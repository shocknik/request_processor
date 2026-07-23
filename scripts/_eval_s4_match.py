"""One-shot: match rate for Vulkan-like PPI items (dev helper, not packaged)."""
from __future__ import annotations

from pathlib import Path

from request_processor.persistence.sqlite_repo import (
    create_test_program,
    init_db,
    match_program_items_to_price,
    seed_example_norm_requirements,
)

ITEMS = [
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
CTX = "приемочных испытаний ОК ТУ 27.31.11-131 Кабели оптические огнестойкие"


def main() -> None:
    db = Path("data/_s4_match_eval.db")
    if db.exists():
        db.unlink()
    init_db(db)
    seed_example_norm_requirements(db)
    pid = create_test_program(
        name=CTX,
        test_type="приемочные",
        tu_ref="ТУ 27.31.11-131-47273194-2025",
        items=[{"name": n, "sort_order": i + 1} for i, n in enumerate(ITEMS)],
        db_path=db,
    )
    stats = match_program_items_to_price(pid, db_path=db, overwrite=True)
    print(stats["summary"])
    for d in stats.get("details") or []:
        code = d.get("code") or "—"
        print(f"  [{d.get('method')}] {(d.get('name') or '')[:60]} → {code}")
    db.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
