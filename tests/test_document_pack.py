"""Пакет документов и макет протокола."""

from __future__ import annotations

from pathlib import Path

import pytest

from request_processor.calculation.cost_calculator import calculate_cost
from request_processor.generation.document_pack import build_document_pack
from request_processor.generation.protocol_generator import generate_protocol_draft_from_order
from request_processor.persistence.sqlite_repo import (
    build_default_hours_map,
    create_order_from_kp,
    get_document_pack_settings,
    init_db,
    push_recent_pack_path,
    save_calculation,
)


def _save_demo_calc(db: Path, mark: str = "ВВГнг(А)-LS 3х1,5") -> int:
    hours = build_default_hours_map(db)
    calc = calculate_cost(mark, ["стойкость_к_солнечной_радиации"], hours, db)
    return save_calculation(calc, db)


@pytest.fixture()
def db_with_order(tmp_path: Path) -> tuple[Path, int]:
    db = tmp_path / "pack.db"
    init_db(db)
    calc_id = _save_demo_calc(db)
    kp_path = tmp_path / "КП_demo.docx"
    kp_path.write_bytes(b"PK\x03\x04docx")
    order_id = create_order_from_kp(
        customer_name="ООО Тест-Заказчик",
        manufacturer_name="ООО Тест-Завод",
        subject="Периодические испытания",
        note=None,
        calculation_ids=[calc_id],
        kp_output_path=str(kp_path),
        document_extraction_id=None,
        db_path=db,
    )
    return db, order_id


def test_protocol_draft_created(db_with_order: tuple[Path, int], tmp_path: Path) -> None:
    db, order_id = db_with_order
    out = tmp_path / "protocol.docx"
    path = generate_protocol_draft_from_order(order_id, output_path=out, db_path=db)
    assert path.exists()
    assert path.stat().st_size > 1000


def test_document_pack_folder(db_with_order: tuple[Path, int], tmp_path: Path) -> None:
    db, order_id = db_with_order
    pack = build_document_pack(order_id, output_dir=tmp_path / "packs", db_path=db)
    pack_dir = Path(pack["pack_dir"])
    assert pack_dir.is_dir()
    names = {Path(f).name for f in pack["files"]}
    assert any(n.startswith("Заявка") for n in names)
    assert any("Протокол" in n for n in names)
    assert "summary.json" in names
    assert "README.txt" in names


def test_document_pack_custom_folder_name(
    db_with_order: tuple[Path, int], tmp_path: Path
) -> None:
    db, order_id = db_with_order
    out_base = tmp_path / "exports"
    pack = build_document_pack(
        order_id,
        output_dir=out_base,
        pack_folder_name="Мой_пакет_тест",
        db_path=db,
    )
    pack_dir = Path(pack["pack_dir"])
    assert pack_dir.name == "Мой_пакет_тест"
    assert pack_dir.parent == out_base


def test_push_recent_pack_path(db_with_order: tuple[Path, int], tmp_path: Path) -> None:
    db, order_id = db_with_order
    pack = build_document_pack(order_id, output_dir=tmp_path / "p1", db_path=db)
    push_recent_pack_path(pack["pack_dir"], db)
    settings = get_document_pack_settings(db)
    assert settings.recent_paths
    assert Path(settings.recent_paths[0]) == Path(pack["pack_dir"]).resolve()
