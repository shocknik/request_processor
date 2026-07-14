"""
LLM-провайдер для подсказок по маркам (фаза C, Obsidian §34).

По умолчанию выключен. Реализация: локальный Ollama (без доп. зависимостей — urllib).
"""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..config import (
    ASSISTANT_LLM_BASE_URL_DEFAULT,
    ASSISTANT_LLM_ENABLED_DEFAULT,
    ASSISTANT_LLM_MODEL_DEFAULT,
    ASSISTANT_LLM_TIMEOUT_DEFAULT,
    OLLAMA_MODELS_DIR_DEFAULT,
)
from ..models import AssistantLlmSettings
from .fuzzy_match import fuzzy_snap_mark
from .models import AssistantContext, MarkSuggestion

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """Ты помощник испытательной лаборатории кабельной продукции.
Исправляй OCR-ошибки в марках кабелей: латиница → кириллица, опечатки, формат «бренд размер».
Отвечай ТОЛЬКО валидным JSON без markdown:
{"mark": "исправленная марка", "confidence": 0.85, "reason": "кратко"}
Если марка уже корректна — верни её без изменений с confidence 0.95."""


class LlmMarkProvider(Protocol):
    """Абстракция провайдера LLM для коррекции марок."""

    def suggest_mark(
        self,
        raw: str,
        *,
        context: AssistantContext | None,
        candidates: list[str],
    ) -> MarkSuggestion | None: ...


@dataclass
class OllamaHealth:
    """Результат проверки Ollama."""

    ok: bool
    message: str
    models: list[str]


def apply_ollama_env(settings: AssistantLlmSettings) -> None:
    """Прописывает OLLAMA_MODELS для хранения весов на диске D (и др.)."""
    models_dir = (settings.ollama_models_dir or "").strip()
    if models_dir:
        path = Path(models_dir)
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.warning("Не удалось создать каталог моделей %s: %s", path, exc)
        os.environ["OLLAMA_MODELS"] = str(path)


def _env_bool(name: str) -> bool | None:
    raw = os.environ.get(name)
    if raw is None:
        return None
    return raw.strip().lower() in ("1", "true", "yes", "on")


def resolve_llm_settings(stored: AssistantLlmSettings | None = None) -> AssistantLlmSettings:
    """Слияние настроек из БД с переменными окружения."""
    base = stored or AssistantLlmSettings()
    enabled = _env_bool("ASSISTANT_LLM_ENABLED")
    if enabled is not None:
        base.enabled = enabled
    if os.environ.get("ASSISTANT_LLM_MODEL"):
        base.model = os.environ["ASSISTANT_LLM_MODEL"]
    if os.environ.get("OLLAMA_HOST"):
        base.base_url = os.environ["OLLAMA_HOST"]
    elif os.environ.get("ASSISTANT_LLM_BASE_URL"):
        base.base_url = os.environ["ASSISTANT_LLM_BASE_URL"]
    if os.environ.get("OLLAMA_MODELS"):
        base.ollama_models_dir = os.environ["OLLAMA_MODELS"]
    if base.enabled and base.provider == "off":
        base.provider = "ollama"
    if not base.base_url:
        base.base_url = ASSISTANT_LLM_BASE_URL_DEFAULT
    if not base.model:
        base.model = ASSISTANT_LLM_MODEL_DEFAULT
    if not base.ollama_models_dir:
        base.ollama_models_dir = OLLAMA_MODELS_DIR_DEFAULT
    if base.timeout_seconds <= 0:
        base.timeout_seconds = ASSISTANT_LLM_TIMEOUT_DEFAULT
    return base


def default_llm_settings() -> AssistantLlmSettings:
    return resolve_llm_settings(
        AssistantLlmSettings(
            enabled=ASSISTANT_LLM_ENABLED_DEFAULT,
            model=ASSISTANT_LLM_MODEL_DEFAULT,
            base_url=ASSISTANT_LLM_BASE_URL_DEFAULT,
            ollama_models_dir=OLLAMA_MODELS_DIR_DEFAULT,
            timeout_seconds=ASSISTANT_LLM_TIMEOUT_DEFAULT,
        )
    )


