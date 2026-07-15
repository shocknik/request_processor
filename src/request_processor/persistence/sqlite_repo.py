"""
sqlite_repo.py — слой работы с базой данных SQLite.

Это "репозиторий" (Repository pattern). 
Он полностью отвечает за:
- Создание таблиц
- Загрузку прайс-листа из Excel
- Сохранение и получение расчётов
- Seed демо-данных для быстрого старта

Почему отдельный файл:
- Вся работа с БД в одном месте → легко менять на PostgreSQL позже
- Чистый sqlite3 (без SQLAlchemy) — просто и понятно на старте
- Все запросы параметризованы (защита от SQL-инъекций)
- Используем контекстный менеджер для безопасной работы с соединением

Структура таблиц (Итерация 1):
- test_items — справочник испытаний (из прайс-листа)
- calculations — заголовок одного расчёта (марка + итоги)
- calculation_lines — детальные строки (каждое испытание в расчёте)
"""

from __future__ import annotations

import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from ..models import (
    AssistantLlmSettings,
    Calculation,
    CalculationLine,
    CableMarkRecord,
    ClimaticTestSettings,
    DocumentPackSettings,
    OrganizationExtract,
    TestItem,
    TestItemUpdate,
    TestItemCreate,
)
from ..extraction.organization_extractor import normalize_org_name
from ..parsing.cable_mark_parser import parse_cable_mark_record
from ..calculation.climatic_tests import (
    CLIMATE_ITEM_ALIASES,
    CLIMATE_SLUG_BY_HOURS_KEY,
    CLIMATIC_TESTS,
    DEPRECATED_CLIMATE_ITEM_CODES,
    climatic_settings_fields,
)
from ..calculation.test_rules import DEFAULT_PRICE_XLSX, infer_rule_type

# Корень проекта (не зависит от текущей рабочей директории при запуске GUI/CLI)
from ..config import DB_PATH_DEFAULT, GENERATED_DIR_DEFAULT, PROJECT_ROOT


def resolve_db_path(db_path: str | Path = DB_PATH_DEFAULT) -> Path:
    """Абсолютный путь к БД; относительные пути — от cwd, кроме стандартного data/app.db."""
    p = Path(db_path)
    if p.is_absolute():
        return p
    if p.as_posix() == "data/app.db":
        return (PROJECT_ROOT / p).resolve()
    return (Path.cwd() / p).resolve()


@contextmanager
def get_connection(db_path: str | Path = DB_PATH_DEFAULT):
    """
    Контекстный менеджер подключения к SQLite.
    
    Преимущества:
    - Автоматически commit при успехе и close при любом исходе
    - Включает foreign_keys (для целостности данных)
    - row_factory = sqlite3.Row → можно обращаться как к dict
    """
    db_path = resolve_db_path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(db_path: str | Path = DB_PATH_DEFAULT) -> None:
    """
    Создаёт структуру базы данных + seed демо-данных.
    
    Вызывается командой: python -m cli init-db
    """
    schema = """
    CREATE TABLE IF NOT EXISTS test_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        base_cost REAL NOT NULL,
        category TEXT,
        method TEXT,
        rule_type TEXT DEFAULT 'fixed',
        rule_params TEXT DEFAULT '{}'
    );

    CREATE TABLE IF NOT EXISTS calculations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        mark TEXT NOT NULL,
        parsed_mark TEXT NOT NULL,           -- JSON строки CableMark
        total_cost_without_vat REAL NOT NULL,
        vat_rate REAL NOT NULL DEFAULT 0.22,
        total_cost_with_vat REAL NOT NULL,
        source TEXT DEFAULT 'manual',
        output_path TEXT,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS calculation_lines (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        calculation_id INTEGER NOT NULL,
        test_item_id INTEGER,
        test_name TEXT NOT NULL,
        base_cost REAL NOT NULL,
        multiplier REAL DEFAULT 1.0,
        hours REAL,
        final_cost REAL NOT NULL,
        note TEXT,
        FOREIGN KEY (calculation_id) REFERENCES calculations(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS cable_marks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        full_mark TEXT NOT NULL UNIQUE,
        brand TEXT NOT NULL,
        fire_class TEXT,
        cores_count INTEGER NOT NULL,
        structural_element_type TEXT,
        structural_elements_count INTEGER,
        characteristic_size REAL NOT NULL,
        size_unit TEXT NOT NULL DEFAULT 'mm2',
        document TEXT,
        source TEXT,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS app_settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS organizations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        name_normalized TEXT NOT NULL,
        address TEXT,
        legal_address TEXT,
        actual_address TEXT,
        postal_code TEXT,
        phone TEXT,
        email TEXT,
        inn TEXT,
        kpp TEXT,
        is_accredited INTEGER NOT NULL DEFAULT 0,
        fsa_registry_number TEXT,
        org_type TEXT NOT NULL DEFAULT 'unknown',
        source TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS document_extractions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_path TEXT NOT NULL,
        source_type TEXT NOT NULL,
        customer_org_id INTEGER,
        manufacturer_org_id INTEGER,
        subject TEXT,
        raw_text_length INTEGER,
        marks_count INTEGER NOT NULL DEFAULT 0,
        extracted_at TEXT NOT NULL,
        FOREIGN KEY (customer_org_id) REFERENCES organizations(id),
        FOREIGN KEY (manufacturer_org_id) REFERENCES organizations(id)
    );

    CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_org_id INTEGER,
        manufacturer_org_id INTEGER,
        subject TEXT,
        note TEXT,
        status TEXT NOT NULL DEFAULT 'kp_generated',
        total_without_vat REAL NOT NULL DEFAULT 0,
        total_with_vat REAL NOT NULL DEFAULT 0,
        vat_rate REAL NOT NULL DEFAULT 0.22,
        document_extraction_id INTEGER,
        kp_output_path TEXT,
        application_path TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (customer_org_id) REFERENCES organizations(id),
        FOREIGN KEY (manufacturer_org_id) REFERENCES organizations(id),
        FOREIGN KEY (document_extraction_id) REFERENCES document_extractions(id)
    );

    CREATE TABLE IF NOT EXISTS order_marks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER NOT NULL,
        calculation_id INTEGER NOT NULL,
        cable_mark_id INTEGER,
        manufacturer_org_id INTEGER,
        mark TEXT NOT NULL,
        total_without_vat REAL NOT NULL,
        total_with_vat REAL NOT NULL,
        FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
        FOREIGN KEY (calculation_id) REFERENCES calculations(id),
        FOREIGN KEY (cable_mark_id) REFERENCES cable_marks(id),
        FOREIGN KEY (manufacturer_org_id) REFERENCES organizations(id)
    );

    CREATE INDEX IF NOT EXISTS idx_test_items_code ON test_items(code);
    CREATE INDEX IF NOT EXISTS idx_calculations_created_at ON calculations(created_at);
    CREATE INDEX IF NOT EXISTS idx_cable_marks_brand ON cable_marks(brand);
    CREATE UNIQUE INDEX IF NOT EXISTS idx_organizations_dedup
        ON organizations(COALESCE(inn, ''), name_normalized);
    CREATE INDEX IF NOT EXISTS idx_organizations_name ON organizations(name_normalized);
    CREATE INDEX IF NOT EXISTS idx_orders_created_at ON orders(created_at);
    CREATE INDEX IF NOT EXISTS idx_order_marks_order_id ON order_marks(order_id);

    CREATE TABLE IF NOT EXISTS test_applications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER NOT NULL,
        output_path TEXT NOT NULL,
        template_path TEXT,
        application_number TEXT,
        test_type TEXT,
        customer_name TEXT,
        manufacturer_name TEXT,
        marks_count INTEGER NOT NULL DEFAULT 0,
        marks_snapshot TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_test_applications_order_id ON test_applications(order_id);
    CREATE INDEX IF NOT EXISTS idx_test_applications_created_at ON test_applications(created_at);
    """

    with get_connection(db_path) as conn:
        conn.executescript(schema)

    migrate_db(db_path)
    _seed_demo_tests(db_path)
    _seed_default_settings(db_path)
    print(f"База данных инициализирована: {db_path}")


