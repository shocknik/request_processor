"""S5: norm documents, requirements, aliases."""

from __future__ import annotations

from pathlib import Path

from request_processor.persistence.sqlite_repo import (
    add_test_alias,
    init_db,
    list_norm_documents,
    list_requirements,
    list_test_aliases,
    resolve_test_alias,
    seed_example_norm_requirements,
)


def test_seed_and_list(tmp_path: Path) -> None:
    db = tmp_path / "n.db"
    init_db(db)
    # seed runs inside init/migrate; call again idempotent
    seed_example_norm_requirements(db)
    docs = list_norm_documents(db_path=db)
    assert any(d["kind"] == "tu" for d in docs)
    reqs = list_requirements(db_path=db)
    assert len(reqs) >= 2
    aliases = list_test_aliases(db_path=db)
    assert any("жил" in a["alias_norm"] for a in aliases)


def test_add_and_resolve_alias(tmp_path: Path) -> None:
    db = tmp_path / "n.db"
    init_db(db)
    add_test_alias(
        "омическая асимметрия пар",
        "Омическая асимметрия",
        price_test_code=None,
        db_path=db,
    )
    hit = resolve_test_alias("нужна омическая асимметрия пар в кабеле", db_path=db)
    assert hit is not None
    assert "асимметр" in hit["canonical_name"].lower()
