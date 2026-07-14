"""
Опциональное NLP-усиление извлечения (PyTorch + transformers).

Не обязательно для работы приложения: при отсутствии torch/transformers
все функции возвращают входные данные без изменений.

EasyOCR (OCR сканов) уже использует PyTorch под капотом.
Этот модуль добавляет NER для уточнения организаций в сложных письмах.
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache
from typing import Any

from ..models import OrganizationExtract
from ..extraction.organization_extractor import normalize_org_name, sanitize_address

logger = logging.getLogger(__name__)

# Мультиязычная NER-модель (~700 МБ при первом запуске, кэш HuggingFace)
DEFAULT_NER_MODEL = "Davlan/bert-base-multilingual-cased-ner-hrl"

_RECIENT_HINTS = re.compile(
    r"директору|видяев|испытательный центр|испытательн",
    re.IGNORECASE,
)


def is_nlp_available() -> bool:
    """Проверяет, установлены ли torch и transformers."""
    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401

        return True
    except ImportError:
        return False


@lru_cache(maxsize=1)
def _get_ner_pipeline(model_name: str = DEFAULT_NER_MODEL) -> Any | None:
    if not is_nlp_available():
        return None
    try:
        from transformers import pipeline

        logger.info("Загрузка NER-модели %s (PyTorch)…", model_name)
        return pipeline(
            "ner",
            model=model_name,
            aggregation_strategy="simple",
            device=-1,
        )
    except Exception as exc:
        logger.warning("NER pipeline недоступен: %s", exc)
        return None


def _entities_from_text(text: str, *, max_chars: int = 4000) -> list[dict[str, str]]:
    """Извлекает сущности ORG/LOC через transformers NER."""
    ner = _get_ner_pipeline()
    if ner is None:
        return []

    chunk = text[:max_chars]
    try:
        raw = ner(chunk)
    except Exception as exc:
        logger.warning("NER inference failed: %s", exc)
        return []

    entities: list[dict[str, str]] = []
    for item in raw:
        label = str(item.get("entity_group") or item.get("entity") or "")
        word = str(item.get("word") or "").strip()
        if not word:
            continue
        entities.append({"label": label, "text": word})
    return entities


def _merge_org_entities(entities: list[dict[str, str]]) -> list[str]:
    """Склеивает подряд идущие ORG в названия компаний."""
    names: list[str] = []
    buf: list[str] = []
    for ent in entities:
        if ent["label"] in ("ORG", "B-ORG", "I-ORG"):
            buf.append(ent["text"])
        else:
            if buf:
                names.append(re.sub(r"\s+", " ", " ".join(buf)).strip())
                buf = []
    if buf:
        names.append(re.sub(r"\s+", " ", " ".join(buf)).strip())
    return [n for n in names if len(n) >= 4]


def enhance_organizations(
    text: str,
    organizations: list[OrganizationExtract],
) -> list[OrganizationExtract]:
    """
    Уточняет список организаций с помощью NER (если PyTorch доступен).

    - Не подменяет уже уверенный разбор письма (confidence >= 0.8).
    - Отбрасывает ORG из строки «Генеральному директору …» (получатель).
    """
    if not organizations:
        return organizations

    if max(o.confidence for o in organizations) >= 0.8:
        return organizations

    if not is_nlp_available():
        return organizations

    entities = _entities_from_text(text)
    if not entities:
        return organizations

    org_names = _merge_org_entities(entities)
    if not org_names:
        return organizations

    recipient_line = ""
    m = re.search(r"^.*директору.*$", text[:1200], re.I | re.M)
    if m:
        recipient_line = m.group(0).lower()

    filtered = [
        n
        for n in org_names
        if not _RECIENT_HINTS.search(n)
        and (not recipient_line or normalize_org_name(n) not in recipient_line)
    ]

    if not filtered:
        return organizations

    existing = {normalize_org_name(o.name) for o in organizations}
    extra: list[OrganizationExtract] = []
    for name in filtered:
        key = normalize_org_name(name)
        if not key or key in existing:
            continue
        if "производитель" in key or "завод" in key or "ооо" in name.lower():
            extra.append(
                OrganizationExtract(
                    name=name if "«" in name else f"«{name}»",
                    org_type="manufacturer",
                    role="customer",
                    confidence=0.6,
                )
            )
            existing.add(key)

    if extra and not any(o.role == "customer" for o in organizations):
        return extra + organizations

    return organizations