def migrate_db(db_path: str | Path = DB_PATH_DEFAULT) -> None:
    """Добавляет новые таблицы в существующие БД без пересоздания."""
    with get_connection(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS cable_marks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                full_mark TEXT NOT NULL UNIQUE,
                brand TEXT NOT NULL,
                fire_class TEXT,
                cores_count INTEGER NOT NULL,
                structural_element_type TEXT,
                structural_elements_count INTEGER,
                characteristic_size REAL NOT NULL,
                size_unit TEXT NOT NULL DEFAULT 'mm2',
                document TEXT,
                source TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS organizations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                name_normalized TEXT NOT NULL,
                address TEXT,
                legal_address TEXT,
                actual_address TEXT,
                postal_code TEXT,
                phone TEXT,
                email TEXT,
                inn TEXT,
                kpp TEXT,
                is_accredited INTEGER NOT NULL DEFAULT 0,
                fsa_registry_number TEXT,
                org_type TEXT NOT NULL DEFAULT 'unknown',
                source TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS document_extractions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_path TEXT NOT NULL,
                source_type TEXT NOT NULL,
                customer_org_id INTEGER,
                manufacturer_org_id INTEGER,
                subject TEXT,
                raw_text_length INTEGER,
                marks_count INTEGER NOT NULL DEFAULT 0,
                extracted_at TEXT NOT NULL,
                FOREIGN KEY (customer_org_id) REFERENCES organizations(id),
                FOREIGN KEY (manufacturer_org_id) REFERENCES organizations(id)
            );
            CREATE INDEX IF NOT EXISTS idx_cable_marks_brand ON cable_marks(brand);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_organizations_dedup
                ON organizations(COALESCE(inn, ''), name_normalized);
            CREATE INDEX IF NOT EXISTS idx_organizations_name ON organizations(name_normalized);
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_org_id INTEGER,
                manufacturer_org_id INTEGER,
                subject TEXT,
                note TEXT,
                status TEXT NOT NULL DEFAULT 'kp_generated',
                total_without_vat REAL NOT NULL DEFAULT 0,
                total_with_vat REAL NOT NULL DEFAULT 0,
                vat_rate REAL NOT NULL DEFAULT 0.22,
                document_extraction_id INTEGER,
                kp_output_path TEXT,
                application_path TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (customer_org_id) REFERENCES organizations(id),
                FOREIGN KEY (manufacturer_org_id) REFERENCES organizations(id),
                FOREIGN KEY (document_extraction_id) REFERENCES document_extractions(id)
            );
            CREATE TABLE IF NOT EXISTS order_marks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                calculation_id INTEGER NOT NULL,
                cable_mark_id INTEGER,
                manufacturer_org_id INTEGER,
                mark TEXT NOT NULL,
                total_without_vat REAL NOT NULL,
                total_with_vat REAL NOT NULL,
                FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
                FOREIGN KEY (calculation_id) REFERENCES calculations(id),
                FOREIGN KEY (cable_mark_id) REFERENCES cable_marks(id),
                FOREIGN KEY (manufacturer_org_id) REFERENCES organizations(id)
            );
            CREATE INDEX IF NOT EXISTS idx_orders_created_at ON orders(created_at);
            CREATE INDEX IF NOT EXISTS idx_order_marks_order_id ON order_marks(order_id);
            CREATE TABLE IF NOT EXISTS test_applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                output_path TEXT NOT NULL,
                template_path TEXT,
                application_number TEXT,
                test_type TEXT,
                customer_name TEXT,
                manufacturer_name TEXT,
                marks_count INTEGER NOT NULL DEFAULT 0,
                marks_snapshot TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_test_applications_order_id ON test_applications(order_id);
            CREATE INDEX IF NOT EXISTS idx_test_applications_created_at ON test_applications(created_at);
            CREATE TABLE IF NOT EXISTS test_mappings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                requirement_pattern TEXT NOT NULL UNIQUE,
                test_code TEXT NOT NULL,
                note TEXT,
                usage_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_test_mappings_code ON test_mappings(test_code);
            CREATE TABLE IF NOT EXISTS generated_documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER,
                calculation_id INTEGER,
                doc_type TEXT NOT NULL,
                file_path TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE SET NULL,
                FOREIGN KEY (calculation_id) REFERENCES calculations(id) ON DELETE SET NULL
            );
            CREATE INDEX IF NOT EXISTS idx_generated_documents_order_id
                ON generated_documents(order_id);
            CREATE INDEX IF NOT EXISTS idx_generated_documents_type
                ON generated_documents(doc_type);
            """
        )
    _migrate_orders_columns(db_path)
    _migrate_organizations_columns(db_path)
    _migrate_training_tables(db_path)
    _migrate_test_programs(db_path)
    _migrate_calculation_lines_quantity(db_path)
    apply_price_catalog_fixes(db_path)
    sync_climatic_tests(db_path)
    sync_test_rule_types(db_path)
    sync_default_test_mappings(db_path)
    sync_mappings_from_test_item_names(db_path)


def _migrate_training_tables(db_path: str | Path = DB_PATH_DEFAULT) -> None:
    """Таблицы обучения и RAG (мастер-план 35c, Фаза 1)."""
    with get_connection(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS training_documents (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path       TEXT NOT NULL UNIQUE,
                file_hash       TEXT NOT NULL,
                file_name       TEXT NOT NULL,
                mime_type       TEXT,
                page_count      INTEGER,
                document_type   TEXT,
                document_family TEXT,
                source          TEXT DEFAULT 'operator',
                label_status    TEXT DEFAULT 'unlabeled',
                notes           TEXT,
                registered_at   TEXT NOT NULL,
                updated_at      TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_training_docs_type ON training_documents(document_type);
            CREATE INDEX IF NOT EXISTS idx_training_docs_label ON training_documents(label_status);
            CREATE INDEX IF NOT EXISTS idx_training_docs_hash ON training_documents(file_hash);

            CREATE TABLE IF NOT EXISTS training_labels (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id     INTEGER NOT NULL REFERENCES training_documents(id),
                label_type      TEXT NOT NULL,
                label_version   INTEGER DEFAULT 1,
                payload_json    TEXT NOT NULL,
                labeled_by      TEXT DEFAULT 'operator',
                created_at      TEXT NOT NULL,
                is_active       INTEGER DEFAULT 1
            );
            CREATE INDEX IF NOT EXISTS idx_training_labels_doc
                ON training_labels(document_id, label_type);

            CREATE TABLE IF NOT EXISTS document_families (
                id              TEXT PRIMARY KEY,
                display_name    TEXT NOT NULL,
                document_type   TEXT NOT NULL,
                config_path     TEXT NOT NULL,
                sender_patterns TEXT,
                enabled         INTEGER DEFAULT 1,
                priority        INTEGER DEFAULT 100,
                created_at      TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS ocr_runs (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id     INTEGER REFERENCES training_documents(id),
                source_path     TEXT NOT NULL,
                engine          TEXT NOT NULL,
                dpi             INTEGER,
                preprocess      TEXT,
                page_count      INTEGER,
                mean_confidence REAL,
                duration_ms     INTEGER,
                cache_path      TEXT,
                created_at      TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS training_corrections (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id     INTEGER REFERENCES training_documents(id),
                field_name      TEXT NOT NULL,
                original_value  TEXT,
                corrected_value TEXT,
                mark_context    TEXT,
                exported_from   TEXT,
                created_at      TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS rag_documents (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                title           TEXT NOT NULL,
                doc_kind        TEXT NOT NULL,
                file_path       TEXT,
                text_length     INTEGER,
                chunk_count     INTEGER DEFAULT 0,
                indexed_at      TEXT,
                metadata_json   TEXT
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_rag_documents_path
                ON rag_documents(file_path);

            CREATE TABLE IF NOT EXISTS rag_chunks (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                rag_document_id INTEGER NOT NULL REFERENCES rag_documents(id),
                chunk_index     INTEGER NOT NULL,
                chunk_text      TEXT NOT NULL,
                embedding_blob  BLOB,
                UNIQUE(rag_document_id, chunk_index)
            );

            CREATE TABLE IF NOT EXISTS assistant_sessions (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id        INTEGER,
                document_id     INTEGER,
                role            TEXT,
                message         TEXT NOT NULL,
                response        TEXT,
                model           TEXT,
                feedback        TEXT,
                created_at      TEXT NOT NULL
            );
            """
        )


def _migrate_test_programs(db_path: str | Path = DB_PATH_DEFAULT) -> None:
    """Программы испытаний (S4): заголовок + позиции."""
    with get_connection(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS test_programs (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                name            TEXT NOT NULL,
                test_type       TEXT,
                cable_mark_text TEXT,
                tu_ref          TEXT,
                source_path     TEXT,
                notes           TEXT,
                created_at      TEXT NOT NULL,
                updated_at      TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_test_programs_name ON test_programs(name);

            CREATE TABLE IF NOT EXISTS test_program_items (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                program_id           INTEGER NOT NULL
                    REFERENCES test_programs(id) ON DELETE CASCADE,
                sort_order           INTEGER NOT NULL DEFAULT 0,
                name                 TEXT NOT NULL,
                requirement_doc      TEXT,
                requirement_clause   TEXT,
                method_doc           TEXT,
                method_clause        TEXT,
                price_test_code      TEXT,
                meta_json            TEXT,
                UNIQUE(program_id, sort_order, name)
            );
            CREATE INDEX IF NOT EXISTS idx_test_program_items_prog
                ON test_program_items(program_id);
            """
        )


def _migrate_orders_columns(db_path: str | Path = DB_PATH_DEFAULT) -> None:
    with get_connection(db_path) as conn:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(orders)").fetchall()}
        if "application_path" not in cols:
            conn.execute("ALTER TABLE orders ADD COLUMN application_path TEXT")


def _migrate_organizations_columns(db_path: str | Path = DB_PATH_DEFAULT) -> None:
    from ..extraction.organization_extractor import finalize_organization_address, sanitize_address
    from ..models import OrganizationExtract

    with get_connection(db_path) as conn:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(organizations)").fetchall()}
        if "legal_address" not in cols:
            conn.execute("ALTER TABLE organizations ADD COLUMN legal_address TEXT")
        if "actual_address" not in cols:
            conn.execute("ALTER TABLE organizations ADD COLUMN actual_address TEXT")

        rows = conn.execute(
            "SELECT id, address, legal_address, actual_address FROM organizations"
        ).fetchall()
        for row in rows:
            raw = row["address"]
            legal = row["legal_address"]
            actual = row["actual_address"]
            org_row = conn.execute(
                "SELECT name FROM organizations WHERE id = ?", (row["id"],)
            ).fetchone()
            org_name = org_row["name"] if org_row else ""
            finalized = finalize_organization_address(
                OrganizationExtract(
                    name=org_name or "—",
                    address=raw,
                    legal_address=legal,
                    actual_address=actual,
                ),
                str(raw or ""),
            )
            clean = finalized.address or sanitize_address(raw)
            clean_legal = finalized.legal_address or sanitize_address(legal) if legal else clean
            clean_actual = finalized.actual_address or sanitize_address(actual) if actual else None
            if clean and (not legal or len(str(legal)) > 250):
                legal = clean_legal
            if not actual and clean_actual:
                actual = clean_actual
            if raw != clean or legal != row["legal_address"] or actual != row["actual_address"]:
                conn.execute(
                    """
                    UPDATE organizations SET
                        address = ?,
                        legal_address = COALESCE(?, legal_address),
                        actual_address = COALESCE(?, actual_address)
                    WHERE id = ?
                    """,
                    (clean or raw, legal, actual, row["id"]),
                )


def get_calculation_lines(
    calculation_id: int,
    db_path: str | Path = DB_PATH_DEFAULT,
) -> list[dict[str, Any]]:
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT test_name, base_cost, multiplier, quantity, hours, final_cost, note
            FROM calculation_lines
            WHERE calculation_id = ?
            ORDER BY id
            """,
            (calculation_id,),
        ).fetchall()
        return [dict(row) for row in rows]


def get_cable_mark_document(
    full_mark: str,
    db_path: str | Path = DB_PATH_DEFAULT,
) -> str | None:
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT document FROM cable_marks WHERE full_mark = ? LIMIT 1",
            (full_mark,),
        ).fetchone()
        return row["document"] if row and row["document"] else None


