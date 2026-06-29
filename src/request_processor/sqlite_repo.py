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

from .models import Calculation, CalculationLine, TestItem, TestItemUpdate, TestItemCreate

# Путь по умолчанию (относительно корня проекта)
DB_PATH_DEFAULT = Path("data/app.db")


@contextmanager
def get_connection(db_path: str | Path = DB_PATH_DEFAULT):
    """
    Контекстный менеджер подключения к SQLite.
    
    Преимущества:
    - Автоматически commit при успехе и close при любом исходе
    - Включает foreign_keys (для целостности данных)
    - row_factory = sqlite3.Row → можно обращаться как к dict
    """
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

    CREATE INDEX IF NOT EXISTS idx_test_items_code ON test_items(code);
    CREATE INDEX IF NOT EXISTS idx_calculations_created_at ON calculations(created_at);
    """

    with get_connection(db_path) as conn:
        conn.executescript(schema)

    # Добавляем демо-тесты, чтобы calculate работал сразу после init-db
    _seed_demo_tests(db_path)
    print(f"База данных инициализирована: {db_path}")


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
        ),
        TestItem(
            code="voltage_test",
            name="Испытание напряжением",
            base_cost=400,
            category="Электрические параметры НЧ",
        ),
        # Климатические испытания (по твоей таблице)
        TestItem(
            code="temp_low",
            name="Выдержка при пониженной температуре",
            base_cost=350,
            category="Внешние воздействующие факторы",
            rule_type="time_based",
            rule_params={
                "hours_key": "temp_low",
                "default_hours": 2,
                "cost_per_hour": 350,        # пока 0, позже можно заполнить
            },
        ),
        TestItem(
            code="temp_high",
            name="Выдержка при повышенной температуре",
            base_cost=250,
            category="Внешние воздействующие факторы",
            rule_type="time_based",
            rule_params={
                "hours_key": "temp_high",
                "default_hours": 2,
                "cost_per_hour": 250,
            },
        ),
        TestItem(
            code="humidity",
            name="Стойкость к повышенной влажности",
            base_cost=300,
            category="Внешние воздействующие факторы",
            rule_type="time_based",
            rule_params={
                "hours_key": "humidity",
                "default_hours": 48,
                "cost_per_hour": 300,
            },
        ),
        TestItem(
            code="temp_cycling",
            name="Смена температур",
            base_cost=350,
            category="Внешние воздействующие факторы",
            rule_type="time_based",
            rule_params={
                "hours_key": "temp_cycling",
                "default_hours": 2,
                "cost_per_hour": 0,
            },
        ),
    ]

    existing = get_all_test_items(db_path)
    if len(existing) < 5:
        for item in demo:
            insert_test_item(item, db_path)


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
    """Получает TestItem по короткому коду (используется в калькуляторе)."""
    with get_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM test_items WHERE code = ?", (code,)).fetchone()
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
                     multiplier, hours, final_cost, note)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    calc_id,
                    line.test_item_id,
                    line.test_name,
                    line.base_cost,
                    line.multiplier,
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
    
    Все тесты загружаются с rule_type='fixed' (позже доработаем сложные правила).
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

            item = TestItem(
                code=code,
                name=name,
                base_cost=base_cost,
                category=category,
                method=method,
                rule_type="fixed",
                rule_params={},
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