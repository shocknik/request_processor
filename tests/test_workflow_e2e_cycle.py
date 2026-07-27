"""E2E цикл: заявка → марка в расчёт → расчёт → КП → пакет.

Регрессия 2026-07-27:
- mark_var / Entry «Марка кабеля» после «→ В расчёт»
- КП worker не трогает tk-переменные (main thread is not in main loop)
- после КП создаётся заказ; пакет документов собирается
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("tkinter")

from request_processor.calculation.cost_calculator import calculate_cost
from request_processor.generation.document_pack import build_document_pack
from request_processor.generation.kp_generator import generate_kp_from_db
from request_processor.models import FieldStatus, MarkValidation, PdfExtractionResult
from request_processor.persistence.sqlite_repo import (
    build_default_hours_map,
    create_order_from_kp,
    init_db,
    list_orders,
    save_calculation,
)
from request_processor.ui.gui import RequestProcessorApp
from request_processor.ui.state import ExtractionDraft
from request_processor.validation.extraction_validator import validate_extraction


@pytest.fixture
def gui_app(tmp_path):
    try:
        app = RequestProcessorApp(db_path=tmp_path / "e2e.db")
    except Exception as exc:
        if exc.__class__.__name__ == "TclError":
            pytest.skip(f"tkinter недоступен: {exc}")
        raise
    app.withdraw()
    yield app
    try:
        app.destroy()
    except Exception:
        pass


def _seed_draft(app: RequestProcessorApp, tmp_path: Path, mark: str) -> MarkValidation:
    mv = MarkValidation(
        mark=mark,
        confidence=0.9,
        status=FieldStatus.ok,
        accepted=True,
        brand=mark.split()[0] if mark else None,
    )
    result = PdfExtractionResult(
        source_path="e2e.docx",
        source_type="docx",
        page_count=1,
        text="НАПРАВЛЕНИЕ испытательная лаборатория\n" + mark,
        cable_marks=[],
        customer_name="ООО «E2E-Заказчик»",
        manufacturer_name="ООО «E2E-Завод»",
    )
    report = validate_extraction(result)
    draft = ExtractionDraft(
        result=result,
        report=report,
        source_path=Path("e2e.docx"),
        json_path=tmp_path / "e2e.json",
        marks=[mv],
        original_marks=[mv.model_copy(deep=True)],
        original_customer=result.customer_name or "",
        original_manufacturer=result.manufacturer_name or "",
    )
    draft.json_path.write_text("{}", encoding="utf-8")
    app._extraction_draft = draft
    app._extraction_confirmed = True
    app.kp_customer_var.set(result.customer_name or "")
    app._last_manufacturer_name = result.manufacturer_name or ""
    app._refresh_marks_tree()
    app.marks_tree.selection_set("0")
    return mv


def test_use_mark_fills_calc_mark_entry_field(gui_app: RequestProcessorApp, tmp_path) -> None:
    """→ В расчёт: StringVar И Entry «Марка кабеля» содержат марку."""
    mark = "КГРвЭСТ 3*35+16/3в+3*2,5 - 1140"
    _seed_draft(gui_app, tmp_path, mark)
    gui_app.deiconify()
    gui_app._use_mark_in_calc()
    gui_app.update_idletasks()
    assert gui_app.mark_var.get().strip() == mark
    assert hasattr(gui_app, "calc_mark_entry")
    assert gui_app.calc_mark_entry.get().strip() == mark
    assert gui_app.notebook.index(gui_app.notebook.select()) == gui_app.notebook.index(
        gui_app.tab_calc
    )


def test_backend_cycle_calc_kp_order_pack(tmp_path: Path) -> None:
    """Без GUI: расчёт → КП docx → заказ → пакет документов."""
    db = tmp_path / "cycle.db"
    init_db(db)
    hours = build_default_hours_map(db)
    mark = "ВВГнг(А) 3х2,5"
    calc = calculate_cost(
        mark,
        ["обработка_заявки", "оформление_протокола", "базовая_подготовка_образцов"],
        hours,
        db,
    )
    calc_id = save_calculation(calc, db)
    assert calc_id > 0

    out = tmp_path / "generated"
    out.mkdir()
    kp_path = out / "КП_e2e.docx"
    saved = generate_kp_from_db(
        customer="ООО «E2E-Заказчик»",
        subject="Сертификационные испытания",
        calculation_ids=[calc_id],
        output_path=kp_path,
        db_path=db,
        note=None,
        style="classic",
    )
    assert saved.exists()
    assert saved.stat().st_size > 500

    order_id = create_order_from_kp(
        customer_name="ООО «E2E-Заказчик»",
        manufacturer_name="ООО «E2E-Завод»",
        subject="Сертификационные испытания",
        note=None,
        calculation_ids=[calc_id],
        kp_output_path=str(saved),
        document_extraction_id=None,
        db_path=db,
    )
    assert order_id > 0
    orders = list_orders(db_path=db)
    assert any(o["id"] == order_id for o in orders)

    pack = build_document_pack(
        order_id,
        output_dir=tmp_path / "packs",
        pack_folder_name="E2E_pack",
        db_path=db,
    )
    pack_dir = Path(pack["pack_dir"])
    assert pack_dir.is_dir()
    assert pack_dir.name == "E2E_pack"
    names = {Path(f).name for f in pack["files"]}
    assert "summary.json" in names
    assert "README.txt" in names
    assert any("Заявка" in n or "заявка" in n.lower() for n in names) or any(
        n.endswith(".docx") for n in names
    )


def test_gui_kp_worker_does_not_touch_tk_vars(gui_app: RequestProcessorApp, tmp_path) -> None:
    """КП: style читается на main thread; worker не вызывает kp_style_var.get()."""
    db = gui_app.db_path
    hours = build_default_hours_map(db)
    calc = calculate_cost(
        "ВВГ 3х1,5",
        ["обработка_заявки"],
        hours,
        db,
    )
    calc_id = save_calculation(calc, db)
    gui_app.kp_customer_var.set("ООО Тест")
    gui_app._load_kp_calculations()
    gui_app.update_idletasks()
    # выделить расчёт
    children = gui_app.kp_calc_tree.get_children()
    assert children, "kp calc list empty"
    # найти iid по id
    target = None
    for iid in children:
        vals = gui_app.kp_calc_tree.item(iid, "values")
        if vals and int(vals[0]) == calc_id:
            target = iid
            break
    if target is None:
        target = children[0]
    gui_app.kp_calc_tree.selection_set(target)

    style_probe = MagicMock(side_effect=RuntimeError("tk from worker!"))
    # подмена get только если вызовут из worker после старта — проще: spy
    original_get = gui_app.kp_style_var.get
    calls: list[str] = []

    def tracked_get(*a, **k):
        import threading

        name = threading.current_thread().name
        calls.append(name)
        if name != "MainThread":
            raise RuntimeError(f"kp_style_var.get from non-main thread: {name}")
        return original_get(*a, **k)

    gui_app.kp_style_var.get = tracked_get  # type: ignore[method-assign]

    real_gen = generate_kp_from_db
    done = {"ok": False, "err": None}

    def fake_gen(**kwargs):
        # style already plain str
        assert kwargs.get("style") is None or isinstance(kwargs.get("style"), str)
        path = tmp_path / "kp_gui.docx"
        path.write_bytes(b"PK\x03\x04fake")
        return path

    with patch(
        "request_processor.ui.tabs.kp_tab.generate_kp_from_db",
        side_effect=fake_gen,
    ):
        with patch(
            "request_processor.ui.tabs.kp_tab.create_order_from_kp",
            return_value=99,
        ):
            with patch("request_processor.ui.tabs.kp_tab.messagebox.showinfo"):
                with patch("request_processor.ui.tabs.kp_tab.messagebox.showerror") as err:
                    gui_app._run_generate_kp()
                    # дать worker + after callbacks
                    for _ in range(30):
                        gui_app.update()
                        import time

                        time.sleep(0.05)
                        if err.called:
                            done["err"] = err.call_args
                            break
                        # success: status mentions Заказ
                        st = gui_app.status.get() if hasattr(gui_app, "status") else ""
                        if "Заказ" in st or "КП" in st:
                            done["ok"] = True
                            break

    assert not done["err"], f"KP failed: {done['err']}"
    # style get только с MainThread
    assert all(c == "MainThread" for c in calls), calls
    # хотя бы один вызов get на main (чтение style перед thread)
    assert calls, "kp_style_var.get was never called on main thread"


def test_pack_dialog_defaults_and_sync_build(
    gui_app: RequestProcessorApp, tmp_path: Path
) -> None:
    """Диалог пакета отдаёт пути; build_document_pack на main thread создаёт файлы."""
    db = gui_app.db_path
    hours = build_default_hours_map(db)
    calc = calculate_cost("ВВГ 3х1,5", ["обработка_заявки"], hours, db)
    calc_id = save_calculation(calc, db)
    kp_path = tmp_path / "kp.docx"
    saved = generate_kp_from_db(
        customer="ООО Пакет",
        subject="Тест",
        calculation_ids=[calc_id],
        output_path=kp_path,
        db_path=db,
        style="classic",
    )
    order_id = create_order_from_kp(
        customer_name="ООО Пакет",
        manufacturer_name=None,
        subject="Тест",
        note=None,
        calculation_ids=[calc_id],
        kp_output_path=str(saved),
        document_extraction_id=None,
        db_path=db,
    )
    gui_app._load_orders_table()
    gui_app.orders_tree.selection_set(str(order_id))

    # Не открываем modal: подменяем dialog
    out = tmp_path / "pack_out"
    out.mkdir()
    with patch.object(
        gui_app,
        "_ask_document_pack_options",
        return_value={
            "output_dir": str(out),
            "pack_folder_name": f"gui_pack_{order_id}",
        },
    ):
        with patch("request_processor.ui.tabs.orders_tab.messagebox.showinfo"):
            with patch("request_processor.ui.tabs.orders_tab.messagebox.showerror") as err:
                gui_app._build_order_document_pack()
                assert not err.called, err.call_args
    pack_dir = out / f"gui_pack_{order_id}"
    assert pack_dir.is_dir()
    names = {p.name for p in pack_dir.iterdir()}
    assert "summary.json" in names
    assert "README.txt" in names
    assert any(n.endswith(".docx") for n in names)


def test_gui_full_cycle_mark_calc_entry_then_backend_pack(
    gui_app: RequestProcessorApp, tmp_path
) -> None:
    """GUI: марка в поле + расчёт; backend: КП/заказ/пакет от calc_id."""
    mark = "АПуВ 1х6"
    _seed_draft(gui_app, tmp_path, mark)
    gui_app.deiconify()
    gui_app._use_mark_in_calc()
    gui_app.update_idletasks()
    assert gui_app.calc_mark_entry.get().strip() == mark

    # добавить испытание и посчитать синхронно (без thread flakiness)
    code = "обработка_заявки"
    if code not in gui_app._tests_by_code and gui_app._tests_by_code:
        code = next(iter(gui_app._tests_by_code))
    gui_app._add_test_to_calc(code)
    assert any(e.code == code for e in gui_app._calc_entries)

    hours = build_default_hours_map(gui_app.db_path)
    calc = calculate_cost(mark, [code], hours, gui_app.db_path)
    calc_id = save_calculation(calc, gui_app.db_path)

    kp_path = tmp_path / "КП_cycle.docx"
    saved = generate_kp_from_db(
        customer=gui_app.kp_customer_var.get() or "ООО Тест",
        subject="Сертификационные испытания",
        calculation_ids=[calc_id],
        output_path=kp_path,
        db_path=gui_app.db_path,
        style="classic",
    )
    order_id = create_order_from_kp(
        customer_name=gui_app.kp_customer_var.get() or "ООО Тест",
        manufacturer_name=gui_app._last_manufacturer_name or None,
        subject="Сертификационные испытания",
        note=None,
        calculation_ids=[calc_id],
        kp_output_path=str(saved),
        document_extraction_id=None,
        db_path=gui_app.db_path,
    )
    pack = build_document_pack(
        order_id,
        output_dir=tmp_path / "packs",
        pack_folder_name="cycle_pack",
        db_path=gui_app.db_path,
    )
    assert Path(pack["pack_dir"]).is_dir()
    assert len(pack["files"]) >= 2