def update_order_application_path(
    order_id: int,
    application_path: str,
    db_path: str | Path = DB_PATH_DEFAULT,
) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            "UPDATE orders SET application_path = ?, updated_at = ? WHERE id = ?",
            (application_path, datetime.now().isoformat(), order_id),
        )


def save_test_application(
    order_id: int,
    output_path: str,
    *,
    template_path: str | None = None,
    test_type: str | None = None,
    customer_name: str | None = None,
    manufacturer_name: str | None = None,
    marks_snapshot: list[dict[str, Any]] | None = None,
    db_path: str | Path = DB_PATH_DEFAULT,
) -> int:
    """Сохраняет сформированную заявку на испытания в БД и обновляет orders.application_path."""
    import json

    now = datetime.now().isoformat()
    snapshot = marks_snapshot or []
    with get_connection(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO test_applications (
                order_id, output_path, template_path, application_number,
                test_type, customer_name, manufacturer_name,
                marks_count, marks_snapshot, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                order_id,
                output_path,
                template_path,
                str(order_id),
                test_type,
                customer_name,
                manufacturer_name,
                len(snapshot),
                json.dumps(snapshot, ensure_ascii=False),
                now,
            ),
        )
        conn.execute(
            "UPDATE orders SET application_path = ?, updated_at = ? WHERE id = ?",
            (output_path, now, order_id),
        )
        app_id = int(cur.lastrowid)
    save_generated_document(
        doc_type="application",
        file_path=output_path,
        order_id=order_id,
        db_path=db_path,
    )
    return app_id


def list_test_applications(
    order_id: int | None = None,
    limit: int = 50,
    db_path: str | Path = DB_PATH_DEFAULT,
) -> list[dict[str, Any]]:
    """История сформированных заявок на испытания."""
    import json

    query = "SELECT * FROM test_applications"
    params: list[Any] = []
    if order_id is not None:
        query += " WHERE order_id = ?"
        params.append(order_id)
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)

    with get_connection(db_path) as conn:
        rows = conn.execute(query, params).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            raw = item.get("marks_snapshot")
            if raw:
                try:
                    item["marks_snapshot"] = json.loads(raw)
                except json.JSONDecodeError:
                    item["marks_snapshot"] = []
            else:
                item["marks_snapshot"] = []
            result.append(item)
        return result


def sync_test_rule_types(db_path: str | Path = DB_PATH_DEFAULT) -> int:
    """Пересчитывает rule_type по названию/категории (per_core, per_group, time_based)."""
    updated = 0
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT id, code, name, category FROM test_items"
        ).fetchall()
        for row in rows:
            rule_type, rule_params = infer_rule_type(
                row["name"], row["category"], row["code"]
            )
            conn.execute(
                """
                UPDATE test_items
                SET rule_type = ?, rule_params = ?
                WHERE id = ?
                """,
                (
                    rule_type,
                    json.dumps(rule_params, ensure_ascii=False),
                    row["id"],
                ),
            )
            updated += 1
    return updated


def _migrate_calculation_lines_quantity(db_path: str | Path = DB_PATH_DEFAULT) -> None:
    with get_connection(db_path) as conn:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(calculation_lines)").fetchall()}
        if "quantity" not in cols:
            conn.execute(
                "ALTER TABLE calculation_lines ADD COLUMN quantity INTEGER NOT NULL DEFAULT 1"
            )


_PRICE_NAME_FIXES: dict[str, str] = {
    "измерение_толщины_облочкишланга": "Измерение толщины оболочки/шланга",
    "измерение_шагакратности_скртки": "Измерение шага/кратности скрутки",
    "водопоглащение": "Водопоглощение",
    "прочность_и_относительное_удлинение_элемента_конструкци": (
        "Прочность и относительное удлинение элемента конструкции"
    ),
    "хромотография_определние_фтора_в_тч": "Хроматография (определение фтора в т.ч.)",
    "установка_соединителейпод_vna_aesa": "Установка соединителей (под VNA, AESA)",
}

_OPTICAL_PER_CORE_CODES = (
    "измерение_затухания_оптического_волокнаодного",
    "определение_целостности_оптического_волокнаодного",
)


def apply_price_catalog_fixes(db_path: str | Path = DB_PATH_DEFAULT) -> None:
    """
    Синхронизация прайса по шаблону Obsidian §39:
    убрать EN-дубли климатики, исправить опечатки, оптика → per_core.
    """
    with get_connection(db_path) as conn:
        for en_code, slug in CLIMATE_ITEM_ALIASES.items():
            conn.execute(
                "UPDATE test_mappings SET test_code = ? WHERE test_code = ?",
                (slug, en_code),
            )
        for code in DEPRECATED_CLIMATE_ITEM_CODES:
            conn.execute("DELETE FROM test_items WHERE code = ?", (code,))

    for code, name in _PRICE_NAME_FIXES.items():
        if get_test_item_by_code(code, db_path):
            update_test_item(code, TestItemUpdate(name=name), db_path)

    for code in _OPTICAL_PER_CORE_CODES:
        if get_test_item_by_code(code, db_path):
            update_test_item(
                code,
                TestItemUpdate(rule_type="per_core", rule_params={}),
                db_path,
            )


def sync_climatic_tests(db_path: str | Path = DB_PATH_DEFAULT) -> None:
    """Обновляет slug-коды климатики: time_based + rule_params (без EN-дублей)."""
    for spec in CLIMATIC_TESTS:
        slug = CLIMATE_SLUG_BY_HOURS_KEY.get(spec["hours_key"])
        if not slug or not get_test_item_by_code(slug, db_path):
            continue
        update_test_item(
            slug,
            TestItemUpdate(
                rule_type="time_based",
                rule_params={
                    "hours_key": spec["hours_key"],
                    "default_hours": spec["default_hours"],
                    "cost_per_hour": spec["cost_per_hour"],
                },
            ),
            db_path,
        )


_DEFAULT_TEST_MAPPINGS: list[tuple[str, str, str | None]] = [
    # Климатика (slug-коды прайса)
    ("воздействию солнечного", "стойкость_к_солнечной_радиации", "Направления в ИЛ"),
    ("солнечного излучения", "стойкость_к_солнечной_радиации", "ГОСТ 20.57.406"),
    ("солнечной радиации", "стойкость_к_солнечной_радиации", "Климатика"),
    ("20.57.406", "стойкость_к_солнечной_радиации", "ГОСТ солнечного излучения"),
    ("метод 211-1", "стойкость_к_солнечной_радиации", "ГОСТ 20.57.406 метод 211-1"),
    ("повышенной влажности", "стойкость_к_повышенной_влажности_воздуха", "Климатика"),
    ("влажности воздуха", "стойкость_к_повышенной_влажности_воздуха", "Климатика"),
    ("пониженной температуры", "стойкость_к_пониженной_температуре", "Климатика"),
    ("пониженной температуре", "стойкость_к_пониженной_температуре", "Климатика"),
    ("повышенной температуры", "стойкость_к_повышенной_температуре", "Климатика"),
    ("повышенной температуре", "стойкость_к_повышенной_температуре", "Климатика"),
    ("изменению температур", "стойкость_к_изменению_температуррезкоеплавное", "Климатика"),
    ("изменению температуры", "стойкость_к_изменению_температуррезкоеплавное", "Климатика"),
    ("циклическ", "стойкость_к_изменению_температуррезкоеплавное", "Климатика"),
    ("отрицательной температур", "стойкость_к_пониженной_температуре", "Морозостойкость"),
    ("простому изгибу", "стойкость_к_простому_изгибу_100_циклов", "Механика"),
    # Электрические (коды из прайса)
    ("электрическое сопротивление тпж", "электрическое_сопротивление_тпж", "Прайс НЧ"),
    ("сопротивление изоляции", "электрическое_сопротивление_изоляции_тпж", "Прайс НЧ"),
    ("сопротивление изоляции тпж", "электрическое_сопротивление_изоляции_тпж", "Прайс НЧ"),
    ("испытание напряжением", "испытание_напряжением", "Прайс НЧ"),
    ("испытание напряжение", "испытание_напряжением", "Прайс НЧ"),
    ("емкости", "измерение_емкостииндуктивности", "ВЧ параметры"),
    ("индуктивности", "измерение_емкостииндуктивности", "ВЧ параметры"),
    ("затухания экранирования", "измерение_затухания_экранирования", "ВЧ"),
    ("затухания излучения", "измерение_затухания_излучения", "ВЧ"),
    ("огнестойкость", "огнестойкость", "Пожарная безопасность"),
    ("ультрафиолет", "стойкость_к_солнечной_радиации", "УФ → солнечная радиация"),
]


def sync_default_test_mappings(db_path: str | Path = DB_PATH_DEFAULT) -> None:
    """Заполняет test_mappings базовыми фразами (идемпотентно)."""
    now = datetime.now().isoformat()
    with get_connection(db_path) as conn:
        for pattern, test_code, note in _DEFAULT_TEST_MAPPINGS:
            conn.execute(
                """
                INSERT INTO test_mappings (requirement_pattern, test_code, note, usage_count, created_at)
                VALUES (?, ?, ?, 0, ?)
                ON CONFLICT(requirement_pattern) DO NOTHING
                """,
                (pattern.lower(), test_code, note, now),
            )


