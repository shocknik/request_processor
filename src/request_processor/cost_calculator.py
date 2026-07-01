"""
cost_calculation.py — калькулятор стоимости испытаний.

Основная логика расчёта:
- Принимает марку + список кодов тестов + часы
- Применяет правила (fixed, per_core, time_based)
- Возвращает Pydantic-модель Calculation с breakdown
- Не знает про CLI и генерацию документов (чистая функция)
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from .models import CableMark, Calculation, CalculationLine, TestItem
from .cable_mark_parser import parse_cable_mark
from .sqlite_repo import get_test_item_by_code


def _apply_rule(
    item: TestItem,
    hours_map: dict[str, float],
    parsed_mark: CableMark,
) -> tuple[float, float, Optional[str]]:
    """
    Применяет правило расчёта к одному испытанию.

    Возвращает:
        (final_cost, multiplier, note)
    """
    rule = item.rule_type
    params = item.rule_params or {}

    if rule == "time_based":
        # Берём часы либо из переданного hours_map, либо из default_hours в правиле
        hours_key = params.get("hours_key", item.code)
        hours_val = hours_map.get(hours_key) or params.get("default_hours")

        if hours_val is None:
            # Эту ситуацию лучше ловить раньше (в calculate_cost), но на всякий случай
            hours_val = 0

        cost_per_hour = params.get("cost_per_hour", 0)
        final_cost = item.base_cost + (cost_per_hour * hours_val)
        note = f"База {item.base_cost} + {hours_val} ч × {cost_per_hour} ₽/ч"

        return round(final_cost, 2), float(hours_val), note

    if rule == "per_core":
        mult = float(parsed_mark.cores)
        return round(item.base_cost * mult, 2), mult, f"× {parsed_mark.cores} жил"

    if rule == "per_group":
        mult = float(parsed_mark.groups)
        return round(item.base_cost * mult, 2), mult, f"× {parsed_mark.groups} пар"

    # По умолчанию — фиксированная стоимость
    return item.base_cost, 1.0, None


def calculate_cost(
    mark: str | CableMark,
    test_codes: list[str],
    hours_map: Optional[dict[str, float]] = None,
    db_path: str | Path = "data/app.db",
) -> Calculation:
    """
    Главная функция калькулятора стоимости.

    Args:
        mark: Марка кабеля (строка или уже разобранный CableMark)
        test_codes: Список кодов испытаний. Может содержать дубликаты.
        hours_map: Словарь {code_или_hours_key: количество_часов}
        db_path: Путь к базе данных

    Raises:
        ValueError: если для time_based теста не указаны часы и нет default_hours
    """
    hours_map = hours_map or {}
    parsed = parse_cable_mark(mark) if isinstance(mark, str) else mark

    lines: list[CalculationLine] = []
    total_without_vat = 0.0

    for code in test_codes:
        item = get_test_item_by_code(code, db_path)
        if item is None:
            print(f"⚠ Тест '{code}' не найден в справочнике — пропускаю")
            continue

        # === Валидация time_based ===
        if item.rule_type == "time_based":
            hours_key = item.rule_params.get("hours_key", code)
            has_hours = hours_key in hours_map or "default_hours" in (item.rule_params or {})
            if not has_hours:
                raise ValueError(
                    f"Для испытания '{code}' (time_based) не указано количество часов. "
                    f"Добавь --hour {hours_key}=<часы> или укажи default_hours в правиле."
                )

        final_cost, multiplier, note = _apply_rule(item, hours_map, parsed)

        # Определяем, какое значение часов записать в строку
        hours_key = item.rule_params.get("hours_key", code)
        hours_value = hours_map.get(hours_key)

        line = CalculationLine(
            test_item_id=item.id or 0,
            test_name=item.name,
            base_cost=item.base_cost,
            multiplier=multiplier,
            hours=hours_value,
            final_cost=final_cost,
            note=note,
        )
        lines.append(line)
        total_without_vat += final_cost

    vat_rate = 0.22
    total_with_vat = round(total_without_vat * (1 + vat_rate), 2)

    return Calculation(
        mark=parsed.full_mark,
        parsed_mark=parsed,
        total_cost_without_vat=round(total_without_vat, 2),
        vat_rate=vat_rate,
        total_cost_with_vat=total_with_vat,
        lines=lines,
        source="manual",
    )


def format_breakdown(calc: Calculation) -> str:
    """Форматирует расчёт в текст (CLI, GUI)."""
    lines_out = [
        "РАСЧЁТ СТОИМОСТИ ИСПЫТАНИЙ",
        f"Марка: {calc.mark}",
        (
            f"Жилы: {calc.parsed_mark.cores}, Групп: {calc.parsed_mark.groups}, "
            f"Сечение: {calc.parsed_mark.size} мм²"
        ),
        "-" * 72,
    ]

    if not calc.lines:
        lines_out.append("Нет строк расчёта.")
    else:
        for i, line in enumerate(calc.lines, 1):
            note_str = f"  ({line.note})" if line.note else ""
            lines_out.append(
                f"{i:2}. {line.test_name[:52]:<52} {line.final_cost:>10.2f} ₽{note_str}"
            )
        lines_out.extend(
            [
                "-" * 72,
                f"ИТОГО без НДС: {calc.total_cost_without_vat:>10.2f} ₽",
                f"НДС {int(calc.vat_rate * 100)}%:      "
                f"{(calc.total_cost_with_vat - calc.total_cost_without_vat):>10.2f} ₽",
                f"ИТОГО с НДС:   {calc.total_cost_with_vat:>10.2f} ₽",
            ]
        )
    return "\n".join(lines_out)


def print_breakdown(calc: Calculation) -> None:
    """Красивый вывод расчёта в терминал."""
    print("\n" + "=" * 72)
    print(format_breakdown(calc))
    print("=" * 72 + "\n")