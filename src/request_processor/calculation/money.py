"""Денежные операции через Decimal (копейки)."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Union

MoneyLike = Union[int, float, str, Decimal]

_TWO_PLACES = Decimal("0.01")


def to_decimal(value: MoneyLike) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def money_round(value: MoneyLike) -> float:
    """Округление до копеек (ROUND_HALF_UP)."""
    return float(to_decimal(value).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP))