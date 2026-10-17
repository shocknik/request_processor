"""Чередование строк журналов (соседние позиции)."""

from __future__ import annotations

from pathlib import Path

import pytest

from request_processor.persistence.sqlite_repo import create_organization, init_db
from request_processor.ui.widgets.tree_rows import TAG_EVEN, TAG_ODD, zebra_tags


def test_zebra_tags_alternate() -> None:
    assert zebra_tags(0) == (TAG_EVEN,)
    assert zebra_tags(1) == (TAG_ODD,)
    assert zebra_tags(2) == (TAG_EVEN,)


def test_journal_trees_have_zebra_rows(tmp_path: Path) -> None:
    pytest.importorskip("tkinter")
    from request_processor.calculation.cost_calculator import calculate_cost
    from request_processor.persistence.sqlite_repo import save_calculation
    from request_processor.ui.gui import RequestProcessorApp

    db = tmp_path / "zebra.db"
    init_db(db)
    create_organization(name="ООО Зебра-1", db_path=db)
    create_organization(name="ООО Зебра-2", db_path=db)
    c1 = calculate_cost("ВВГ 3х2,5", ["испытание_напряжением"], db_path=db, apply_minimum=False)
    save_calculation(c1, db)
    c2 = calculate_cost("ВВГ 5х2,5", ["испытание_напряжением"], db_path=db, apply_minimum=False)
    save_calculation(c2, db)
    try:
        app = RequestProcessorApp(db_path=db)
    except Exception as exc:
        if exc.__class__.__name__ == "TclError":
            pytest.skip(f"tkinter недоступен: {exc}")
        raise
    app.withdraw()
    try:
        app._load_history()
        kids = app.history_tree.get_children()
        assert len(kids) >= 2
        assert TAG_EVEN in app.history_tree.item(kids[0], "tags")
        assert TAG_ODD in app.history_tree.item(kids[1], "tags")
        app._load_cable_marks()
        app._load_orders_table()
        app._load_kp_calculations()
        kids_kp = app.kp_calc_tree.get_children()
        assert len(kids_kp) >= 2
        assert TAG_EVEN in app.kp_calc_tree.item(kids_kp[0], "tags")
        assert TAG_ODD in app.kp_calc_tree.item(kids_kp[1], "tags")
    finally:
        app.destroy()