def _http_json(
    url: str,
    *,
    payload: dict | None = None,
    method: str = "GET",
    timeout: float = 10.0,
) -> dict:
    data = None
    headers = {"Content-Type": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def check_ollama_health(settings: AssistantLlmSettings) -> OllamaHealth:
    """Проверка доступности Ollama и списка моделей."""
    apply_ollama_env(settings)
    url = f"{settings.base_url.rstrip('/')}/api/tags"
    try:
        data = _http_json(url, timeout=min(settings.timeout_seconds, 15.0))
        models = [m.get("name", "") for m in data.get("models", []) if m.get("name")]
        if not models:
            return OllamaHealth(
                ok=True,
                message="Ollama отвечает, но модели не загружены. Выполните: ollama pull "
                + settings.model,
                models=[],
            )
        return OllamaHealth(ok=True, message=f"Доступно моделей: {len(models)}", models=models)
    except urllib.error.URLError as exc:
        return OllamaHealth(
            ok=False,
            message=f"Ollama недоступна ({settings.base_url}): {exc.reason}",
            models=[],
        )
    except Exception as exc:  # noqa: BLE001
        return OllamaHealth(ok=False, message=str(exc), models=[])


def _extract_json_blob(text: str) -> dict | None:
    cleaned = (text or "").strip()
    if not cleaned:
        return None
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL | re.IGNORECASE)
    if fence:
        cleaned = fence.group(1)
    else:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            cleaned = cleaned[start : end + 1]
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _normalize_llm_mark(
    suggested: str,
    *,
    candidates: list[str],
    raw: str,
) -> tuple[str, float]:
    text = (suggested or "").strip()
    if not text:
        return raw, 0.0
    if candidates:
        lowered = text.lower()
        for cand in candidates:
            if cand.lower() == lowered:
                return cand, 0.95
        snap, score = fuzzy_snap_mark(text, set(candidates), min_score=0.78)
        if snap:
            return snap, min(0.94, 0.80 + score * 0.15)
    return text, 0.82


class OllamaMarkProvider:
    """Подсказки через Ollama /api/chat."""

    def __init__(self, settings: AssistantLlmSettings) -> None:
        self.settings = settings

    def suggest_mark(
        self,
        raw: str,
        *,
        context: AssistantContext | None,
        candidates: list[str],
    ) -> MarkSuggestion | None:
        raw_s = (raw or "").strip()
        if not raw_s:
            return None

        user_parts = [f"Сырая марка (OCR/ввод): {raw_s}"]
        if candidates:
            user_parts.append("Похожие марки из справочника:")
            user_parts.extend(f"- {c}" for c in candidates[:5])
        if context and context.document_text:
            snippet = context.document_text[:1200].replace("\n", " ")
            user_parts.append(f"Фрагмент документа: {snippet}")

        payload = {
            "model": self.settings.model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": "\n".join(user_parts)},
            ],
            "stream": False,
            "options": {"temperature": 0.1},
        }
        url = f"{self.settings.base_url.rstrip('/')}/api/chat"
        try:
            data = _http_json(
                url,
                payload=payload,
                method="POST",
                timeout=self.settings.timeout_seconds,
            )
            content = (data.get("message") or {}).get("content", "")
        except Exception as exc:  # noqa: BLE001
            logger.info("Ollama недоступна или ошибка запроса: %s", exc)
            return None

        parsed = _extract_json_blob(content)
        if not parsed:
            logger.debug("LLM ответ без JSON: %s", content[:200])
            return None

        mark_raw = str(parsed.get("mark", "")).strip()
        if not mark_raw:
            return None

        try:
            conf = float(parsed.get("confidence", 0.82))
        except (TypeError, ValueError):
            conf = 0.82
        conf = max(0.0, min(1.0, conf))

        mark, conf_boost = _normalize_llm_mark(mark_raw, candidates=candidates, raw=raw_s)
        conf = max(conf, conf_boost)
        reason = str(parsed.get("reason", "")).strip() or f"Ollama ({self.settings.model})"

        return MarkSuggestion(
            raw=raw,
            suggested=mark,
            confidence=conf,
            source="llm",
            reason=reason,
        )


class NullLlmProvider:
    """Заглушка при выключенном LLM."""

    def suggest_mark(
        self,
        raw: str,
        *,
        context: AssistantContext | None,
        candidates: list[str],
    ) -> MarkSuggestion | None:
        return None


def get_llm_provider(settings: AssistantLlmSettings) -> LlmMarkProvider:
    resolved = resolve_llm_settings(settings)
    if not resolved.enabled or resolved.provider == "off":
        return NullLlmProvider()
    apply_ollama_env(resolved)
    return OllamaMarkProvider(resolved)


def should_try_llm(det: MarkSuggestion, settings: AssistantLlmSettings) -> bool:
    if not resolve_llm_settings(settings).enabled:
        return False
    if not det.changed:
        return True
    return det.confidence < settings.skip_if_confidence_above


def try_llm_suggestion(
    raw: str,
    *,
    context: AssistantContext | None,
    candidates: list[str],
    settings: AssistantLlmSettings,
) -> MarkSuggestion | None:
    provider = get_llm_provider(settings)
    return provider.suggest_mark(raw, context=context, candidates=candidates)