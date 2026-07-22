"""S4 polish: сопоставление пунктов программы с прайсом (ППИ-подобные формулировки)."""

from __future__ import annotations

from pathlib import Path

from request_processor.mapping.program_price_matcher import (
    match_rate_summary,
    resolve_program_item_price_code,
)
from request_processor.persistence.sqlite_repo import (
    create_test_program,
    get_test_program,
    init_db,
    list_test_items,
    load_price_catalog_from_seed,
    match_program_items_to_price,
    seed_example_norm_requirements,
)


# Реальные формулировки с prod ППИ Вулкан (ТУ 27.31.11-131, 14 пунктов)
VULKAN_PPI_ITEMS: list[str] = [
    "Проверка конструкции, конструктивных размеров ОК",
    "Проверка маркировки и упаковки ОК",
    "Измерение коэффициента затухания ОК",
    "Прочность к воздействию многократным изгибам на угол ±90°",
    "Прочность к воздействию одиночного удара",
    "Прочность к воздействию осевого кручения на угол ±180°",
    "Прочность к воздействию раздавливающего усилия",
    "Прочность к воздействию статического изгиба",
    "Прочность к допустимому растягивающему усилию",
    "Стойкость к воздействию повышенной влажности воздуха 98% при температуре 35 оС",
    "Стойкость к воздействию пониженной и повышенной температур окружающей среды",
    "Стойкость к воздействию циклической смене температур от пониженной до повышенной",
    "Подтверждение срока службы",
    "Испытание на огнестойкость (время сохранения работоспособности в условиях воздействия пламени)",
]

VULKAN_CONTEXT = (
    "приемочных испытаний опытных образцов ОК "
    "ТУ 27.31.11-131-47273194-2025 Кабели оптические огнестойкие"
)


def _db_with_price(tmp_path: Path) -> Path:
    db = tmp_path / "match.db"
    init_db(db)
    load_price_catalog_from_seed(db)
    seed_example_norm_requirements(db)
    assert len(list_test_items(limit=500, db_path=db)) >= 20
    return db


def test_match_rate_summary_format() -> None:
    assert match_rate_summary(5, 14) == "сопоставлено 5/14 (36%)"
    assert match_rate_summary(9, 14).startswith("сопоставлено 9/14")


def test_optical_attenuation_not_shielding(tmp_path: Path) -> None:
    db = _db_with_price(tmp_path)
    hit = resolve_program_item_price_code(
        "Измерение коэффициента затухания ОК",
        db_path=db,
        program_context=VULKAN_CONTEXT,
    )
    assert hit is not None
    assert hit.code == "измерение_затухания_оптического_волокнаодного"
    assert "экран" not in hit.code


def test_mechanical_phrase_rules(tmp_path: Path) -> None:
    db = _db_with_price(tmp_path)
    cases = {
        "Прочность к воздействию осевого кручения на угол ±180°": "стойкость_к_осевому_кручению_100_циклов",
        "Прочность к воздействию многократным изгибам на угол ±90°": "стойкость_к_простому_изгибу_100_циклов",
        "Прочность к воздействию одиночного удара": "стойкость_к_удару_при_отрицательной_температуре",
        "Стойкость к воздействию повышенной влажности воздуха 98%": "стойкость_к_повышенной_влажности_воздуха",
        "Стойкость к воздействию циклической смене температур": "стойкость_к_изменению_температуррезкоеплавное",
    }
    for name, code in cases.items():
        hit = resolve_program_item_price_code(name, db_path=db, program_context="")
        assert hit is not None, name
        assert hit.code == code, f"{name} → {hit.code}, want {code}"


def test_optical_fire_from_program_context(tmp_path: Path) -> None:
    db = _db_with_price(tmp_path)
    hit = resolve_program_item_price_code(
        "Испытание на огнестойкость (время сохранения работоспособности в условиях воздействия пламени)",
        db_path=db,
        program_context=VULKAN_CONTEXT,
    )
    assert hit is not None
    assert hit.code == "огнестойкость_оптического_кабеля"


def test_vulkan_ppi_match_rate_improved(tmp_path: Path) -> None:
    """Baseline prod ~5/14 (36%); target ≥ 9/14 (~64%)."""
    db = _db_with_price(tmp_path)
    items = [{"name": n, "sort_order": i + 1} for i, n in enumerate(VULKAN_PPI_ITEMS)]
    pid = create_test_program(
        name=VULKAN_CONTEXT,
        test_type="приемочные",
        tu_ref="ТУ 27.31.11-131-47273194-2025",
        items=items,
        db_path=db,
    )
    # Имитируем «старый» ошибочный code на затухании
    prog = get_test_program(pid, db_path=db)
    assert prog
    for it in prog["items"]:
        if "затухания" in (it.get("name") or "").lower():
            from request_processor.persistence.sqlite_repo import (
                update_program_item_price_code,
            )

            update_program_item_price_code(
                int(it["id"]),
                "измерение_затухания_экранирования",
                db_path=db,
            )

    # without overwrite — keep wrong code, still count as matched
    kept = match_program_items_to_price(pid, db_path=db, overwrite=False)
    assert kept["matched"] >= 1

    stats = match_program_items_to_price(pid, db_path=db, overwrite=True)
    assert stats["total"] == 14
    assert stats["matched"] >= 9, stats
    assert stats["rate"] >= 0.64
    assert "сопоставлено" in stats["summary"]

    prog2 = get_test_program(pid, db_path=db)
    by_name = {it["name"]: it.get("price_test_code") for it in prog2["items"]}
    assert (
        by_name["Измерение коэффициента затухания ОК"]
        == "измерение_затухания_оптического_волокнаодного"
    )
    # пункты без аналога в прайсе остаются пустыми
    assert not by_name.get("Подтверждение срока службы")
    assert not by_name.get("Проверка маркировки и упаковки ОК")