def sync_mappings_from_test_item_names(db_path: str | Path = DB_PATH_DEFAULT) -> int:
    """Добавляет маппинги «название из прайса → code» (для явных перечней в письмах).

    Идемпотентно. Возвращает число **новых** строк.
    """
    now = datetime.now().isoformat()
    added = 0
    with get_connection(db_path) as conn:
        rows = conn.execute("SELECT code, name FROM test_items").fetchall()
        for row in rows:
            code = (row["code"] or "").strip()
            name = (row["name"] or "").strip()
            if not code or not name or len(name) < 4:
                continue
            pattern = name.lower()
            cur = conn.execute(
                """
                INSERT INTO test_mappings (requirement_pattern, test_code, note, usage_count, created_at)
                VALUES (?, ?, ?, 0, ?)
                ON CONFLICT(requirement_pattern) DO NOTHING
                """,
                (pattern, code, "auto: имя из прайса", now),
            )
            if cur.rowcount:
                added += 1
            # короткий паттерн без «определение/измерение/проверка»
            short = re.sub(
                r"^(определение|измерение|проверка|испытание)\s+",
                "",
                pattern,
                flags=re.IGNORECASE,
            ).strip()
            if short and short != pattern and len(short) >= 6:
                cur2 = conn.execute(
                    """
                    INSERT INTO test_mappings (requirement_pattern, test_code, note, usage_count, created_at)
                    VALUES (?, ?, ?, 0, ?)
                    ON CONFLICT(requirement_pattern) DO NOTHING
                    """,
                    (short, code, "auto: короткое имя прайса", now),
                )
                if cur2.rowcount:
                    added += 1
    return added


# --- Программы испытаний (S4) ---


def create_test_program(
    *,
    name: str,
    test_type: str | None = None,
    cable_mark_text: str | None = None,
    tu_ref: str | None = None,
    source_path: str | None = None,
    notes: str | None = None,
    items: list[dict[str, Any]] | None = None,
    db_path: str | Path = DB_PATH_DEFAULT,
) -> int:
    """Создаёт программу и позиции. items: dict с name, requirement_*, method_*, price_test_code."""
    now = datetime.now().isoformat()
    with get_connection(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO test_programs
                (name, test_type, cable_mark_text, tu_ref, source_path, notes, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name.strip(),
                (test_type or "").strip() or None,
                (cable_mark_text or "").strip() or None,
                (tu_ref or "").strip() or None,
                source_path,
                notes,
                now,
                now,
            ),
        )
        program_id = int(cur.lastrowid)
        for i, it in enumerate(items or []):
            conn.execute(
                """
                INSERT INTO test_program_items
                    (program_id, sort_order, name, requirement_doc, requirement_clause,
                     method_doc, method_clause, price_test_code, meta_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    program_id,
                    int(it.get("sort_order", i + 1)),
                    str(it.get("name") or "").strip() or f"Пункт {i + 1}",
                    it.get("requirement_doc"),
                    it.get("requirement_clause"),
                    it.get("method_doc"),
                    it.get("method_clause"),
                    it.get("price_test_code"),
                    json.dumps(it.get("meta") or {}, ensure_ascii=False)
                    if it.get("meta")
                    else None,
                ),
            )
        return program_id


def list_test_programs(
    *,
    search: str | None = None,
    limit: int = 100,
    db_path: str | Path = DB_PATH_DEFAULT,
) -> list[dict[str, Any]]:
    query = """
        SELECT p.*,
               (SELECT COUNT(*) FROM test_program_items i WHERE i.program_id = p.id) AS items_count
        FROM test_programs p
    """
    params: list[Any] = []
    if search:
        query += " WHERE p.name LIKE ? OR IFNULL(p.cable_mark_text,'') LIKE ? OR IFNULL(p.tu_ref,'') LIKE ?"
        params.extend([f"%{search}%"] * 3)
    query += " ORDER BY p.updated_at DESC LIMIT ?"
    params.append(limit)
    with get_connection(db_path) as conn:
        return [dict(r) for r in conn.execute(query, params).fetchall()]


def get_test_program(
    program_id: int,
    db_path: str | Path = DB_PATH_DEFAULT,
) -> dict[str, Any] | None:
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM test_programs WHERE id = ?", (program_id,)
        ).fetchone()
        if not row:
            return None
        items = conn.execute(
            """
            SELECT * FROM test_program_items
            WHERE program_id = ?
            ORDER BY sort_order, id
            """,
            (program_id,),
        ).fetchall()
        data = dict(row)
        data["items"] = [dict(i) for i in items]
        return data


def delete_test_program(
    program_id: int,
    db_path: str | Path = DB_PATH_DEFAULT,
) -> bool:
    with get_connection(db_path) as conn:
        conn.execute("DELETE FROM test_program_items WHERE program_id = ?", (program_id,))
        cur = conn.execute("DELETE FROM test_programs WHERE id = ?", (program_id,))
        return cur.rowcount > 0


def update_program_item_price_code(
    item_id: int,
    price_test_code: str | None,
    db_path: str | Path = DB_PATH_DEFAULT,
) -> bool:
    with get_connection(db_path) as conn:
        cur = conn.execute(
            "UPDATE test_program_items SET price_test_code = ? WHERE id = ?",
            ((price_test_code or "").strip() or None, item_id),
        )
        return cur.rowcount > 0


def match_program_items_to_price(
    program_id: int,
    db_path: str | Path = DB_PATH_DEFAULT,
) -> dict[str, int]:
    """Проставляет price_test_code по test_mappings / имени прайса.

    Returns: {matched, unmatched}
    """
    from ..mapping.requirement_mapper import map_requirements_to_tests

    prog = get_test_program(program_id, db_path=db_path)
    if not prog:
        return {"matched": 0, "unmatched": 0}
    matched = 0
    unmatched = 0
    price_names = {
        (r["name"] or "").strip().lower(): r["code"]
        for r in list_test_items(limit=500, db_path=db_path)
    }
    for item in prog["items"]:
        if item.get("price_test_code"):
            matched += 1
            continue
        name = (item.get("name") or "").strip()
        code: str | None = None
        # exact / substring in price names
        nl = name.lower()
        if nl in price_names:
            code = price_names[nl]
        else:
            for pname, pcode in price_names.items():
                if nl and (nl in pname or pname in nl) and len(nl) >= 8:
                    code = pcode
                    break
        if not code:
            suggestions = map_requirements_to_tests(name, db_path=db_path)
            if suggestions:
                code = suggestions[0].code
        if code:
            update_program_item_price_code(int(item["id"]), code, db_path=db_path)
            matched += 1
        else:
            unmatched += 1
    return {"matched": matched, "unmatched": unmatched}


def list_test_mappings(
    *,
    test_code: str | None = None,
    limit: int = 200,
    db_path: str | Path = DB_PATH_DEFAULT,
) -> list[dict[str, Any]]:
    query = "SELECT * FROM test_mappings"
    params: list[Any] = []
    if test_code:
        query += " WHERE test_code = ?"
        params.append(test_code)
    query += " ORDER BY usage_count DESC, requirement_pattern LIMIT ?"
    params.append(limit)
    with get_connection(db_path) as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]


def add_test_mapping(
    requirement_pattern: str,
    test_code: str,
    *,
    note: str | None = None,
    db_path: str | Path = DB_PATH_DEFAULT,
) -> int:
    """Добавляет или обновляет маппинг «фраза → код испытания»."""
    pattern = requirement_pattern.strip().lower()
    if not pattern:
        raise ValueError("Пустой шаблон требования")
    code = test_code.strip()
    if not code:
        raise ValueError("Пустой код испытания")
    now = datetime.now().isoformat()
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO test_mappings (requirement_pattern, test_code, note, usage_count, created_at)
            VALUES (?, ?, ?, 0, ?)
            ON CONFLICT(requirement_pattern) DO UPDATE SET
                test_code = excluded.test_code,
                note = COALESCE(excluded.note, test_mappings.note)
            """,
            (pattern, code, note, now),
        )
        row = conn.execute(
            "SELECT id FROM test_mappings WHERE requirement_pattern = ?",
            (pattern,),
        ).fetchone()
        return int(row["id"]) if row else 0


def get_test_mapping(
    mapping_id: int,
    db_path: str | Path = DB_PATH_DEFAULT,
) -> dict[str, Any] | None:
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM test_mappings WHERE id = ?",
            (mapping_id,),
        ).fetchone()
        return dict(row) if row else None


def update_test_mapping(
    mapping_id: int,
    *,
    requirement_pattern: str | None = None,
    test_code: str | None = None,
    note: str | None = None,
    db_path: str | Path = DB_PATH_DEFAULT,
) -> None:
    """Обновляет запись маппинга по id."""
    current = get_test_mapping(mapping_id, db_path)
    if not current:
        raise ValueError(f"Маппинг id={mapping_id} не найден")
    pattern = (requirement_pattern or current["requirement_pattern"]).strip().lower()
    code = (test_code or current["test_code"]).strip()
    if not pattern:
        raise ValueError("Пустой шаблон требования")
    if not code:
        raise ValueError("Пустой код испытания")
    new_note = note if note is not None else current.get("note")
    with get_connection(db_path) as conn:
        conn.execute(
            """
            UPDATE test_mappings
            SET requirement_pattern = ?, test_code = ?, note = ?
            WHERE id = ?
            """,
            (pattern, code, new_note, mapping_id),
        )


def delete_test_mapping(
    mapping_id: int,
    db_path: str | Path = DB_PATH_DEFAULT,
) -> bool:
    """Удаляет маппинг. Возвращает False, если запись не найдена."""
    with get_connection(db_path) as conn:
        cur = conn.execute("DELETE FROM test_mappings WHERE id = ?", (mapping_id,))
        return cur.rowcount > 0


def save_generated_document(
    *,
    doc_type: str,
    file_path: str,
    order_id: int | None = None,
    calculation_id: int | None = None,
    db_path: str | Path = DB_PATH_DEFAULT,
) -> int:
    """Журнал сгенерированных файлов (КП, заявка на испытания)."""
    if doc_type not in ("kp", "application"):
        raise ValueError(f"Неизвестный тип документа: {doc_type}")
    now = datetime.now().isoformat()
    resolved = str(Path(file_path).resolve())
    with get_connection(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO generated_documents (
                order_id, calculation_id, doc_type, file_path, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (order_id, calculation_id, doc_type, resolved, now),
        )
        return int(cur.lastrowid or 0)


def list_generated_documents(
    *,
    order_id: int | None = None,
    doc_type: str | None = None,
    limit: int = 50,
    db_path: str | Path = DB_PATH_DEFAULT,
) -> list[dict[str, Any]]:
    query = "SELECT * FROM generated_documents"
    params: list[Any] = []
    conditions: list[str] = []
    if order_id is not None:
        conditions.append("order_id = ?")
        params.append(order_id)
    if doc_type:
        conditions.append("doc_type = ?")
        params.append(doc_type)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    with get_connection(db_path) as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]


