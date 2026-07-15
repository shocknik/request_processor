"""Реквизиты лаборатории и оформление КП (из data/lab_profile.yaml)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..config import DATA_DIR, PROJECT_ROOT

LAB_PROFILE_PATH = DATA_DIR / "lab_profile.yaml"
LAB_PROFILE_EXAMPLE = PROJECT_ROOT / "docs" / "lab_profile.example.yaml"

KP_STYLES = ("classic", "modern", "compact")


@dataclass
class LabProfile:
    name: str = "ООО «Испытательный центр»"
    tagline: str = "Испытательный центр кабельной продукции"
    address: str = ""
    phone: str = ""
    email: str = ""
    accreditation: str = ""
    website: str = ""
    logo_path: str = "data/logo_cable_test_new_4.jpg"
    kp_style: str = "classic"

    def resolved_logo(self) -> Path | None:
        raw = (self.logo_path or "").strip()
        if not raw:
            return None
        p = Path(raw)
        if not p.is_absolute():
            p = PROJECT_ROOT / p
        return p if p.is_file() else None


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
    return LabProfile(
        name=str(data.get("name") or LabProfile.name),
        tagline=str(data.get("tagline") or LabProfile.tagline),
        address=str(data.get("address") or ""),
        phone=str(data.get("phone") or ""),
        email=str(data.get("email") or ""),
        accreditation=str(data.get("accreditation") or ""),
        website=str(data.get("website") or ""),
        logo_path=str(data.get("logo_path") or LabProfile.logo_path),
        kp_style=style,
    )
