"""Роли БД: dev / work_copy / work."""

from __future__ import annotations

from pathlib import Path

from request_processor.persistence.db_profile import (
    load_db_profile,
    save_db_profile,
    set_db_role,
    format_db_info,
    DbProfile,
)


def test_missing_profile_defaults_to_dev(tmp_path: Path) -> None:
    db = tmp_path / "app.db"
    db.write_bytes(b"sqlite")  # fingerprint only
    prof = load_db_profile(db)
    assert prof.role == "dev"
    assert prof.is_dev_scratch
    assert not prof.is_source_of_truth
    assert "не размечена" in prof.ui_label().lower() or "тестов" in prof.ui_label().lower()


def test_set_work_copy_is_source_of_truth(tmp_path: Path) -> None:
    db = tmp_path / "app.db"
    db.write_bytes(b"x" * 100)
    prof = set_db_role(
        "work_copy",
        db_path=db,
        source="рабочий ПК тест",
        notes="импорт",
    )
    assert prof.role == "work_copy"
    assert prof.is_source_of_truth
    assert not prof.is_dev_scratch
    assert "рабоч" in prof.source

    path = tmp_path / "db_profile.local.yaml"
    assert path.is_file()
    again = load_db_profile(db)
    assert again.role == "work_copy"
    assert again.source == "рабочий ПК тест"


def test_other_db_file_has_own_profile_sidecar(tmp_path: Path) -> None:
    """Две БД в одном каталоге не делят одну метку."""
    from request_processor.persistence.db_profile import profile_path_for_db

    main = tmp_path / "app.db"
    other = tmp_path / "test_smoke.db"
    main.write_bytes(b"a")
    other.write_bytes(b"b")
    set_db_role("work_copy", db_path=main, source="work")
    set_db_role("dev", db_path=other, source="tests")
    assert profile_path_for_db(main).name == "db_profile.local.yaml"
    assert profile_path_for_db(other).name == "test_smoke.db.profile.yaml"
    assert load_db_profile(main).role == "work_copy"
    assert load_db_profile(other).role == "dev"


def test_window_title_and_status_differ_by_role(tmp_path: Path) -> None:
    db = tmp_path / "app.db"
    db.write_bytes(b"1")
    dev = set_db_role("dev", db_path=db)
    work = set_db_role("work_copy", db_path=db, source="W")
    assert "DEV" in dev.window_title_suffix()
    assert "WORK-COPY" in work.window_title_suffix()
    assert "не источник" in dev.status_line()
    assert "копия" in work.status_line().lower() or "WORK" in work.window_title_suffix()


def test_format_db_info_mentions_path(tmp_path: Path) -> None:
    db = tmp_path / "app.db"
    db.write_bytes(b"abc")
    set_db_role("dev", db_path=db)
    text = format_db_info(db)
    assert "dev" in text
    assert str(db.resolve()) in text or "app.db" in text


def test_save_roundtrip_custom_label(tmp_path: Path) -> None:
    db = tmp_path / "app.db"
    db.write_bytes(b"z")
    p = DbProfile(role="work", label="боевая", source="lab desk", notes="ok")
    save_db_profile(p, db)
    loaded = load_db_profile(db)
    assert loaded.role == "work"
    assert loaded.label == "боевая"
    assert loaded.is_source_of_truth
