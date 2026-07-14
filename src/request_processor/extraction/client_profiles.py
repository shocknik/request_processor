"""
Локальные профили клиента (gitignored): OCR-алиасы имён, адреса заводов.

Принцип: парсер **читает документ**. Здесь только:
  - как прочитать «битый» OCR (Сненка6 → Спецкабель — то, что на бланке);
  - канонические адреса для сверки.

Не подставлять выдуманные «шаблонные» организации без текста в документе.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from ..config import DATA_DIR

LOCAL_PROFILE_PATH = DATA_DIR / "client_profiles.local.yaml"
EXAMPLE_PROFILE_PATH = Path(__file__).resolve().parents[3] / "docs" / "client_profiles.example.yaml"


@lru_cache(maxsize=1)
def load_client_profile() -> dict[str, Any]:
    path = LOCAL_PROFILE_PATH
    if not path.is_file():
        return {}
    try:
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def reload_client_profile() -> None:
    load_client_profile.cache_clear()


def org_ocr_alias_pairs() -> tuple[tuple[str, str], ...]:
    """
    Пары (regex, replacement) для имён организаций из локального профиля.

    Пример в client_profiles.local.yaml:
      org_ocr_aliases:
        - pattern: "Сненка6[бе]?е?н?б"
          replacement: "Спецкабель"
        - pattern: "Cneu\\\\w*abel"
          replacement: "Спецкабель"
    """
    profile = load_client_profile()
    raw = profile.get("org_ocr_aliases") or []
    pairs: list[tuple[str, str]] = []
    if not isinstance(raw, list):
        return ()
    for item in raw:
        if not isinstance(item, dict):
            continue
        pat = (item.get("pattern") or "").strip()
        repl = (item.get("replacement") or "").strip()
        if pat and repl:
            pairs.append((pat, repl))
    return tuple(pairs)


def apply_org_ocr_aliases(text: str) -> str:
    """Применяет локальные OCR→канон для имён (только если заданы в local.yaml)."""
    if not text:
        return text
    for pattern, repl in org_ocr_alias_pairs():
        try:
            text = re.sub(pattern, repl, text, flags=re.IGNORECASE)
        except re.error:
            continue
    return text


def known_org_names_for_validation() -> set[str]:
    """Имена для сверки «не чушь» (не для подстановки вместо OCR)."""
    profile = load_client_profile()
    names = profile.get("known_org_names") or []
    if not isinstance(names, list):
        return set()
    return {str(n).strip() for n in names if str(n).strip()}
