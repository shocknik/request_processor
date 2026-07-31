"""ТЗ 70: ручной заказчик/производитель → extraction → order org_id."""

from __future__ import annotations

from pathlib import Path

from request_processor.calculation.cost_calculator import calculate_cost
from request_processor.models import OrganizationExtract, PdfExtractionResult
from request_processor.persistence.sqlite_repo import (
    build_default_hours_map,
    create_order_from_kp,
    get_order_details,
    init_db,
    list_organizations,
    save_calculation,
    save_document_extraction,
    upsert_organization,
)


def _demo_calc(db: Path, mark: str = "МГЛФ") -> int:
    hours = build_default_hours_map(db)
    calc = calculate_cost(mark, ["оформление_протокола"], hours, db)
    return save_calculation(calc, db)


def test_create_order_uses_extraction_org_ids_when_names_missing(tmp_path: Path) -> None:
    """Если КП назвали «заказчик», id с заявки всё равно попадают в order."""
    db = tmp_path / "hitl.db"
    init_db(db)

    cust_id = upsert_organization(
        OrganizationExtract(
            name="ОС ВНИИНМАШ",
            org_type="certification_body",
            role="customer",
            confidence=0.9,
        ),
        source="test",
        db_path=db,
    )
    mfg_id = upsert_organization(
        OrganizationExtract(
            name="Чувашкабель",
            org_type="manufacturer",
            role="manufacturer",
            confidence=0.9,
        ),
        source="test",
        db_path=db,
    )
    extraction_id = save_document_extraction(
        source_path="text://customer_speech",
        source_type="text",
        text="МГЛФ испытания",
        marks_count=1,
        customer_org_id=cust_id,
        manufacturer_org_id=mfg_id,
        db_path=db,
    )

    calc_id = _demo_calc(db)

    order_id = create_order_from_kp(
        customer_name="",  # как «КП_заказчик»
        manufacturer_name=None,
        subject="Проведение сертификационных испытаний",
        calculation_ids=[calc_id],
        kp_output_path=str(tmp_path / "kp.docx"),
        document_extraction_id=extraction_id,
        db_path=db,
    )
    details = get_order_details(order_id, db_path=db)
    assert details is not None
    assert details.get("customer_org_id") == cust_id
    assert details.get("manufacturer_org_id") == mfg_id


def test_manual_org_names_resolve_to_order(tmp_path: Path) -> None:
    db = tmp_path / "hitl2.db"
    init_db(db)
    upsert_organization(
        OrganizationExtract(
            name="АО «Электропровод»",
            org_type="manufacturer",
            role="manufacturer",
            confidence=0.95,
        ),
        source="manual",
        db_path=db,
    )
    calc_id = _demo_calc(db, "КАГЭ")
    order_id = create_order_from_kp(
        customer_name="АО «Электропровод»",
        manufacturer_name="АО «Электропровод»",
        subject="Периодика",
        calculation_ids=[calc_id],
        kp_output_path=str(tmp_path / "kp2.docx"),
        db_path=db,
    )
    details = get_order_details(order_id, db_path=db)
    assert details["customer_org_id"] is not None
    assert details["manufacturer_org_id"] is not None
    orgs = list_organizations(search="Электропровод", db_path=db)
    assert orgs


def test_build_confirmed_result_keeps_manual_orgs(tmp_path: Path) -> None:
    """Поля draft → _build_confirmed_result (без GUI mainloop)."""
    import pytest

    pytest.importorskip("tkinter")
    from request_processor.ui.gui import RequestProcessorApp
    from request_processor.ui.extract_job import prepare_extraction_draft
    from request_processor.models import FieldStatus, MarkValidation

    try:
        app = RequestProcessorApp(db_path=tmp_path / "gui_org.db")
    except Exception as exc:  # noqa: BLE001
        if exc.__class__.__name__ == "TclError":
            pytest.skip(str(exc))
        raise
    app.withdraw()
    try:
        result = PdfExtractionResult(
            source_path="text://customer_speech",
            source_type="text",
            page_count=1,
            text="Просим испытания кабеля Энергия-ВЗ",
            tables=[],
            cable_marks=[],
            organizations=[],
            customer_name="",
            manufacturer_name="",
            is_scanned=False,
            ocr_used=False,
        )
        draft = prepare_extraction_draft(
            result,
            source_path=Path("text_customer_test.txt"),
            json_stem="text_customer_test",
        )
        # оператор добавил марку и org вручную
        draft.marks = [
            MarkValidation(
                mark="Энергия-ВЗ-МКВЭклВКснг(А)-FRLS-УФ",
                confidence=0.9,
                status=FieldStatus.ok,
                accepted=True,
                brand="Энергия-ВЗ",
                cores_count=1,
                structural_element_type="жила",
                structural_elements_count=1,
                characteristic_size=1.0,
                size_unit="mm2",
            )
        ]
        app._extraction_draft = draft
        app.draft_customer_var.set("ООО «Тест-С.-Петербург»")
        app.draft_manufacturer_var.set("Кабельный завод «Энергия»")
        app.draft_customer_addr_var.set("Санкт-Петербург")

        confirmed = app._build_confirmed_result()
        assert confirmed.customer_name == "ООО «Тест-С.-Петербург»"
        assert confirmed.manufacturer_name == "Кабельный завод «Энергия»"
        roles = {o.role: o.name for o in confirmed.organizations}
        assert roles.get("customer") == "ООО «Тест-С.-Петербург»"
        assert roles.get("manufacturer") == "Кабельный завод «Энергия»"
        assert len(confirmed.cable_marks) == 1
    finally:
        app.destroy()
