"""Журнал пожеланий 13–16.10.2026: макет протокола (#16) и цвет журнала орг. (#14)."""

from __future__ import annotations

from pathlib import Path

import pytest

from request_processor.persistence.sqlite_repo import create_organization, init_db
from request_processor.ui.state import (
    ORG_TYPE_LABELS,
    ORG_TYPE_ROW_COLORS,
    org_type_tree_tag,
)


def test_org_type_tree_tag_known_and_unknown() -> None:
    assert org_type_tree_tag("manufacturer") == "orgtype_manufacturer"
    assert org_type_tree_tag("dealer") == "orgtype_dealer"
    assert org_type_tree_tag(None) == "orgtype_unknown"
    assert org_type_tree_tag("  ") == "orgtype_unknown"
    assert org_type_tree_tag("not_a_type") == "orgtype_unknown"
    assert set(ORG_TYPE_ROW_COLORS) == set(ORG_TYPE_LABELS)


def test_orders_ui_hides_protocol_mock_menu() -> None:
    src = Path("src/request_processor/ui/tabs/orders_tab.py").read_text(encoding="utf-8")
    assert 'label="Макет протокола' not in src
    assert "_generate_order_protocol" not in src


def test_orgs_journal_rows_tagged_by_type(tmp_path: Path) -> None:
    pytest.importorskip("tkinter")
    from request_processor.ui.gui import RequestProcessorApp

    db = tmp_path / "orgs_color.db"
    init_db(db)
    ids = {
        "manufacturer": create_organization(
            name="ООО Завод Цвет", org_type="manufacturer", db_path=db
        ),
        "testing_center": create_organization(
            name="ООО ИЦ Цвет", org_type="testing_center", db_path=db
        ),
        "unknown": create_organization(name="ООО Без типа Цвет", db_path=db),
    }
    try:
        app = RequestProcessorApp(db_path=db)
    except Exception as exc:
        if exc.__class__.__name__ == "TclError":
            pytest.skip(f"tkinter недоступен: {exc}")
        raise
    app.withdraw()
    try:
        assert hasattr(app, "orgs_legend")
        app._load_orgs_table()
        for type_key, org_id in ids.items():
            tags = app.orgs_tree.item(str(org_id), "tags")
            assert org_type_tree_tag(type_key) in tags
    finally:
        app.destroy()
