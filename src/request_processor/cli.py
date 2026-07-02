"""
cli.py — точка входа командной строки (Click).

Все команды проекта:
- init-db
- load-data
- calculate
- process (минимальная версия)
- history

Запуск после `pip install -e .`:
    request-processor init-db

Или без установки:
    PYTHONPATH=src python -m cli init-db
"""

from __future__ import annotations
import re
import json
from pathlib import Path
from typing import Any, Optional

import click
from openpyxl import load_workbook

from request_processor.models import TestItemCreate

from .models import ClimaticTestSettings

from .sqlite_repo import (
    init_db,
    load_price_list_from_xlsx,
    save_calculation,
    get_recent_calculations,
    list_test_items,
    add_test_item,
    bulk_upsert_test_items,
    build_default_hours_map,
    get_climatic_settings,
    save_climatic_settings,
    save_cable_marks_from_matches,
    list_cable_marks,
    list_organizations,
    migrate_db,
    save_document_extraction,
    save_organizations_from_extraction,
    create_order_from_kp,
    list_orders,
    get_order_details,
    get_last_document_extraction,
    list_test_applications,
    list_test_mappings,
    add_test_mapping,
    list_generated_documents,
)
from .cost_calculator import calculate_cost, print_breakdown
from .kp_generator import generate_kp_from_db
from .application_generator import generate_application_from_order
from .pdf_extractor import extract_from_document
from .extraction_validator import format_validation_report, validate_extraction
from .requirement_mapper import map_requirements_to_tests, suggest_tests_for_mark
from request_processor import __version__