def record_mapping_usage(
    mapping_id: int,
    db_path: str | Path = DB_PATH_DEFAULT,
) -> None:
    """Увеличивает счётчик срабатывания маппинга (для обучения на подтверждениях оператора)."""
    with get_connection(db_path) as conn:
        conn.execute(
            "UPDATE test_mappings SET usage_count = usage_count + 1 WHERE id = ?",
            (mapping_id,),
        )


CLIMATIC_SETTINGS_KEY = "climatic_test_hours"
DOCUMENT_PACK_SETTINGS_KEY = "document_pack_settings"
ASSISTANT_LLM_SETTINGS_KEY = "assistant_llm_settings"


def _seed_default_settings(db_path: str | Path) -> None:
    if get_climatic_settings(db_path) is not None:
        return
    save_climatic_settings(ClimaticTestSettings(), db_path)


def get_climatic_settings(db_path: str | Path = DB_PATH_DEFAULT) -> ClimaticTestSettings | None:
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT value FROM app_settings WHERE key = ?", (CLIMATIC_SETTINGS_KEY,)
        ).fetchone()
        if not row:
            return None
        return ClimaticTestSettings(**json.loads(row["value"]))


def save_climatic_settings(
    settings: ClimaticTestSettings,
    db_path: str | Path = DB_PATH_DEFAULT,
) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO app_settings (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (CLIMATIC_SETTINGS_KEY, settings.model_dump_json()),
        )


def get_document_pack_settings(
    db_path: str | Path = DB_PATH_DEFAULT,
) -> DocumentPackSettings:
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT value FROM app_settings WHERE key = ?", (DOCUMENT_PACK_SETTINGS_KEY,)
        ).fetchone()
        if not row:
            return DocumentPackSettings()
        return DocumentPackSettings(**json.loads(row["value"]))


def save_document_pack_settings(
    settings: DocumentPackSettings,
    db_path: str | Path = DB_PATH_DEFAULT,
) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO app_settings (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (DOCUMENT_PACK_SETTINGS_KEY, settings.model_dump_json()),
        )


def get_assistant_llm_settings(
    db_path: str | Path = DB_PATH_DEFAULT,
) -> AssistantLlmSettings:
    from ..assistant.llm_provider import default_llm_settings, resolve_llm_settings

    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT value FROM app_settings WHERE key = ?", (ASSISTANT_LLM_SETTINGS_KEY,)
        ).fetchone()
        if not row:
            return resolve_llm_settings(default_llm_settings())
        return resolve_llm_settings(AssistantLlmSettings(**json.loads(row["value"])))


def save_assistant_llm_settings(
    settings: AssistantLlmSettings,
    db_path: str | Path = DB_PATH_DEFAULT,
) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO app_settings (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (ASSISTANT_LLM_SETTINGS_KEY, settings.model_dump_json()),
        )


def prepare_battle_db(
    db_path: str | Path = DB_PATH_DEFAULT,
    *,
    backup: bool = True,
) -> dict[str, Any]:
    """
    Готовит БД к боевому запуску с «чистыми» марками и организациями.

    **Сохраняет:**
    - ``test_items`` — прайс и правила расчёта (fixed/per_core/…)
    - ``test_mappings`` — фразы требований → коды испытаний
    - ``app_settings`` — климатика, LLM, пути пакетов, host_id
    - training/RAG-таблицы (если есть)

    **Очищает:**
    - ``cable_marks``, ``organizations``
    - связанные операционные данные: заказы, расчёты, извлечения,
      заявки, generated_documents, assistant_sessions
      (иначе остаются «осиротевшие» ссылки на удалённые org/mark)

    Returns:
        dict с путём backup (если был), счётчиками удалённых строк
        и сохранёнными test_items / test_mappings.
    """
    path = Path(db_path)
    if not path.exists():
        raise FileNotFoundError(f"БД не найдена: {path}")

    backup_path: Path | None = None
    if backup:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = path.with_name(f"{path.stem}.pre_battle_{stamp}{path.suffix}")
        import shutil

        shutil.copy2(path, backup_path)

    # Порядок: дочерние таблицы → родители (на случай включённых FK)
    clear_tables = (
        "calculation_lines",
        "order_marks",
        "test_applications",
        "generated_documents",
        "orders",
        "calculations",
        "document_extractions",
        "assistant_sessions",
        "cable_marks",
        "organizations",
    )

    deleted: dict[str, int] = {}
    with get_connection(path) as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        for table in clear_tables:
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone()
            if not exists:
                continue
            count = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
            conn.execute(f"DELETE FROM {table}")
            deleted[table] = int(count)
        conn.execute("PRAGMA foreign_keys = ON")
        kept_items = conn.execute("SELECT COUNT(*) AS n FROM test_items").fetchone()["n"]
        kept_maps = conn.execute("SELECT COUNT(*) AS n FROM test_mappings").fetchone()["n"]

    return {
        "db_path": str(path.resolve()),
        "backup_path": str(backup_path.resolve()) if backup_path else None,
        "deleted": deleted,
        "kept_test_items": int(kept_items),
        "kept_test_mappings": int(kept_maps),
    }


def push_recent_pack_path(
    pack_dir: str | Path,
    db_path: str | Path = DB_PATH_DEFAULT,
    *,
    limit: int = 5,
) -> None:
    """Добавляет путь пакета в историю (последние limit уникальных)."""
    path = str(Path(pack_dir).resolve())
    settings = get_document_pack_settings(db_path)
    recent = [p for p in settings.recent_paths if p != path]
    recent.insert(0, path)
    settings.recent_paths = recent[:limit]
    save_document_pack_settings(settings, db_path)


def build_default_hours_map(db_path: str | Path = DB_PATH_DEFAULT) -> dict[str, float]:
    """Собирает часы выдержки из настроек + default_hours из time_based испытаний."""
    hours: dict[str, float] = {}
    settings = get_climatic_settings(db_path)
    if settings:
        for key, _ in climatic_settings_fields():
            hours[key] = float(getattr(settings, key))
    for item in get_all_test_items(db_path):
        if item.rule_type != "time_based":
            continue
        key = item.rule_params.get("hours_key", item.code)
        if key not in hours and "default_hours" in item.rule_params:
            hours[key] = float(item.rule_params["default_hours"])
    return hours


