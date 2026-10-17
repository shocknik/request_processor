"""Тип организации «проектировщик» (designer)."""

from __future__ import annotations

from pathlib import Path

import pytest

from request_processor.extraction.organization_extractor import _infer_org_type
from request_processor.models import ORGANIZATION_TYPES, OrganizationExtract
from request_processor.persistence.sqlite_repo import (
    create_organization,
    get_organization_by_id,
    init_db,
)
from request_processor.ui.state import (
    ORG_TYPE_LABELS,
    ORG_TYPE_ROW_COLORS,
    org_type_from_label,
    org_type_tree_tag,
)


def test_designer_in_type_catalog() -> None:
    assert "designer" in ORGANIZATION_TYPES
    assert ORG_TYPE_LABELS["designer"] == "Проектировщик"
    assert "designer" in ORG_TYPE_ROW_COLORS
    assert org_type_from_label("Проектировщик") == "designer"
    assert org_type_from_label("designer") == "designer"
    assert org_type_tree_tag("designer") == "orgtype_designer"


def test_infer_designer_from_name_and_text() -> None:
    assert _infer_org_type("", "ООО «Проектировщик-Север»") == "designer"
    assert _infer_org_type("генпроектировщик объекта", "ООО СтройПроект") == "designer"
    assert _infer_org_type("", "АО Проектный институт") == "designer"
    assert _infer_org_type("", "ООО Кабельный завод") == "manufacturer"


def test_create_designer_organization(tmp_path: Path) -> None:
    db = tmp_path / "orgs.db"
    init_db(db)
    org_id = create_organization(
        name="ООО ПроектКабель",
        org_type="designer",
        db_path=db,
    )
    row = get_organization_by_id(org_id, db)
    assert row is not None
    assert row["org_type"] == "designer"
    extract = OrganizationExtract(name="ООО ПроектКабель", org_type="designer", role="customer")
    assert extract.org_type == "designer"


def test_orgs_editor_lists_designer_label(tmp_path: Path) -> None:
    pytest.importorskip("tkinter")
    from request_processor.ui.gui import RequestProcessorApp

    db = tmp_path / "orgs_ui.db"
    init_db(db)
    org_id = create_organization(name="ООО Проект UI", org_type="designer", db_path=db)
    try:
        app = RequestProcessorApp(db_path=db)
    except Exception as exc:
        if exc.__class__.__name__ == "TclError":
            pytest.skip(f"tkinter недоступен: {exc}")
        raise
    app.withdraw()
    try:
        app._load_orgs_table()
        tags = app.orgs_tree.item(str(org_id), "tags")
        assert org_type_tree_tag("designer") in tags
        values = app.orgs_tree.item(str(org_id), "values")
        assert "Проектировщик" in values
        legend_texts = [
            child.cget("text")
            for chip in app.orgs_legend.winfo_children()
            for child in chip.winfo_children()
            if child.winfo_class() == "Label"
        ]
        assert "Проектировщик" in legend_texts
    finally:
        app.destroy()
