"""
cost_calculator.py — калькулятор стоимости испытаний.

Правила из шаблона прайса (Obsidian §39):
- количество испытаний (quantity) на строку;
- коэффициент сложности образца для базовой подготовки;
- минимальный заказ = базовая_стоимость;
- скидка / наценка в процентах;
- денежные суммы через Decimal.
"""

from __future__ import annotations

from collections import Counter
from decimal import Decimal
from pathlib import Path
from typing import Mapping, Optional

from ..config import MINIMUM_ORDER_CODE, SAMPLE_PREP_CODE, VAT_RATE
from ..models import CableMark, Calculation, CalculationLine, TestItem
from ..parsing.cable_mark_parser import parse_cable_mark
from ..persistence.sqlite_repo import get_test_item_by_code
from .climatic_tests import resolve_climate_item_code
from .money import money_round, to_decimal
from .sample_complexity import compute_sample_complexity

PREP_COMPLEXITY_CODE = SAMPLE_PREP_CODE


def normalize_test_quantities(
    test_codes: list[str],
    quantities: Mapping[str, int] | None = None,
) -> dict[str, int]:
    """Сливает дубликаты в списке кодов и объединяет с явными quantities."""
    merged: Counter[str] = Counter()
    for code in test_codes:
        c = (code or "").strip()
        if c:
            merged[c] += 1
    if quantities:
        for code, qty in quantities.items():
            c = (code or "").strip()
            if c and qty > 0:
                merged[c] = max(merged.get(c, 0), int(qty))
    return dict(merged)


def _resolve_item_code(code: str) -> str:
    return resolve_climate_item_code(code)


def _apply_rule(
    item: TestItem,
    hours_map: dict[str, float],
    parsed_mark: CableMark,
    *,
    quantity: int,
    complexity: float,
) -> tuple[float, float, Optional[str]]:
    """
    Применяет правило расчёта к одному испытанию.

    Возвращает (final_cost, multiplier, note) для одной единицы × quantity.
    """
    rule = item.rule_type
    params = item.rule_params or {}
    qty = max(1, quantity)

    if rule == "time_based":
        hours_key = params.get("hours_key", item.code)
        hours_val = hours_map.get(hours_key) or params.get("default_hours")
        if hours_val is None:
            hours_val = 0
        cost_per_hour = params.get("cost_per_hour", 0)
        unit = to_decimal(item.base_cost) + to_decimal(cost_per_hour) * to_decimal(hours_val)
        note = f"База {item.base_cost} + {hours_val} ч × {cost_per_hour} ₽/ч"
        if qty > 1:
            note += f"; ×{qty}"
        final = money_round(unit * qty)
        return final, float(hours_val), note

    if rule == "per_core":
        mult = float(parsed_mark.cores)
        unit = money_round(to_decimal(item.base_cost) * to_decimal(mult))
        note = f"× {parsed_mark.cores} жил"
        if qty > 1:
            note += f"; ×{qty} исп."
        return money_round(to_decimal(unit) * qty), mult, note

    if rule == "per_group":
        mult = float(parsed_mark.groups)
        unit = money_round(to_decimal(item.base_cost) * to_decimal(mult))
        note = f"× {parsed_mark.groups} эл. скрутки"
        if qty > 1:
            note += f"; ×{qty} исп."
        return money_round(to_decimal(unit) * qty), mult, note

    if item.code == PREP_COMPLEXITY_CODE:
        unit = money_round(to_decimal(item.base_cost) * to_decimal(complexity))
        note = f"× сложность {complexity}"
        if qty > 1:
            note += f"; ×{qty} исп."
        return money_round(to_decimal(unit) * qty), complexity, note

    unit = money_round(item.base_cost)
    note = f"×{qty} исп." if qty > 1 else None
    return money_round(to_decimal(unit) * qty), 1.0, note


