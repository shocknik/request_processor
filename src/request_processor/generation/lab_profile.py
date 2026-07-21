"""Реквизиты лаборатории и оформление КП (из data/lab_profile.yaml)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from ..config import DATA_DIR, PROJECT_ROOT

LAB_PROFILE_PATH = DATA_DIR / "lab_profile.yaml"
LAB_PROFILE_EXAMPLE = PROJECT_ROOT / "docs" / "lab_profile.example.yaml"

KP_STYLES = ("classic", "modern", "compact")

# Всегда считаем «своей» ИЛ (даже без yaml) — профиль лаборатории Кабель-Тест
_DEFAULT_OWN_LAB_ALIASES: tuple[str, ...] = (
    "кабель-тест",
    "кабель тест",
    "ниц кабель-тест",
    "ниц «кабель-тест»",
    "ооо ниц кабель-тест",
    "испытательный центр общества с ограниченной ответственностью ниц кабель-тест",
)


@dataclass
class LabProfile:
    name: str = 'ООО НИЦ «Кабель-Тест»'
    tagline: str = "Испытательный центр кабельной продукции"
    address: str = (
        "107497, РОССИЯ, город Москва, ул. Бирюсинка, д. 6, корп. 1-5, 6, 7, 9А"
    )
    phone: str = "+7 4956030655"
    email: str = ""
    accreditation: str = "РОСС RU.0001.21КБ32"
    website: str = ""
    logo_path: str = "data/logo_cable_test_new_4.jpg"
    kp_style: str = "classic"
    aliases: list[str] = field(default_factory=list)

    def resolved_logo(self) -> Path | None:
        """Путь к логотипу: yaml → fallbacks assets/app_logo.png, data/logo_…"""
        candidates: list[Path] = []
        raw = (self.logo_path or "").strip()
        if raw:
            p = Path(raw)
            if not p.is_absolute():
                p = PROJECT_ROOT / p
            candidates.append(p)
        candidates.extend(
            [
                PROJECT_ROOT / "assets" / "app_logo.png",
                PROJECT_ROOT / "data" / "logo_cable_test_new_4.jpg",
            ]
        )
        for p in candidates:
            if p.is_file():
                return p
        return None

    def own_name_keys(self) -> set[str]:
        """Нормализованные ключи «это наша ИЛ» (не заказчик/производитель)."""
        from ..extraction.organization_extractor import normalize_org_name

        keys: set[str] = set()
        for raw in (self.name, *self.aliases, *_DEFAULT_OWN_LAB_ALIASES):
            key = normalize_org_name(str(raw or ""))
            if key:
                keys.add(key)
        return keys


def load_lab_profile(path: Path | str | None = None) -> LabProfile:
    """Читает YAML; при отсутствии — defaults + example-поля."""
    target = Path(path) if path else LAB_PROFILE_PATH
    data: dict[str, Any] = {}
    for candidate in (target, LAB_PROFILE_EXAMPLE):
        if candidate.is_file():
            try:
                import yaml

                raw = yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}
                if isinstance(raw, dict):
                    data = raw
                    break
            except Exception:
                continue
    style = str(data.get("kp_style") or "classic").strip().lower()
    if style not in KP_STYLES:
        style = "classic"
    aliases_raw = data.get("aliases") or []
    aliases: list[str] = []
    if isinstance(aliases_raw, list):
        aliases = [str(a).strip() for a in aliases_raw if str(a).strip()]
    elif isinstance(aliases_raw, str) and aliases_raw.strip():
        aliases = [aliases_raw.strip()]
    return LabProfile(
        name=str(data.get("name") or LabProfile.name),
        tagline=str(data.get("tagline") or LabProfile.tagline),
        address=str(data.get("address") or LabProfile.address),
        phone=str(data.get("phone") or LabProfile.phone),
        email=str(data.get("email") or ""),
        accreditation=str(data.get("accreditation") or LabProfile.accreditation),
        website=str(data.get("website") or ""),
        logo_path=str(data.get("logo_path") or LabProfile.logo_path),
        kp_style=style,
        aliases=aliases,
    )


@lru_cache(maxsize=1)
def _cached_own_lab_keys() -> frozenset[str]:
    return frozenset(load_lab_profile().own_name_keys())


def clear_lab_profile_cache() -> None:
    """Сброс кэша после смены lab_profile.yaml (тесты / настройки)."""
    _cached_own_lab_keys.cache_clear()


def is_own_lab_name(name: str | None) -> bool:
    """
    True, если имя — наша ИЛ (Кабель-Тест / lab_profile).

    Такие организации не пишем в справочник заказчиков/производителей
    и не назначаем customer_org_id / manufacturer_org_id.
    """
    if not name or not str(name).strip():
        return False
    from ..extraction.organization_extractor import normalize_org_name

    key = normalize_org_name(str(name))
    if not key:
        return False
    if key in _cached_own_lab_keys():
        return True
    # эвристика: «кабель-тест» / «кабель тест» в любом виде
    compact = re.sub(r"[\s\-–—]+", "", key)
    if "кабельтест" in compact:
        return True
    return False
