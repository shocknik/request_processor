"""
Парсер марок кабелей (Итерация 1).
"""

from __future__ import annotations

import re
from typing import Any

from .models import CableMark


def _detect_fire_class(mark: str) -> str | None:
    patterns = [r"нг\(А\)", r"нг\(А\)-LS", r"нг\(А\)-LSLTx", r"HF", r"FRHF", r"FRLS"]
    for p in patterns:
        if match := re.search(p, mark, re.IGNORECASE):
            return match.group(0)
    return None


def _extract_numbers(mark: str) -> dict[str, Any]:
    s = mark.replace("×", "х").replace("x", "х").replace(",", ".")
    result = {"cores": 1, "groups": 1, "size": 1.0}

    # 3х4, 4зх2х2.5, 1х6 и т.д.
    if m := re.search(r"(\d+)\s*[зЗ]?\s*х\s*([\d.]+)", s):
        num = int(m.group(1))
        size = float(m.group(2))
        if re.search(r"\d+\s*[зЗ]\s*х", s):
            result["groups"] = num
            result["cores"] = num * 3
        else:
            result["cores"] = num
        result["size"] = size
        return result

    # 4х2х0.52 (LAN)
    if m := re.search(r"(\d+)\s*х\s*(\d+)\s*х\s*([\d.]+)", s):
        result["groups"] = int(m.group(1))
        result["cores"] = int(m.group(1)) * int(m.group(2))
        result["size"] = float(m.group(3))
        result["is_lan"] = True
        return result

    if m := re.search(r"(\d+)\s*х\s*([\d.]+)\s*$", s):
        result["cores"] = int(m.group(1))
        result["size"] = float(m.group(2))
    return result


def parse_cable_mark(mark: str) -> CableMark:
    if not mark or not mark.strip():
        raise ValueError("Пустая марка")

    original = mark.strip()
    brand = re.match(r"^([А-Яа-яЁёA-Za-z0-9\-]+)", original)
    brand = brand.group(1) if brand else original.split()[0]

    fire = _detect_fire_class(original)
    nums = _extract_numbers(original)

    material = None
    if m := re.search(r"\(([^)]+)\)", original):
        material = m.group(1)

    voltage = None
    if m := re.search(r"[-–]?\s*(\d[.,]?\d*)\s*(кВ)?", original):
        try:
            voltage = float(m.group(1).replace(",", "."))
            if voltage > 100:
                voltage /= 1000
        except ValueError:
            pass

    has_armor = bool(re.search(r"[ВвБб][Бб]", original) or "брон" in original.lower())

    return CableMark(
        full_mark=original,
        brand=brand,
        fire_class=fire,
        cores=nums["cores"],
        groups=nums["groups"],
        size=nums["size"],
        material=material,
        voltage=voltage,
        has_armor=has_armor,
        is_lan=nums.get("is_lan", False),
        extras={"raw": original},
    )