def calculate_cost(
    mark: str | CableMark,
    test_codes: list[str],
    hours_map: Optional[dict[str, float]] = None,
    db_path: str | Path = "data/app.db",
    *,
    quantities: Mapping[str, int] | None = None,
    discount_percent: float = 0.0,
    markup_percent: float = 0.0,
    has_armor: bool | None = None,
    is_wire: bool | None = None,
    apply_minimum: bool = True,
) -> Calculation:
    """
    Главная функция калькулятора стоимости.

    Args:
        mark: Марка кабеля (строка или CableMark)
        test_codes: Коды испытаний (дубликаты сливаются в quantity)
        hours_map: {hours_key: часы} для time_based
        quantities: Явные количества {code: n} (перекрывают счётчик из списка)
        discount_percent: Скидка, %
        markup_percent: Наценка, %
        has_armor: Бронированный кабель (если None — из парсера / вопрос в GUI)
        is_wire: Провод, не кабель
        apply_minimum: Доплата до минимального заказа (базовая_стоимость)
    """
    hours_map = hours_map or {}
    parsed = parse_cable_mark(mark) if isinstance(mark, str) else mark
    qty_map = normalize_test_quantities(test_codes, quantities)
    complexity, complexity_note = compute_sample_complexity(
        parsed, has_armor=has_armor, is_wire=is_wire
    )

    lines: list[CalculationLine] = []
    subtotal = Decimal("0")

    for code, qty in qty_map.items():
        resolved = _resolve_item_code(code)
        item = get_test_item_by_code(resolved, db_path)
        if item is None:
            print(f"⚠ Тест '{code}' не найден в справочнике — пропускаю")
            continue

        if item.rule_type == "time_based":
            hours_key = item.rule_params.get("hours_key", resolved)
            has_hours = hours_key in hours_map or "default_hours" in (item.rule_params or {})
            if not has_hours:
                raise ValueError(
                    f"Для испытания '{resolved}' (time_based) не указано количество часов. "
                    f"Добавь --hour {hours_key}=<часы> или укажи default_hours в правиле."
                )

        final_cost, multiplier, note = _apply_rule(
            item,
            hours_map,
            parsed,
            quantity=qty,
            complexity=complexity,
        )

        hours_key = item.rule_params.get("hours_key", resolved)
        hours_value = hours_map.get(hours_key)
        if item.code == PREP_COMPLEXITY_CODE and note:
            note = f"{complexity_note}; {note}"

        line = CalculationLine(
            test_item_id=item.id or 0,
            test_name=item.name,
            base_cost=item.base_cost,
            multiplier=multiplier,
            quantity=qty,
            hours=hours_value,
            final_cost=final_cost,
            note=note,
        )
        lines.append(line)
        subtotal += to_decimal(final_cost)

    subtotal_f = money_round(subtotal)
    minimum_adjustment = 0.0
    adjusted = subtotal

    if apply_minimum:
        min_item = get_test_item_by_code(MINIMUM_ORDER_CODE, db_path)
        if min_item and subtotal_f < min_item.base_cost:
            minimum_adjustment = money_round(to_decimal(min_item.base_cost) - subtotal)
            adjusted = to_decimal(min_item.base_cost)

    if markup_percent:
        adjusted = adjusted * (Decimal("1") + to_decimal(markup_percent) / Decimal("100"))
    if discount_percent:
        adjusted = adjusted * (Decimal("1") - to_decimal(discount_percent) / Decimal("100"))

    total_without_vat = money_round(adjusted)
    if minimum_adjustment > 0:
        min_item = get_test_item_by_code(MINIMUM_ORDER_CODE, db_path)
        lines.append(
            CalculationLine(
                test_item_id=min_item.id if min_item else 0,
                test_name=min_item.name if min_item else "Минимальный заказ",
                base_cost=minimum_adjustment,
                multiplier=1.0,
                quantity=1,
                final_cost=minimum_adjustment,
                note="Доплата до минимальной стоимости заказа",
            )
        )

    vat_rate = VAT_RATE
    total_with_vat = money_round(to_decimal(total_without_vat) * (Decimal("1") + to_decimal(vat_rate)))

    return Calculation(
        mark=parsed.full_mark,
        parsed_mark=parsed,
        subtotal_before_adjustments=subtotal_f,
        minimum_adjustment=minimum_adjustment,
        discount_percent=discount_percent,
        markup_percent=markup_percent,
        sample_complexity=complexity,
        total_cost_without_vat=total_without_vat,
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
            f"Жилы: {calc.parsed_mark.cores}, Эл. скрутки: {calc.parsed_mark.groups}, "
            f"Сечение: {calc.parsed_mark.size} мм²"
        ),
        f"Сложность образца: {calc.sample_complexity}",
        "-" * 72,
    ]

    if not calc.lines:
        lines_out.append("Нет строк расчёта.")
    else:
        for i, line in enumerate(calc.lines, 1):
            qty_str = f" ×{line.quantity}" if line.quantity > 1 else ""
            note_str = f"  ({line.note})" if line.note else ""
            lines_out.append(
                f"{i:2}. {line.test_name[:48]:<48} {line.final_cost:>10.2f} ₽{qty_str}{note_str}"
            )
        lines_out.append("-" * 72)
        if calc.minimum_adjustment > 0:
            lines_out.append(
                f"Сумма испытаний:     {calc.subtotal_before_adjustments:>10.2f} ₽"
            )
            lines_out.append(
                f"Доплата до минимума:{calc.minimum_adjustment:>10.2f} ₽"
            )
        if calc.discount_percent or calc.markup_percent:
            adj = []
            if calc.markup_percent:
                adj.append(f"+{calc.markup_percent}%")
            if calc.discount_percent:
                adj.append(f"-{calc.discount_percent}%")
            lines_out.append(f"Корректировка:       {' '.join(adj)}")
        lines_out.extend(
            [
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