def upsert_cable_mark(
    record: CableMarkRecord,
    db_path: str | Path = DB_PATH_DEFAULT,
) -> int:
    """Добавляет марку без полных дублей (по full_mark)."""
    with get_connection(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO cable_marks (
                full_mark, brand, fire_class, cores_count,
                structural_element_type, structural_elements_count,
                characteristic_size, size_unit, document, source, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(full_mark) DO UPDATE SET
                brand = excluded.brand,
                fire_class = excluded.fire_class,
                cores_count = excluded.cores_count,
                structural_element_type = excluded.structural_element_type,
                structural_elements_count = excluded.structural_elements_count,
                characteristic_size = excluded.characteristic_size,
                size_unit = excluded.size_unit,
                document = COALESCE(excluded.document, cable_marks.document),
                source = COALESCE(excluded.source, cable_marks.source)
            """,
            (
                record.full_mark,
                record.brand,
                record.fire_class,
                record.cores_count,
                record.structural_element_type,
                record.structural_elements_count,
                record.characteristic_size,
                record.size_unit,
                record.document,
                record.source,
                (record.created_at or datetime.now()).isoformat(),
            ),
        )
        if cursor.lastrowid:
            return cursor.lastrowid
        row = conn.execute(
            "SELECT id FROM cable_marks WHERE full_mark = ?", (record.full_mark,)
        ).fetchone()
        return int(row["id"]) if row else 0


def save_cable_marks_from_matches(
    matches: list,
    *,
    source: str | None = None,
    db_path: str | Path = DB_PATH_DEFAULT,
) -> dict[str, int]:
    """Сохраняет найденные в PDF марки в накопительную таблицу."""
    stats = {"saved": 0, "errors": 0}
    for match in matches:
        try:
            record = parse_cable_mark_record(
                match.mark,
                document=getattr(match, "document", None),
                context=getattr(match, "context", None),
            )
            record.source = source
            upsert_cable_mark(record, db_path)
            stats["saved"] += 1
        except Exception:
            stats["errors"] += 1
    return stats


def save_cable_marks_from_validations(
    validations: list,
    *,
    source: str | None = None,
    only_accepted: bool = True,
    db_path: str | Path = DB_PATH_DEFAULT,
) -> dict[str, int]:
    """Сохраняет подтверждённые марки с полями, заданными оператором."""
    from ..models import MarkValidation

    stats = {"saved": 0, "errors": 0}
    for item in validations:
        if only_accepted and isinstance(item, MarkValidation) and not item.accepted:
            continue
        try:
            if isinstance(item, MarkValidation):
                record = item.to_cable_mark_record(source=source)
            else:
                record = parse_cable_mark_record(
                    item.mark,
                    document=getattr(item, "document", None),
                    context=getattr(item, "context", None),
                )
                record.source = source
            upsert_cable_mark(record, db_path)
            stats["saved"] += 1
        except Exception:
            stats["errors"] += 1
    return stats


def upsert_organization(
    extract: OrganizationExtract,
    *,
    source: str | None = None,
    db_path: str | Path = DB_PATH_DEFAULT,
) -> int:
    """Сохраняет организацию без дублей (по ИНН или нормализованному названию)."""
    from ..extraction.organization_extractor import finalize_organization_address

    extract = finalize_organization_address(extract)
    now = datetime.now().isoformat()
    name_normalized = normalize_org_name(extract.name)
    inn_key = extract.inn or ""

    with get_connection(db_path) as conn:
        row = None
        if extract.inn:
            row = conn.execute(
                "SELECT * FROM organizations WHERE inn = ?",
                (extract.inn,),
            ).fetchone()
        if row is None:
            row = conn.execute(
                "SELECT * FROM organizations WHERE name_normalized = ? AND COALESCE(inn, '') = ?",
                (name_normalized, inn_key),
            ).fetchone()

        legal = extract.legal_address or extract.address
        actual = extract.actual_address or legal

        if row:
            org_id = int(row["id"])
            conn.execute(
                """
                UPDATE organizations SET
                    name = ?,
                    address = COALESCE(?, address),
                    legal_address = COALESCE(?, legal_address),
                    actual_address = COALESCE(?, actual_address),
                    postal_code = COALESCE(?, postal_code),
                    phone = COALESCE(?, phone),
                    email = COALESCE(?, email),
                    inn = COALESCE(?, inn),
                    kpp = COALESCE(?, kpp),
                    is_accredited = MAX(is_accredited, ?),
                    fsa_registry_number = COALESCE(?, fsa_registry_number),
                    org_type = CASE WHEN ? = 'unknown' THEN org_type ELSE ? END,
                    source = COALESCE(?, source),
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    extract.name,
                    extract.address,
                    legal,
                    actual,
                    extract.postal_code,
                    extract.phone,
                    extract.email,
                    extract.inn,
                    extract.kpp,
                    int(extract.is_accredited),
                    extract.fsa_registry_number,
                    extract.org_type,
                    extract.org_type,
                    source,
                    now,
                    org_id,
                ),
            )
            return org_id

        cursor = conn.execute(
            """
            INSERT INTO organizations (
                name, name_normalized, address, legal_address, actual_address,
                postal_code, phone, email,
                inn, kpp, is_accredited, fsa_registry_number, org_type,
                source, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                extract.name,
                name_normalized,
                extract.address,
                legal,
                actual,
                extract.postal_code,
                extract.phone,
                extract.email,
                extract.inn,
                extract.kpp,
                int(extract.is_accredited),
                extract.fsa_registry_number,
                extract.org_type,
                source,
                now,
                now,
            ),
        )
        return int(cursor.lastrowid or 0)


def save_organizations_from_extraction(
    organizations: list[OrganizationExtract],
    *,
    source: str | None = None,
    db_path: str | Path = DB_PATH_DEFAULT,
) -> dict[str, int | None]:
    """Сохраняет организации из заявки; возвращает id заказчика и производителя."""
    customer_id: int | None = None
    manufacturer_id: int | None = None

    for org in organizations:
        org_id = upsert_organization(org, source=source, db_path=db_path)
        if org.role == "customer" and customer_id is None:
            customer_id = org_id
        if org.role == "manufacturer" and manufacturer_id is None:
            manufacturer_id = org_id

    if customer_id is None and organizations:
        customer_id = upsert_organization(organizations[0], source=source, db_path=db_path)
    if manufacturer_id is None and len(organizations) > 1:
        manufacturer_id = upsert_organization(organizations[1], source=source, db_path=db_path)
    elif manufacturer_id is None and customer_id is not None:
        manufacturer_id = customer_id

    return {"customer_org_id": customer_id, "manufacturer_org_id": manufacturer_id}


def save_document_extraction(
    *,
    source_path: str,
    source_type: str,
    text: str,
    marks_count: int,
    customer_org_id: int | None = None,
    manufacturer_org_id: int | None = None,
    subject: str | None = None,
    db_path: str | Path = DB_PATH_DEFAULT,
) -> int:
    with get_connection(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO document_extractions (
                source_path, source_type, customer_org_id, manufacturer_org_id,
                subject, raw_text_length, marks_count, extracted_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source_path,
                source_type,
                customer_org_id,
                manufacturer_org_id,
                subject,
                len(text),
                marks_count,
                datetime.now().isoformat(),
            ),
        )
        return int(cursor.lastrowid or 0)


def list_organizations(
    search: str | None = None,
    org_type: str | None = None,
    limit: int = 100,
    db_path: str | Path = DB_PATH_DEFAULT,
) -> list[dict[str, Any]]:
    query = "SELECT * FROM organizations"
    params: list[Any] = []
    conditions: list[str] = []
    if search:
        conditions.append("(name LIKE ? OR inn LIKE ? OR address LIKE ?)")
        params.extend([f"%{search}%", f"%{search}%", f"%{search}%"])
    if org_type:
        conditions.append("org_type = ?")
        params.append(org_type)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY updated_at DESC LIMIT ?"
    params.append(limit)

    with get_connection(db_path) as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]


def get_organization_by_id(
    org_id: int,
    db_path: str | Path = DB_PATH_DEFAULT,
) -> dict[str, Any] | None:
    with get_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM organizations WHERE id = ?", (org_id,)).fetchone()
        return dict(row) if row else None


def update_organization(
    org_id: int,
    *,
    name: str,
    address: str | None = None,
    postal_code: str | None = None,
    phone: str | None = None,
    email: str | None = None,
    inn: str | None = None,
    kpp: str | None = None,
    is_accredited: bool = False,
    fsa_registry_number: str | None = None,
    org_type: str = "unknown",
    db_path: str | Path = DB_PATH_DEFAULT,
) -> bool:
    """Обновляет организацию по id (ручное редактирование в GUI)."""
    now = datetime.now().isoformat()
    name_normalized = normalize_org_name(name)
    with get_connection(db_path) as conn:
        cursor = conn.execute(
            """
            UPDATE organizations SET
                name = ?,
                name_normalized = ?,
                address = ?,
                postal_code = ?,
                phone = ?,
                email = ?,
                inn = ?,
                kpp = ?,
                is_accredited = ?,
                fsa_registry_number = ?,
                org_type = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                name.strip(),
                name_normalized,
                address,
                postal_code,
                phone,
                email,
                inn,
                kpp,
                int(is_accredited),
                fsa_registry_number,
                org_type,
                now,
                org_id,
            ),
        )
        return cursor.rowcount > 0


def get_last_document_extraction(
    db_path: str | Path = DB_PATH_DEFAULT,
) -> dict[str, Any] | None:
    """Последняя обработанная заявка (для панели сводки в GUI)."""
    with get_connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT d.*,
                   c.name AS customer_name,
                   m.name AS manufacturer_name
            FROM document_extractions d
            LEFT JOIN organizations c ON c.id = d.customer_org_id
            LEFT JOIN organizations m ON m.id = d.manufacturer_org_id
            ORDER BY d.extracted_at DESC
            LIMIT 1
            """
        ).fetchone()
        return dict(row) if row else None


def find_organization_id_by_name(
    name: str,
    db_path: str | Path = DB_PATH_DEFAULT,
) -> int | None:
    if not name or not name.strip():
        return None
    normalized = normalize_org_name(name)
    with get_connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT id FROM organizations
            WHERE name_normalized = ? OR name = ?
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (normalized, name.strip()),
        ).fetchone()
        return int(row["id"]) if row else None


def _find_cable_mark_id(mark: str, db_path: str | Path) -> int | None:
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT id FROM cable_marks WHERE full_mark = ? LIMIT 1",
            (mark,),
        ).fetchone()
        return int(row["id"]) if row else None


def create_order_from_kp(
    *,
    customer_name: str,
    manufacturer_name: str | None = None,
    customer_org_id: int | None = None,
    manufacturer_org_id: int | None = None,
    subject: str,
    note: str | None = None,
    calculation_ids: list[int],
    kp_output_path: str,
    document_extraction_id: int | None = None,
    db_path: str | Path = DB_PATH_DEFAULT,
) -> int:
    """
    Создаёт заказ после формирования КП.
    Заказчик — на уровне заказа; каждая марка связана с производителем.
    """
    if not calculation_ids:
        raise ValueError("Нет расчётов для заказа")

    if customer_org_id is None and customer_name:
        customer_org_id = find_organization_id_by_name(customer_name, db_path)
    if manufacturer_org_id is None and manufacturer_name:
        manufacturer_org_id = find_organization_id_by_name(manufacturer_name, db_path)
    if manufacturer_org_id is None and document_extraction_id:
        with get_connection(db_path) as conn:
            row = conn.execute(
                "SELECT manufacturer_org_id FROM document_extractions WHERE id = ?",
                (document_extraction_id,),
            ).fetchone()
            if row and row["manufacturer_org_id"]:
                manufacturer_org_id = int(row["manufacturer_org_id"])

    rows = get_calculations_for_kp(calculation_ids, db_path=db_path)
    if not rows:
        raise ValueError("Расчёты не найдены")

    total_without = round(sum(float(r["total_cost_without_vat"]) for r in rows), 2)
    total_with = round(sum(float(r["total_cost_with_vat"]) for r in rows), 2)
    vat_rate = float(rows[0].get("vat_rate") or 0.22)
    now = datetime.now().isoformat()

    with get_connection(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO orders (
                customer_org_id, manufacturer_org_id, subject, note, status,
                total_without_vat, total_with_vat, vat_rate,
                document_extraction_id, kp_output_path, created_at, updated_at
            ) VALUES (?, ?, ?, ?, 'kp_generated', ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                customer_org_id,
                manufacturer_org_id,
                subject,
                note,
                total_without,
                total_with,
                vat_rate,
                document_extraction_id,
                kp_output_path,
                now,
                now,
            ),
        )
        order_id = int(cursor.lastrowid or 0)

        for row in rows:
            calc_id = int(row["id"])
            mark = row["mark"]
            cable_mark_id = _find_cable_mark_id(mark, db_path)
            conn.execute(
                """
                INSERT INTO order_marks (
                    order_id, calculation_id, cable_mark_id, manufacturer_org_id,
                    mark, total_without_vat, total_with_vat
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    order_id,
                    calc_id,
                    cable_mark_id,
                    manufacturer_org_id,
                    mark,
                    float(row["total_cost_without_vat"]),
                    float(row["total_cost_with_vat"]),
                ),
            )

    save_generated_document(
        doc_type="kp",
        file_path=kp_output_path,
        order_id=order_id,
        db_path=db_path,
    )
    return order_id


