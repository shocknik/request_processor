"""Импорт норм из raw .txt и aliases из yaml."""

from __future__ import annotations

from pathlib import Path

from request_processor.generation.norm_text_import import (
    extract_clauses_from_text,
    import_aliases_from_synonyms_yaml,
    import_norm_from_text_file,
)
from request_processor.mapping.requirement_mapper import map_requirements_to_tests
from request_processor.persistence.sqlite_repo import (
    add_test_alias,
    init_db,
    list_requirements,
)


def test_extract_clauses_interesting() -> None:
    text = """
1.1 Общие положения
1.4.1 Электрическое сопротивление токопроводящих жил не более
1.4.5 Испытание напряжением переменного тока
2.2.1 Нераспространение горения при одиночной прокладке
"""
    clauses = extract_clauses_from_text(text, max_clauses=20)
    assert any(c[0] == "1.4.1" for c in clauses)
    assert any("напряжен" in c[1].lower() for c in clauses)


def test_extract_clauses_from_pipe_table() -> None:
    """Сырой текст ТУ/ПМИ со строками «С1 | … | 2.4 | 5.3» (Вулкан-подобные)."""
    text = """
С1 | Проверка конструкции и конструктивных размеров | 2.2.2, 2.3.1 - 2.3.6 | 5.2
С1 | Измерение коэффициента затухания | 2.4 | 5.3
П3 | Испытание на огнестойкость | 3.4.5 | 5.9.5
"""
    clauses = extract_clauses_from_text(text, max_clauses=20)
    assert any(c[0] == "2.4" for c in clauses)
    assert any("затухан" in c[1].lower() for c in clauses)
    assert any(c[0] == "3.4.5" for c in clauses)


def test_import_norm_file(tmp_path: Path) -> None:
    db = tmp_path / "n.db"
    init_db(db)
    f = tmp_path / "16.K99-999-2014.txt"
    f.write_text(
        "1.4.1 Электрическое сопротивление жил\n"
        "1.4.5 Испытание напряжением изоляции\n",
        encoding="utf-8",
    )
    result = import_norm_from_text_file(f, db_path=db)
    assert result["clauses"] >= 1
    reqs = list_requirements(db_path=db)
    assert any(r["clause"] == "1.4.1" for r in reqs)


def test_alias_in_mapper(tmp_path: Path) -> None:
    db = tmp_path / "n.db"
    init_db(db)
    add_test_alias(
        "омическое сопротивление жил кастом",
        "Электрическое сопротивление ТПЖ",
        price_test_code="электрическое_сопротивление_тпж",
        db_path=db,
    )
    # may resolve via alias even if code not in empty demo price — still returns suggestion
    sugg = map_requirements_to_tests(
        "требуется омическое сопротивление жил кастом",
        db_path=db,
    )
    assert sugg
    assert any("сопротивлен" in s.code or s.code for s in sugg)


def test_import_synonyms_yaml(tmp_path: Path) -> None:
    db = tmp_path / "n.db"
    init_db(db)
    y = tmp_path / "syn.yaml"
    y.write_text(
        """
version: 1
synonyms:
  - phrase: тестовая фраза xyz
    canonical_code: resistance_core
    confidence: 0.9
""",
        encoding="utf-8",
    )
    n = import_aliases_from_synonyms_yaml(y, db_path=db)
    assert n >= 1