def _slugify(text: str) -> str:
    """Делает безопасный код из названия (простая версия)."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "_", text)
    return text[:60]

@click.group()
@click.version_option(version=__version__)
@click.pass_context
def cli(ctx: click.Context) -> None:
    """request_processor — расчёт заявок на испытания кабельной продукции."""
    ctx.ensure_object(dict)


@cli.command("init-db")
@click.option("--db", default="data/app.db", show_default=True, help="Путь к файлу SQLite")
def init_db_cmd(db: str) -> None:
    """Инициализирует базу данных и добавляет демо-тесты."""
    init_db(db)
    click.echo(click.style("✓ База данных инициализирована.", fg="green"))


@cli.command("migrate-db")
@click.option("--db", default="data/app.db", show_default=True)
def migrate_db_cmd(db: str) -> None:
    """Обновляет схему существующей БД (таблицы марок и настроек)."""
    migrate_db(db)
    click.echo(click.style("✓ Миграция выполнена.", fg="green"))


@cli.command("load-data")
@click.option("--price", required=True, type=click.Path(exists=True), help="Путь к прайс-листу .xlsx")
@click.option("--db", default="data/app.db", show_default=True)
def load_data_cmd(price: str, db: str) -> None:
    """Загружает прайс-лист в таблицу test_items."""
    click.echo(f"Загрузка прайс-листа: {price}")
    try:
        count = load_price_list_from_xlsx(price, db)
        click.echo(click.style(f"✓ Загружено {count} позиций.", fg="green"))
    except Exception as e:
        click.echo(click.style(f"Ошибка: {e}", fg="red"), err=True)


@cli.command("calculate")
@click.option("--mark", required=True, help="Полная марка кабеля")
@click.option("--cores", type=int, default=1, show_default=True, help="Количество жил/элементов")
@click.option("--groups", type=int, default=1, show_default=True, help="Количество групп")
@click.option("--tests", required=True, help="Коды испытаний через запятую")
@click.option("--hour", "hours_list", multiple=True, help="Часы в формате ключ=значение, можно указывать несколько раз. Пример: --hour temp_low=48")
@click.option("--hours", default="{}", help='JSON-строка (устаревший способ). Лучше используй --hour')
@click.option("--output", default="out", show_default=True, type=click.Path(), help="Папка для результатов")
@click.option("--save-to-db", is_flag=True, default=True, help="Сохранить расчёт в БД")
@click.option("--db", default="data/app.db", show_default=True)
def calculate_cmd(
    mark: str,
    cores: int,
    groups: int,
    tests: str,
    hours_list: tuple[str, ...],
    hours: str,
    output: str,
    save_to_db: bool,
    db: str,
) -> None:
    """Ручной расчёт стоимости для одной марки."""

    click.echo(f"Расчёт марки: {mark}")

    hours_dict: dict[str, float] = build_default_hours_map(db)

    # Новый удобный способ (--hour temp_low=48 --hour humidity=120)
    if hours_list:
        for item in hours_list:
            if "=" in item:
                key, value = item.split("=", 1)
                try:
                    hours_dict[key.strip()] = float(value.strip())
                except ValueError:
                    click.echo(click.style(f"⚠ Не удалось распарсить --hour {item}", fg="yellow"))
    else:
        try:
            hours_dict.update(json.loads(hours))
        except json.JSONDecodeError:
            if hours != "{}":
                click.echo(click.style("⚠ Не удалось распарсить --hours как JSON. Используйте --hour key=value", fg="yellow"))

    test_list = [t.strip() for t in tests.split(",") if t.strip()]

    try:
        calc = calculate_cost(mark, test_list, hours_dict, db)
        print_breakdown(calc)

        if save_to_db:
            calc_id = save_calculation(calc, db)
            click.echo(click.style(f"✓ Расчёт сохранён в БД (id={calc_id})", fg="green"))

        out_dir = Path(output)
        out_dir.mkdir(parents=True, exist_ok=True)

    except Exception as e:
        click.echo(click.style(f"Ошибка расчёта: {e}", fg="red"), err=True)
        raise


@cli.command("extract-pdf")
@click.option("--pdf", required=True, type=click.Path(exists=True), help="Путь к PDF или Word (.docx)")
@click.option(
    "--output",
    "output_path",
    default=None,
    type=click.Path(),
    help="Путь для JSON-результата (по умолчанию data/extracted/<имя>.json)",
)
@click.option("--show-marks", is_flag=True, help="Показать найденные марки кабелей")
@click.option("--full-text", is_flag=True, help="Вывести полный извлечённый текст")
@click.option("--no-ocr", is_flag=True, help="Не запускать OCR для сканов")
@click.option("--ocr-dpi", default=200, show_default=True, type=int, help="DPI для OCR сканов")
@click.option("--no-save-marks", is_flag=True, help="Не сохранять марки в БД")
@click.option("--no-save-orgs", is_flag=True, help="Не сохранять организации в БД")
@click.option(
    "--dry-run",
    is_flag=True,
    help="Сохранить только JSON, без записи в БД (марки, организации, document_extractions)",
)
@click.option(
    "--validate",
    is_flag=True,
    help="Вывести отчёт валидатора парсинга; код выхода 1 при блокировке подтверждения",
)
@click.option("--db", default="data/app.db", show_default=True)
def extract_pdf_cmd(
    pdf: str,
    output_path: Optional[str],
    show_marks: bool,
    full_text: bool,
    no_ocr: bool,
    ocr_dpi: int,
    no_save_marks: bool,
    no_save_orgs: bool,
    dry_run: bool,
    validate: bool,
    db: str,
) -> None:
    """Извлекает текст, таблицы, марки и организации из PDF или Word."""
    pdf_file = Path(pdf)

    try:
        result = extract_from_document(pdf_file, use_ocr=not no_ocr, ocr_dpi=ocr_dpi)
    except Exception as e:
        click.echo(click.style(f"Ошибка извлечения: {e}", fg="red"), err=True)
        raise SystemExit(1) from e

    click.echo(f"Файл: {pdf_file.name}")
    click.echo(f"Страниц: {result.page_count}")
    click.echo(f"Символов текста: {len(result.text)}")
    click.echo(f"Таблиц: {len(result.tables)}")
    click.echo(f"Найдено марок: {len(result.cable_marks)}")
    if result.customer_name:
        click.echo(f"Заказчик: {result.customer_name}")
    if result.manufacturer_name and result.manufacturer_name != result.customer_name:
        click.echo(f"Производитель: {result.manufacturer_name}")
    if result.organizations:
        click.echo(click.style("\nОрганизации:", bold=True))
        for org in result.organizations:
            click.echo(f"  [{org.role}] {org.name}")
            if org.inn:
                click.echo(f"     ИНН/КПП: {org.inn}/{org.kpp or '—'}")
            if org.address:
                click.echo(f"     Адрес: {org.postal_code or ''} {org.address}".strip())

    if result.is_scanned:
        if result.ocr_used:
            click.echo(click.style("Скан распознан через OCR.", fg="cyan"))
        elif no_ocr:
            click.echo(
                click.style(
                    "⚠ PDF — скан без текстового слоя. Запусти без --no-ocr для распознавания.",
                    fg="yellow",
                )
            )
        else:
            click.echo(
                click.style(
                    "⚠ PDF — скан, но OCR не дал текста. Проверь установку Tesseract/easyocr.",
                    fg="yellow",
                )
            )

    if show_marks or result.cable_marks:
        if result.cable_marks:
            click.echo(click.style("\nМарки кабелей:", bold=True))
            for i, match in enumerate(result.cable_marks, 1):
                click.echo(f"  {i}. {match.mark}")
                if match.context and show_marks:
                    click.echo(f"     …{match.context}…")
        elif show_marks:
            click.echo("Марки не найдены.")

    if full_text:
        click.echo(click.style("\n--- Текст ---\n", bold=True))
        click.echo(result.text if result.text else "(пусто)")

    validation_report = validate_extraction(result) if validate else None
    skip_db = dry_run or no_save_marks

    out = Path(output_path) if output_path else Path("data/extracted") / f"{pdf_file.stem}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        result.model_dump_json(indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    click.echo(click.style(f"\n✓ Результат сохранён: {out}", fg="green"))

    if validation_report is not None:
        click.echo(click.style("\n--- Валидация ---\n", bold=True))
        click.echo(format_validation_report(validation_report, source_name=pdf_file.name))

    if dry_run:
        click.echo(click.style("Режим --dry-run: запись в БД пропущена.", fg="cyan"))

    if not skip_db and result.cable_marks:
        migrate_db(db)
        stats = save_cable_marks_from_matches(
            result.cable_marks,
            source=str(pdf_file.resolve()),
            db_path=db,
        )
        click.echo(
            click.style(
                f"✓ Марки в БД: сохранено {stats['saved']}, ошибок {stats['errors']}",
                fg="green",
            )
        )

    if not dry_run and not no_save_orgs and result.organizations:
        migrate_db(db)
        org_ids = save_organizations_from_extraction(
            result.organizations,
            source=str(pdf_file.resolve()),
            db_path=db,
        )
        save_document_extraction(
            source_path=str(pdf_file.resolve()),
            source_type=result.source_type,
            text=result.text,
            marks_count=len(result.cable_marks),
            customer_org_id=org_ids.get("customer_org_id"),
            manufacturer_org_id=org_ids.get("manufacturer_org_id"),
            db_path=db,
        )
        click.echo(
            click.style(
                f"✓ Организации в БД: заказчик id={org_ids.get('customer_org_id')}, "
                f"производитель id={org_ids.get('manufacturer_org_id')}",
                fg="green",
            )
        )

    if validation_report is not None and validation_report.block_confirm:
        raise SystemExit(1)


@cli.command("list-organizations")
@click.option("--search", default=None, help="Поиск по названию, ИНН, адресу")
@click.option("--type", "org_type", default=None, help="Тип: manufacturer, testing_center, …")
@click.option("--limit", default=50, show_default=True)
@click.option("--db", default="data/app.db", show_default=True)
def list_organizations_cmd(search: str | None, org_type: str | None, limit: int, db: str) -> None:
    """Список организаций из справочника БД."""
    migrate_db(db)
    rows = list_organizations(search=search, org_type=org_type, limit=limit, db_path=db)
    if not rows:
        click.echo("Организации не найдены.")
        return
    for row in rows:
        acc = "аккред." if row.get("is_accredited") else "не аккред."
        click.echo(
            f"{row['id']:>4}  {row['name']}  [{row.get('org_type', 'unknown')}, {acc}]"
        )
        if row.get("inn"):
            click.echo(f"       ИНН {row['inn']}" + (f"/{row['kpp']}" if row.get("kpp") else ""))
        if row.get("address"):
            click.echo(f"       {row.get('postal_code', '')} {row['address']}".strip())
        if row.get("fsa_registry_number"):
            click.echo(f"       ФСА: {row['fsa_registry_number']}")


@cli.command("process")
@click.option("--input", required=True, type=click.Path(exists=True), help="Путь к PDF/документу")
@click.option("--output", default="data/extracted", show_default=True)
@click.option("--show-marks", is_flag=True, default=True, help="Показать найденные марки")
def process_cmd(input: str, output: str, show_marks: bool) -> None:
    """Обработка заявки из PDF: извлечение марок и сохранение JSON."""
    pdf_file = Path(input)
    click.echo(f"Обработка документа: {pdf_file}")

    try:
        result = extract_from_document(pdf_file)
    except Exception as e:
        click.echo(click.style(f"Ошибка: {e}", fg="red"), err=True)
        raise SystemExit(1) from e

    if result.customer_name:
        click.echo(f"Заказчик: {result.customer_name}")

    if result.is_scanned and result.ocr_used:
        click.echo(click.style("Скан распознан через OCR.", fg="cyan"))

    if show_marks and result.cable_marks:
        click.echo(click.style("\nНайденные марки:", bold=True))
        for i, match in enumerate(result.cable_marks, 1):
            click.echo(f"  {i}. {match.mark}")

    out_dir = Path(output)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{pdf_file.stem}.json"
    out_file.write_text(
        result.model_dump_json(indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    click.echo(click.style(f"✓ Сохранено: {out_file}", fg="green"))


@cli.command("history")
@click.option("--limit", default=10, show_default=True, type=int)
@click.option("--db", default="data/app.db")
def history_cmd(limit: int, db: str) -> None:
    """Показывает последние расчёты из БД."""
    records = get_recent_calculations(limit, db)
    if not records:
        click.echo("История пуста.")
        return

    click.echo(click.style(f"\nПоследние {len(records)} расчётов:\n", bold=True))
    for r in records:
        click.echo(
            f"#{r['id']:>3} | {r['created_at'][:16]} | {r['mark'][:50]:<50} | "
            f"{r['total_cost_with_vat']:>10.2f} ₽ | {r['source']}"
        )
        
        
'''---Управление справочником испытаний (Итерация 2)---'''

@cli.command("list-tests")
@click.option("--category", help="Фильтр по категории")
@click.option("--search", help="Поиск по названию или коду")
@click.option("--limit", default=100, show_default=True)
def list_tests(category: Optional[str], search: Optional[str], limit: int):
    """Выводит список испытаний из справочника."""
    items = list_test_items(category=category, search=search, limit=limit)

    if not items:
        click.echo("Испытания не найдены.")
        return

    click.echo(f"{'Код':<28} {'Наименование':<55} {'Стоимость':>10}  Правило")
    click.echo("-" * 110)

    for item in items:
        click.echo(
            f"{item['code']:<28} {item['name'][:53]:<55} "
            f"{item['base_cost']:>10.0f}  {item['rule_type']}"
        )


@cli.command("add-test-item")
@click.option("--code", required=True, help="Уникальный код (slug)")
@click.option("--name", required=True, help="Полное наименование")
@click.option("--base-cost", "base_cost", required=True, type=float, help="Стоимость без НДС")
@click.option("--category", required=True, help="Категория")
@click.option("--method", default=None)
@click.option(
    "--rule-type",
    "rule_type",
    type=click.Choice(["fixed", "per_core", "per_group", "time_based"]),
    default="fixed",
    show_default=True,
)
@click.option("--hours-key", default=None, help="Ключ часов для time_based")
@click.option("--default-hours", default=None, type=float, help="Часы выдержки по умолчанию")
@click.option("--cost-per-hour", default=None, type=float, help="Стоимость за час выдержки")
def add_test_item_cmd(
    code, name, base_cost, category, method, rule_type,
    hours_key, default_hours, cost_per_hour,
):
    """Добавляет одно испытание вручную."""
    rule_params: dict[str, Any] = {}
    if rule_type == "time_based":
        rule_params = {
            "hours_key": hours_key or code,
            "default_hours": default_hours or 2.0,
            "cost_per_hour": cost_per_hour or 0.0,
        }
    item = TestItemCreate(
        code=code,
        name=name,
        base_cost=base_cost,
        category=category,
        method=method,
        rule_type=rule_type,
        rule_params=rule_params,
    )
    new_id = add_test_item(item)
    click.echo(f"✓ Добавлено испытание (id={new_id}) | {code}")


@cli.command("suggest-tests")
@click.option(
    "--requirements",
    "requirements_text",
    default=None,
    help="Текст контролируемых показателей / требований",
)
@click.option("--mark", default=None, help="Условное обозначение (для поиска в последнем JSON)")
@click.option("--db", default="data/app.db", show_default=True)
def suggest_tests_cmd(
    requirements_text: str | None,
    mark: str | None,
    db: str,
) -> None:
    """Предлагает коды испытаний по тексту требований из заявки."""
    migrate_db(db)
    suggestions = []

    if requirements_text:
        suggestions = map_requirements_to_tests(requirements_text, db_path=db)
    elif mark:
        last = get_last_document_extraction(db)
        if not last:
            raise click.ClickException("Нет извлечённых заявок в БД. Сначала extract-pdf.")
        import json as _json
        from pathlib import Path as _Path

        src = last.get("source_path") or ""
        stem = _Path(src).stem
        json_path = _Path("data/extracted") / f"{stem}.json"
        if not json_path.exists():
            raise click.ClickException(f"JSON не найден: {json_path}")
        from .models import PdfExtractionResult

        result = PdfExtractionResult.model_validate(
            _json.loads(json_path.read_text(encoding="utf-8"))
        )
        match = next((m for m in result.cable_marks if mark.lower() in m.mark.lower()), None)
        if not match:
            raise click.ClickException(f"Марка «{mark}» не найдена в {json_path.name}")
        suggestions = suggest_tests_for_mark(match, db_path=db)
    else:
        raise click.ClickException("Укажите --requirements или --mark")

    if not suggestions:
        click.echo("Испытания не определены по тексту требований.")
        return

    click.echo(click.style("Предложенные испытания:\n", bold=True))
    for s in suggestions:
        src = "БД" if s.source == "database" else "правило"
        pat = f"  «{s.matched_pattern}»" if s.matched_pattern else ""
        click.echo(f"  {s.code:<22} {s.confidence:>4.0%}  {s.name[:45]:<45}  [{src}]{pat}")


@cli.command("list-test-mappings")
@click.option("--test-code", default=None, help="Фильтр по коду испытания")
@click.option("--limit", default=50, show_default=True)
@click.option("--db", default="data/app.db", show_default=True)
def list_test_mappings_cmd(test_code: str | None, limit: int, db: str) -> None:
    """Справочник маппинга «фраза требования → испытание»."""
    migrate_db(db)
    rows = list_test_mappings(test_code=test_code, limit=limit, db_path=db)
    if not rows:
        click.echo("Маппинги не найдены.")
        return
    for row in rows:
        click.echo(
            f"{row['id']:>4}  {row['test_code']:<22}  "
            f"×{row.get('usage_count', 0):<3}  {row['requirement_pattern']}"
        )


@cli.command("add-test-mapping")
@click.option("--pattern", required=True, help="Фраза из заявки (подстрока, без учёта регистра)")
@click.option("--test-code", required=True, help="Код испытания из test_items")
@click.option("--note", default=None)
@click.option("--db", default="data/app.db", show_default=True)
def add_test_mapping_cmd(pattern: str, test_code: str, note: str | None, db: str) -> None:
    """Добавляет маппинг требования на испытание."""
    migrate_db(db)
    mapping_id = add_test_mapping(pattern, test_code, note=note, db_path=db)
    click.echo(click.style(f"✓ Маппинг сохранён (id={mapping_id})", fg="green"))


@cli.command("list-cable-marks")
@click.option("--search", default=None, help="Поиск по марке")
@click.option("--limit", default=50, show_default=True)
@click.option("--db", default="data/app.db", show_default=True)
def list_cable_marks_cmd(search: Optional[str], limit: int, db: str) -> None:
    """Список накопленных марок кабелей из БД."""
    rows = list_cable_marks(search=search, limit=limit, db_path=db)
    if not rows:
        click.echo("Марки не найдены.")
        return
    click.echo(
        f"{'Усл. обозначение':<45} {'Марка':<12} {'ТПЖ':>4} {'Размер':>10}  Документ"
    )
    click.echo("-" * 110)
    for row in rows:
        unit = "мм²" if row.get("size_unit") == "mm2" else "мм"
        click.echo(
            f"{row['full_mark'][:44]:<45} {row['brand'][:11]:<12} "
            f"{row['cores_count']:>4} "
            f"{row['characteristic_size']:>8}{unit:<2}  "
            f"{(row.get('document') or '')[:30]}"
        )


@cli.command("set-climatic-hours")
@click.option("--temp-low", default=None, type=float, help="Пониженная температура, ч")
@click.option("--temp-high", default=None, type=float, help="Повышенная температура, ч")
@click.option("--temp-cycling", default=None, type=float, help="Изменение температур, ч")
@click.option("--humidity", default=None, type=float, help="Повышенная влажность, ч")
@click.option("--solar-radiation", default=None, type=float, help="Солнечная радиация, ч")
@click.option("--db", default="data/app.db", show_default=True)
def set_climatic_hours_cmd(
    temp_low: Optional[float],
    temp_high: Optional[float],
    temp_cycling: Optional[float],
    humidity: Optional[float],
    solar_radiation: Optional[float],
    db: str,
) -> None:
    """Настройка времени выдержки климатических испытаний."""
    migrate_db(db)
    current = get_climatic_settings(db) or ClimaticTestSettings()
    settings = ClimaticTestSettings(
        temp_low=temp_low if temp_low is not None else current.temp_low,
        temp_high=temp_high if temp_high is not None else current.temp_high,
        temp_cycling=temp_cycling if temp_cycling is not None else current.temp_cycling,
        humidity=humidity if humidity is not None else current.humidity,
        solar_radiation=solar_radiation if solar_radiation is not None else current.solar_radiation,
    )
    save_climatic_settings(settings, db)
    click.echo(
        f"✓ Выдержка: temp_low={settings.temp_low}, temp_high={settings.temp_high}, "
        f"temp_cycling={settings.temp_cycling}, humidity={settings.humidity}, "
        f"solar_radiation={settings.solar_radiation} ч"
    )


@cli.command("import-tests")
@click.option("--file", "file_path", required=True, type=click.Path(exists=True), help="Путь к Excel-файлу")
@click.option("--dry-run", is_flag=True, help="Только проверить файл, ничего не записывать")
@click.option("--sheet", default=None, help="Название листа (по умолчанию первый)")
def import_tests(file_path: str, dry_run: bool, sheet: Optional[str]):
    """Пакетная загрузка / обновление испытаний из Excel."""
    wb = load_workbook(file_path, data_only=True)
    ws = wb[sheet] if sheet else wb.active

    items_to_import: list[TestItemCreate] = []
    errors: list[str] = []

    for row_idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        if not row or not row[1]:
            continue

        try:
            name = str(row[1]).strip()
            if not name:
                continue

            # === Генерация code, если он не указан ===
            raw_code = str(row[0]).strip() if row[0] else ""
            code = raw_code if raw_code else _slugify(name)

            item = TestItemCreate(
                code=code,
                name=name,
                base_cost=float(row[2]) if row[2] is not None else 0.0,
                category=str(row[3]).strip() if row[3] else "Без категории",
                method=str(row[4]).strip() if row[4] else None,
                rule_type=str(row[5]).strip() if row[5] else "fixed",
                rule_params=json.loads(str(row[6])) if row[6] else {},
            )
            items_to_import.append(item)

        except Exception as e:
            errors.append(f"Строка {row_idx}: {e}")

    # === Вывод результатов ===
    click.echo(f"Найдено записей для импорта: {len(items_to_import)}")
    if errors:
        click.echo(f"Ошибок при чтении: {len(errors)}")
        for err in errors[:10]:  # показываем первые 10 ошибок
            click.echo(f"  - {err}")
        if len(errors) > 10:
            click.echo(f"  ... и ещё {len(errors) - 10} ошибок")

    if dry_run:
        click.echo("\nРежим --dry-run: изменения в базу не записаны.")
        return

    if not items_to_import:
        click.echo("Нет данных для загрузки.")
        return

    # Загружаем в БД
    stats = bulk_upsert_test_items(items_to_import)
    click.echo(f"\n✓ Успешно обработано: {stats['processed']}")
    if stats.get("errors", 0) > 0:
        click.echo(f"⚠ Ошибок при записи: {stats['errors']}")


@cli.command("generate-kp")
@click.option("--customer", required=True, help="Заказчик / изготовитель")
@click.option(
    "--subject",
    default="Проведение периодических испытаний",
    show_default=True,
    help="Предмет коммерческого предложения",
)
@click.option("--calc-ids", required=True, help="ID расчётов через запятую (например: 1,2,3,4)")
@click.option("--note", default=None, help="Дополнительный текст")
@click.option(
    "--output",
    "output_path",
    default=None,
    type=click.Path(),
    help="Путь к .docx (по умолчанию data/generated/КП_...)",
)
@click.option("--db", default="data/app.db", show_default=True)
def generate_kp_cmd(
    customer: str,
    subject: str,
    calc_ids: str,
    note: Optional[str],
    output_path: Optional[str],
    db: str,
) -> None:
    """Формирует коммерческое предложение (Word) по выбранным расчётам."""
    ids = [int(x.strip()) for x in calc_ids.split(",") if x.strip()]
    if not ids:
        raise click.ClickException("Укажите хотя бы один ID расчёта в --calc-ids")

    if output_path:
        out = Path(output_path)
    else:
        safe = re.sub(r'[<>:"/\\|?*]', "", customer)[:40] or "заказчик"
        from .sqlite_repo import GENERATED_DIR_DEFAULT

        out = GENERATED_DIR_DEFAULT / f"КП_{safe}.docx"

    try:
        path = generate_kp_from_db(
            customer=customer,
            subject=subject,
            calculation_ids=ids,
            output_path=out,
            db_path=db,
            note=note,
        )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    migrate_db(db)
    last_doc = get_last_document_extraction(db)
    order_id = create_order_from_kp(
        customer_name=customer,
        manufacturer_name=last_doc.get("manufacturer_name") if last_doc else None,
        subject=subject,
        note=note,
        calculation_ids=ids,
        kp_output_path=str(path),
        document_extraction_id=int(last_doc["id"]) if last_doc else None,
        db_path=db,
    )
    click.echo(click.style(f"✓ КП сохранено: {path}", fg="green"))
    click.echo(click.style(f"✓ Заказ №{order_id} создан", fg="green"))


@cli.command("generate-application")
@click.option("--order-id", required=True, type=int, help="ID заказа в БД")
@click.option(
    "--output",
    "output_path",
    default=None,
    type=click.Path(),
    help="Путь к .docx (по умолчанию data/generated/Заявка_...)",
)
@click.option("--db", default="data/app.db", show_default=True)
def generate_application_cmd(order_id: int, output_path: Optional[str], db: str) -> None:
    """Формирует заявку на испытания (Word) по сохранённому заказу."""
    migrate_db(db)
    try:
        path = generate_application_from_order(
            order_id,
            output_path=Path(output_path) if output_path else None,
            db_path=db,
        )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(click.style(f"✓ Заявка сохранена: {path}", fg="green"))


@cli.command("list-generated-documents")
@click.option("--order-id", default=None, type=int, help="Фильтр по заказу")
@click.option("--type", "doc_type", type=click.Choice(["kp", "application"]), default=None)
@click.option("--limit", default=20, show_default=True)
@click.option("--db", default="data/app.db", show_default=True)
def list_generated_documents_cmd(
    order_id: int | None,
    doc_type: str | None,
    limit: int,
    db: str,
) -> None:
    """История сгенерированных файлов (КП, заявки на испытания)."""
    migrate_db(db)
    rows = list_generated_documents(order_id=order_id, doc_type=doc_type, limit=limit, db_path=db)
    if not rows:
        click.echo("Сгенерированные документы не найдены.")
        return
    for row in rows:
        click.echo(
            f"{row['id']:>4}  заказ №{row.get('order_id') or '—':>4}  "
            f"{row['doc_type']:<12}  {(row.get('created_at') or '')[:16]}  "
            f"{row['file_path']}"
        )


@cli.command("list-applications")
@click.option("--order-id", default=None, type=int, help="Фильтр по заказу")
@click.option("--limit", default=20, show_default=True)
@click.option("--db", default="data/app.db", show_default=True)
def list_applications_cmd(order_id: int | None, limit: int, db: str) -> None:
    """История сформированных заявок на испытания из БД."""
    migrate_db(db)
    rows = list_test_applications(order_id=order_id, limit=limit, db_path=db)
    if not rows:
        click.echo("Заявки на испытания не найдены.")
        return
    for row in rows:
        click.echo(
            f"{row['id']:>4}  заказ №{row['order_id']}  "
            f"{(row.get('created_at') or '')[:16]}  "
            f"{(row.get('test_type') or '—'):18}  "
            f"марок: {row.get('marks_count') or 0}"
        )
        click.echo(f"       {(row.get('customer_name') or '—')[:50]}")
        click.echo(f"       {row.get('output_path') or '—'}")


@cli.command("list-orders")
@click.option("--limit", default=20, show_default=True)
@click.option("--db", default="data/app.db", show_default=True)
def list_orders_cmd(limit: int, db: str) -> None:
    """Список сохранённых заказов (КП)."""
    migrate_db(db)
    rows = list_orders(limit=limit, db_path=db)
    if not rows:
        click.echo("Заказы не найдены.")
        return
    for row in rows:
        click.echo(
            f"{row['id']:>4}  {(row.get('created_at') or '')[:16]}  "
            f"{(row.get('customer_name') or '—')[:35]:35}  "
            f"марок: {row.get('marks_count') or 0}  "
            f"{float(row.get('total_with_vat') or 0):,.2f} ₽".replace(",", " ")
        )


@cli.command("gui")
def gui_cmd() -> None:
    """Запускает графический интерфейс (tkinter)."""
    from .gui import main

    main()


if __name__ == "__main__":
    cli()