def list_orders(
    limit: int = 100,
    db_path: str | Path = DB_PATH_DEFAULT,
) -> list[dict[str, Any]]:
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT o.*,
                   c.name AS customer_name,
                   m.name AS manufacturer_name,
                   (SELECT COUNT(*) FROM order_marks om WHERE om.order_id = o.id) AS marks_count
            FROM orders o
            LEFT JOIN organizations c ON c.id = o.customer_org_id
            LEFT JOIN organizations m ON m.id = o.manufacturer_org_id
            ORDER BY o.created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]


def get_order_details(
    order_id: int,
    db_path: str | Path = DB_PATH_DEFAULT,
) -> dict[str, Any] | None:
    with get_connection(db_path) as conn:
        order_row = conn.execute(
            """
            SELECT o.*,
                   c.name AS customer_name,
                   c.inn AS customer_inn,
                   c.address AS customer_address,
                   c.legal_address AS customer_legal_address,
                   c.actual_address AS customer_actual_address,
                   c.phone AS customer_phone,
                   c.email AS customer_email,
                   m.name AS manufacturer_name,
                   m.inn AS manufacturer_inn,
                   m.address AS manufacturer_address,
                   m.legal_address AS manufacturer_legal_address,
                   m.actual_address AS manufacturer_actual_address,
                   m.phone AS manufacturer_phone,
                   m.email AS manufacturer_email,
                   d.source_path AS source_document
            FROM orders o
            LEFT JOIN organizations c ON c.id = o.customer_org_id
            LEFT JOIN organizations m ON m.id = o.manufacturer_org_id
            LEFT JOIN document_extractions d ON d.id = o.document_extraction_id
            WHERE o.id = ?
            """,
            (order_id,),
        ).fetchone()
        if not order_row:
            return None

        marks = conn.execute(
            """
            SELECT om.*,
                   mo.name AS manufacturer_name
            FROM order_marks om
            LEFT JOIN organizations mo ON mo.id = om.manufacturer_org_id
            WHERE om.order_id = ?
            ORDER BY om.id
            """,
            (order_id,),
        ).fetchall()

        result = dict(order_row)
        result["marks"] = [dict(m) for m in marks]
        return result


def list_cable_marks(
    search: str | None = None,
    limit: int = 200,
    db_path: str | Path = DB_PATH_DEFAULT,
) -> list[dict[str, Any]]:
    query = "SELECT * FROM cable_marks"
    params: list[Any] = []
    if search:
        query += " WHERE full_mark LIKE ? OR brand LIKE ?"
        params.extend([f"%{search}%", f"%{search}%"])
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)

    with get_connection(db_path) as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]


def delete_cable_mark(
    mark_id: int,
    db_path: str | Path = DB_PATH_DEFAULT,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Удаляет марку из справочника.

    Если force=False и марка в order_marks — отказ (blocked).
    Если force=True — обнуляет cable_mark_id в order_marks, затем удаляет.
    """
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT id, full_mark FROM cable_marks WHERE id = ?", (mark_id,)
        ).fetchone()
        if not row:
            return {"ok": False, "reason": "not_found"}
        refs = conn.execute(
            "SELECT COUNT(*) AS n FROM order_marks WHERE cable_mark_id = ?",
            (mark_id,),
        ).fetchone()["n"]
        if refs and not force:
            return {
                "ok": False,
                "reason": "in_use",
                "refs": int(refs),
                "full_mark": row["full_mark"],
            }
        if refs and force:
            conn.execute(
                "UPDATE order_marks SET cable_mark_id = NULL WHERE cable_mark_id = ?",
                (mark_id,),
            )
        conn.execute("DELETE FROM cable_marks WHERE id = ?", (mark_id,))
        return {"ok": True, "full_mark": row["full_mark"], "unlinked": int(refs)}


def delete_calculation(
    calc_id: int,
    db_path: str | Path = DB_PATH_DEFAULT,
) -> dict[str, Any]:
    """Удаляет расчёт и его строки. order_marks.calculation_id → NULL."""
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT id, mark FROM calculations WHERE id = ?", (calc_id,)
        ).fetchone()
        if not row:
            return {"ok": False, "reason": "not_found"}
        conn.execute(
            "UPDATE order_marks SET calculation_id = NULL WHERE calculation_id = ?",
            (calc_id,),
        )
        conn.execute("DELETE FROM calculation_lines WHERE calculation_id = ?", (calc_id,))
        conn.execute(
            "UPDATE generated_documents SET calculation_id = NULL WHERE calculation_id = ?",
            (calc_id,),
        )
        conn.execute("DELETE FROM calculations WHERE id = ?", (calc_id,))
        return {"ok": True, "mark": row["mark"]}


def delete_generated_document(
    doc_id: int,
    db_path: str | Path = DB_PATH_DEFAULT,
    *,
    delete_file: bool = False,
) -> dict[str, Any]:
    """Удаляет запись КП/документа из generated_documents (опц. файл с диска)."""
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT id, doc_type, file_path FROM generated_documents WHERE id = ?",
            (doc_id,),
        ).fetchone()
        if not row:
            return {"ok": False, "reason": "not_found"}
        path = row["file_path"]
        conn.execute("DELETE FROM generated_documents WHERE id = ?", (doc_id,))
    removed_file = False
    if delete_file and path:
        try:
            p = Path(path)
            if p.is_file():
                p.unlink()
                removed_file = True
        except OSError:
            pass
    return {
        "ok": True,
        "doc_type": row["doc_type"],
        "file_path": path,
        "file_removed": removed_file,
    }


def delete_order(
    order_id: int,
    db_path: str | Path = DB_PATH_DEFAULT,
    *,
    cascade: bool = False,
) -> dict[str, Any]:
    """Удаляет заказ.

    cascade=False: отказ, если есть order_marks / applications / generated.
    cascade=True: удаляет дочерние записи (не трогает calculations целиком —
    только связи order_marks); файлы на диске не удаляет.
    """
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT id, customer_name FROM orders WHERE id = ?", (order_id,)
        ).fetchone()
        if not row:
            return {"ok": False, "reason": "not_found"}
        marks_n = conn.execute(
            "SELECT COUNT(*) AS n FROM order_marks WHERE order_id = ?", (order_id,)
        ).fetchone()["n"]
        apps_n = conn.execute(
            "SELECT COUNT(*) AS n FROM test_applications WHERE order_id = ?",
            (order_id,),
        ).fetchone()["n"]
        docs_n = conn.execute(
            "SELECT COUNT(*) AS n FROM generated_documents WHERE order_id = ?",
            (order_id,),
        ).fetchone()["n"]
        children = int(marks_n) + int(apps_n) + int(docs_n)
        if children and not cascade:
            return {
                "ok": False,
                "reason": "has_children",
                "order_marks": int(marks_n),
                "applications": int(apps_n),
                "generated": int(docs_n),
                "customer_name": row["customer_name"],
            }
        conn.execute("DELETE FROM order_marks WHERE order_id = ?", (order_id,))
        conn.execute("DELETE FROM test_applications WHERE order_id = ?", (order_id,))
        conn.execute(
            "UPDATE generated_documents SET order_id = NULL WHERE order_id = ?",
            (order_id,),
        )
        conn.execute("DELETE FROM orders WHERE id = ?", (order_id,))
        return {
            "ok": True,
            "customer_name": row["customer_name"],
            "removed_marks": int(marks_n),
            "removed_applications": int(apps_n),
            "unlinked_generated": int(docs_n),
        }


def delete_organization(
    org_id: int,
    db_path: str | Path = DB_PATH_DEFAULT,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Удаляет организацию. force: обнуляет FK в orders/order_marks/extractions."""
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT id, name FROM organizations WHERE id = ?", (org_id,)
        ).fetchone()
        if not row:
            return {"ok": False, "reason": "not_found"}
        o_refs = conn.execute(
            """
            SELECT COUNT(*) AS n FROM orders
            WHERE customer_org_id = ? OR manufacturer_org_id = ?
            """,
            (org_id, org_id),
        ).fetchone()["n"]
        m_refs = conn.execute(
            "SELECT COUNT(*) AS n FROM order_marks WHERE manufacturer_org_id = ?",
            (org_id,),
        ).fetchone()["n"]
        e_refs = conn.execute(
            """
            SELECT COUNT(*) AS n FROM document_extractions
            WHERE customer_org_id = ? OR manufacturer_org_id = ?
            """,
            (org_id, org_id),
        ).fetchone()["n"]
        total = int(o_refs) + int(m_refs) + int(e_refs)
        if total and not force:
            return {
                "ok": False,
                "reason": "in_use",
                "refs": total,
                "name": row["name"],
            }
        if force:
            conn.execute(
                "UPDATE orders SET customer_org_id = NULL WHERE customer_org_id = ?",
                (org_id,),
            )
            conn.execute(
                "UPDATE orders SET manufacturer_org_id = NULL WHERE manufacturer_org_id = ?",
                (org_id,),
            )
            conn.execute(
                "UPDATE order_marks SET manufacturer_org_id = NULL WHERE manufacturer_org_id = ?",
                (org_id,),
            )
            conn.execute(
                "UPDATE document_extractions SET customer_org_id = NULL WHERE customer_org_id = ?",
                (org_id,),
            )
            conn.execute(
                "UPDATE document_extractions SET manufacturer_org_id = NULL WHERE manufacturer_org_id = ?",
                (org_id,),
            )
        conn.execute("DELETE FROM organizations WHERE id = ?", (org_id,))
        return {"ok": True, "name": row["name"], "unlinked": total}


def _seed_demo_tests(db_path: str | Path) -> None:
    """Добавляет демо-тесты с реалистичными параметрами."""
    demo = [
        TestItem(
            code="resistance_core",
            name="Электрическое сопротивление ТПЖ",
            base_cost=400,
            category="Электрические параметры НЧ",
            rule_type="per_core",
        ),
        TestItem(
            code="insulation_resistance",
            name="Электрическое сопротивление изоляции ТПЖ",
            base_cost=600,
            category="Электрические параметры НЧ",
            rule_type="per_core",
        ),
        TestItem(
            code="voltage_test",
            name="Испытание напряжением",
            base_cost=400,
            category="Электрические параметры НЧ",
        ),
    ]

    existing = get_all_test_items(db_path)
    if len(existing) < 5:
        for item in demo:
            insert_test_item(item, db_path)
    sync_climatic_tests(db_path)


