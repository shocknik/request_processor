"""
Коэффициент сложности образца для подготовки (базовая_подготовка_образцов).

Правила из шаблона прайса (Obsidian §39):
- по умолчанию 1.0;
- провод (не кабель) — 0.5;
- броня — +0.5;
- жил > 10 — +0.5;
- сечение > 10 мм² — +0.5.
"""

from __future__ import annotations

from ..models import CableMark
from ..parsing.cable_mark_parser import parse_cable_mark

_WIRE_BRAND_PREFIXES = ("ПВ", "ПГВ", "АПВ", "ПРГА", "ПРВ", "РКГМ", "ПУГВ", "ПУГП")


def is_wire_mark(mark: str, brand: str | None = None) -> bool:
    """Провод — по слову «провод» или типичным маркам без признаков кабеля."""
    text = (mark or "").lower()
    if "провод" in text:
        return True
    if "кабель" in text:
        return False
    base = (brand or mark.split()[0] if mark else "").upper()
    return any(base.startswith(p) for p in _WIRE_BRAND_PREFIXES)


def compute_sample_complexity(
    mark: str | CableMark,
    *,
    has_armor: bool | None = None,
    is_wire: bool | None = None,
) -> tuple[float, str]:
    """
    Возвращает (коэффициент, пояснение для note).

    has_armor / is_wire — переопределение от оператора (GUI).
    """
    parsed = parse_cable_mark(mark) if isinstance(mark, str) else mark
    coef = 1.0
    parts: list[str] = []

    wire = is_wire if is_wire is not None else is_wire_mark(parsed.full_mark, parsed.brand)
    if wire:
        coef = 0.5
        parts.append("провод 0.5")

    armor = has_armor if has_armor is not None else parsed.has_armor
    if armor:
        coef += 0.5
        parts.append("броня +0.5")

    if parsed.cores > 10:
        coef += 0.5
        parts.append(f"жил {parsed.cores} +0.5")

    if parsed.size > 10:
        coef += 0.5
        parts.append(f"сечение {parsed.size} +0.5")

    if not parts:
        parts.append("базовая 1.0")

    return coef, ", ".join(parts)