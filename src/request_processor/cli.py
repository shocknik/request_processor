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

import json
from pathlib import Path
from typing import Any

import click

from .sqlite_repo import (
    init_db,
    load_price_list_from_xlsx,
    save_calculation,
    get_recent_calculations,
)
from .cost_calculator import calculate_cost, print_breakdown
from request_processor import __version__

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

    hours_dict: dict[str, float] = {}

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
        # Старый способ через JSON (для обратной совместимости)
        try:
            hours_dict = json.loads(hours)
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


@cli.command("process")
@click.option("--input", required=True, type=click.Path(exists=True), help="Путь к PDF/документу")
@click.option("--output", default="out", show_default=True)
@click.option("--save-to-db", is_flag=True, default=True)
@click.option("--db", default="data/app.db")
def process_cmd(input: str, output: str, save_to_db: bool, db: str) -> None:
    """Минимальная обработка заявки из PDF (в разработке)."""
    click.echo(f"Обработка документа: {input}")
    click.echo(click.style("⚠ Функционал process в разработке (Итерация 1).", fg="yellow"))


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


if __name__ == "__main__":
    cli()