def insert_test_item(item: TestItem, db_path: str | Path = DB_PATH_DEFAULT) -> int:
    """Вставляет или обновляет элемент прайс-листа по коду."""
    with get_connection(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO test_items (code, name, base_cost, category, method, rule_type, rule_params)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(code) DO UPDATE SET
                name=excluded.name,
                base_cost=excluded.base_cost,
                category=excluded.category,
                method=excluded.method,
                rule_type=excluded.rule_type,
                rule_params=excluded.rule_params
            """,
            (
                item.code,
                item.name,
                item.base_cost,
                item.category,
                item.method,
                item.rule_type,
                json.dumps(item.rule_params, ensure_ascii=False),
            ),
        )
        return cursor.lastrowid or 0


def get_test_item_by_code(code: str, db_path: str | Path = DB_PATH_DEFAULT) -> TestItem | None:
    """Получает TestItem по коду (с алиасом EN-климатики → slug)."""
    resolved = CLIMATE_ITEM_ALIASES.get(code, code)
    with get_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM test_items WHERE code = ?", (resolved,)).fetchone()
        if not row:
            return None
        data = dict(row)
        data["rule_params"] = json.loads(data.get("rule_params") or "{}")
        return TestItem(**data)


def get_all_test_items(db_path: str | Path = DB_PATH_DEFAULT) -> list[TestItem]:
    """Возвращает все тесты (для отладки и load-data)."""
    with get_connection(db_path) as conn:
        rows = conn.execute("SELECT * FROM test_items ORDER BY id").fetchall()
        return [
            TestItem(**{**dict(row), "rule_params": json.loads(row["rule_params"] or "{}")})
            for row in rows
        ]


def save_calculation(calc: Calculation, db_path: str | Path = DB_PATH_DEFAULT) -> int:
    """Сохраняет расчёт + все строки детализации. Возвращает id расчёта."""
    with get_connection(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO calculations
                (mark, parsed_mark, total_cost_without_vat, vat_rate,
                 total_cost_with_vat, source, output_path, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                calc.mark,
                calc.parsed_mark.model_dump_json(),
                calc.total_cost_without_vat,
                calc.vat_rate,
                calc.total_cost_with_vat,
                calc.source,
                calc.output_path,
                calc.created_at.isoformat(),
            ),
        )
        calc_id = cursor.lastrowid

        for line in calc.lines:
            conn.execute(
                """
                INSERT INTO calculation_lines
                    (calculation_id, test_item_id, test_name, base_cost,
                     multiplier, quantity, hours, final_cost, note)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    calc_id,
                    line.test_item_id,
                    line.test_name,
                    line.base_cost,
                    line.multiplier,
                    line.quantity,
                    line.hours,
                    line.final_cost,
                    line.note,
                ),
            )
        return calc_id or 0


def get_recent_calculations(limit: int = 10, db_path: str | Path = DB_PATH_DEFAULT) -> list[dict[str, Any]]:
    """История последних расчётов (для команды history)."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT id, mark, total_cost_with_vat, source, created_at
            FROM calculations ORDER BY created_at DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]


def get_calculations_for_kp(
    calculation_ids: list[int] | None = None,
    limit: int = 100,
    db_path: str | Path = DB_PATH_DEFAULT,
) -> list[dict[str, Any]]:
    """Возвращает расчёты для формирования КП (с итогами по марке)."""
    with get_connection(db_path) as conn:
        if calculation_ids:
            placeholders = ",".join("?" * len(calculation_ids))
            rows = conn.execute(
                f"""
                SELECT id, mark, total_cost_without_vat, total_cost_with_vat,
                       vat_rate, source, created_at, output_path
                FROM calculations
                WHERE id IN ({placeholders})
                ORDER BY id
                """,
                calculation_ids,
            ).fetchall()
            return [dict(row) for row in rows]
        rows = conn.execute(
            """
            SELECT id, mark, total_cost_without_vat, total_cost_with_vat,
                   vat_rate, source, created_at, output_path
            FROM calculations ORDER BY created_at DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]


def update_calculation_output_path(
    calculation_id: int,
    output_path: str,
    db_path: str | Path = DB_PATH_DEFAULT,
) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            "UPDATE calculations SET output_path = ? WHERE id = ?",
            (output_path, calculation_id),
        )



'''---Загрузка прайс-листа из Excel (минимальная, версия)---'''


try:
    from openpyxl import load_workbook
except ImportError:
    load_workbook = None


def _slugify(text: str) -> str:
    """Делает короткий код из русского названия теста."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "_", text)
    return text[:55]


def load_price_list_from_xlsx(
    xlsx_path: str | Path,
    db_path: str | Path = DB_PATH_DEFAULT,
    sheet_name: str = "Стоимость",
) -> int:
    """
    Загружает прайс-лист в таблицу test_items.
    
    Использует openpyxl. Берёт:
    - B (Наименование) → name + code (slug)
    - D (Стоимость) → base_cost
    - F (Категория)
    - G (Метод)
    
    rule_type определяется автоматически (per_core, per_group, time_based, fixed).
    """
    if load_workbook is None:
        raise RuntimeError("openpyxl не установлен")

    wb = load_workbook(xlsx_path, data_only=True)
    ws = wb[sheet_name] if sheet_name in wb.sheetnames else wb.active

    count = 0
    with get_connection(db_path) as conn:
        for idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
            if not row or not row[1]:
                continue
            name = str(row[1]).strip()
            if not name or name.lower() == "наименование":
                continue

            try:
                base_cost = float(row[3]) if row[3] is not None else 0.0
            except (TypeError, ValueError):
                base_cost = 0.0

            category = str(row[5]).strip() if row[5] else None
            method = str(row[6]).strip() if row[6] else None

            code = _slugify(name) or f"test_{idx}"
            rule_type, rule_params = infer_rule_type(name, category, code)

            item = TestItem(
                code=code,
                name=name,
                base_cost=base_cost,
                category=category,
                method=method,
                rule_type=rule_type,  # type: ignore[arg-type]
                rule_params=rule_params,
            )
            insert_test_item(item, db_path)
            count += 1

    print(f"Загружено {count} позиций прайс-листа")
    return count

'''---Новые функции управления справочником испытаний (Итерация 2)---'''

def add_test_item(item: TestItemCreate, db_path: str | Path = DB_PATH_DEFAULT) -> int:
    """Добавляет новое испытание в справочник test_items.
    
    Использует Pydantic-модель TestItemCreate для валидации входных данных.
    Если code уже существует — SQLite выбросит IntegrityError.
    
    Args:
        item: Валидированная модель с данными испытания
        db_path: Путь к базе данных
        
    Returns:
        id созданной записи в БД
    """
    with get_connection(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO test_items 
            (code, name, base_cost, category, method, rule_type, rule_params)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item.code,
                item.name,
                item.base_cost,
                item.category,
                item.method,
                item.rule_type,
                json.dumps(item.rule_params, ensure_ascii=False),
            ),
        )
        return cursor.lastrowid or 0


def update_test_item(
    code: str, 
    updates: TestItemUpdate, 
    db_path: str | Path = DB_PATH_DEFAULT
) -> bool:
    """Частично обновляет испытание по коду.
    
    Обновляет только те поля, которые реально были переданы в модели updates.
    Использует exclude_unset=True внутри Pydantic.
    
    Args:
        code: Уникальный код испытания (например, 'temp_low')
        updates: Модель TestItemUpdate с полями для обновления
        db_path: Путь к БД
        
    Returns:
        True, если была обновлена хотя бы одна запись
    """
    # Получаем только те поля, которые пользователь реально передал
    update_data = updates.model_dump(exclude_unset=True)
    if not update_data:
        return False

    # Если обновляем rule_params — сериализуем в JSON
    if "rule_params" in update_data and update_data["rule_params"] is not None:
        update_data["rule_params"] = json.dumps(update_data["rule_params"], ensure_ascii=False)

    set_clause = ", ".join(f"{k} = ?" for k in update_data.keys())
    values = list(update_data.values()) + [code]

    with get_connection(db_path) as conn:
        cursor = conn.execute(
            f"UPDATE test_items SET {set_clause} WHERE code = ?", 
            values
        )
        return cursor.rowcount > 0


def list_test_items(
    category: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 200,
    db_path: str | Path = DB_PATH_DEFAULT,
) -> list[dict]:
    """Возвращает список испытаний с фильтрацией (для команды list-tests в CLI).
    
    Поддерживает фильтр по категории и поиск по названию/коду.
    """
    query = "SELECT * FROM test_items"
    params: list[Any] = []

    conditions: list[str] = []
    if category:
        conditions.append("category = ?")
        params.append(category)
    if search:
        conditions.append("(name LIKE ? OR code LIKE ?)")
        params.extend([f"%{search}%", f"%{search}%"])

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    query += " ORDER BY category, name LIMIT ?"
    params.append(limit)

    with get_connection(db_path) as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]


def bulk_upsert_test_items(
    items: list[TestItemCreate], 
    db_path: str | Path = DB_PATH_DEFAULT
) -> dict[str, int]:
    """Пакетное добавление/обновление испытаний (для команды import-tests).
    
    Использует INSERT OR REPLACE — если code уже есть, запись обновляется.
    Это удобно при повторной загрузке прайс-листа или его части.
    
    Returns:
        Статистика: сколько обработано и сколько было ошибок
    """
    stats = {"processed": 0, "errors": 0}

    with get_connection(db_path) as conn:
        for item in items:
            try:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO test_items 
                    (code, name, base_cost, category, method, rule_type, rule_params)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item.code,
                        item.name,
                        item.base_cost,
                        item.category,
                        item.method,
                        item.rule_type,
                        json.dumps(item.rule_params, ensure_ascii=False),
                    ),
                )
                stats["processed"] += 1
            except Exception:
                stats["errors"] += 1

        conn.commit()

    return stats