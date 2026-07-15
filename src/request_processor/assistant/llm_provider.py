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
    """Прописывает OLLAMA_MODELS, если в настройках задан каталог моделей.

    По умолчанию Ollama уже использует %USERPROFILE%\\.ollama\\models —
    тогда переменную можно не трогать. Задавайте каталог явно, только
    если модели лежат в нестандартном месте.
    """
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


def normalize_ollama_base_url(url: str | None) -> str:
    """http://127.0.0.1:11434 — без схемы/слэшей, как в GUI."""
    raw = (url or "").strip().rstrip("/")
    if not raw:
        return ASSISTANT_LLM_BASE_URL_DEFAULT.rstrip("/")
    if not raw.startswith(("http://", "https://")):
        raw = "http://" + raw
    return raw.rstrip("/")


def _is_local_url(url: str) -> bool:
    low = url.lower()
    return any(
        host in low
        for host in (
            "://127.0.0.1",
            "://localhost",
            "://[::1]",
            "://0.0.0.0",
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
    # Системный HTTP(S)_PROXY часто ломает запросы к localhost/127.0.0.1.
    if _is_local_url(url):
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def find_ollama_executable() -> Path | None:
    """Путь к ollama.exe / ollama, если установлен (даже когда API не поднят)."""
    import shutil
    import sys

    which = shutil.which("ollama")
    if which:
        return Path(which)
    candidates: list[Path] = []
    local = os.environ.get("LOCALAPPDATA", "")
    user = os.environ.get("USERPROFILE", "")
    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    for base in (
        Path(local) / "Programs" / "Ollama" if local else None,
        Path(user) / "AppData" / "Local" / "Programs" / "Ollama" if user else None,
        Path(program_files) / "Ollama",
        Path(r"C:\Program Files\Ollama"),
        Path(r"D:\Ollama"),
        Path(r"D:\ollama"),
    ):
        if base is None:
            continue
        candidates.append(base / ("ollama.exe" if sys.platform == "win32" else "ollama"))
    for path in candidates:
        if path.is_file():
            return path
    return None


def try_start_ollama_server(*, wait_seconds: float = 8.0) -> tuple[bool, str]:
    """
    Пытается поднять API (ollama serve), если бинарник есть, а /api/tags молчит.
    Возвращает (started_or_already_up, message).
    """
    import subprocess
    import sys
    import time

    exe = find_ollama_executable()
    if exe is None:
        return False, "Исполняемый файл ollama не найден в PATH и стандартных папках."

    # Уже отвечает?
    try:
        _http_json("http://127.0.0.1:11434/api/tags", timeout=2.0)
        return True, "Сервер уже отвечает."
    except Exception:
        pass

    creationflags = 0
    if sys.platform == "win32":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(
            subprocess, "DETACHED_PROCESS", 0
        )
    try:
        subprocess.Popen(  # noqa: S603
            [str(exe), "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
            close_fds=True,
        )
    except OSError as exc:
        return False, f"Не удалось запустить «{exe} serve»: {exc}"

    deadline = time.time() + max(1.0, wait_seconds)
    while time.time() < deadline:
        try:
            _http_json("http://127.0.0.1:11434/api/tags", timeout=1.5)
            return True, f"Запущен через «{exe} serve»."
        except Exception:
            time.sleep(0.4)
    return False, (
        f"Запущен «{exe} serve», но API за {wait_seconds:.0f} с не ответил. "
        "Откройте приложение Ollama из меню Пуск."
    )


def check_ollama_health(
    settings: AssistantLlmSettings,
    *,
    try_start: bool = True,
) -> OllamaHealth:
    """Проверка доступности Ollama и списка моделей."""
    apply_ollama_env(settings)
    base = normalize_ollama_base_url(settings.base_url)
    timeout = min(float(settings.timeout_seconds or 15), 15.0)

    # Несколько URL: GUI/env могут отличаться; 127.0.0.1 vs localhost.
    urls: list[str] = [f"{base}/api/tags"]
    if "127.0.0.1" in base:
        urls.append(base.replace("127.0.0.1", "localhost") + "/api/tags")
    elif "localhost" in base:
        urls.append(base.replace("localhost", "127.0.0.1") + "/api/tags")
    # Уникальные, порядок сохраняем
    seen: set[str] = set()
    uniq_urls: list[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            uniq_urls.append(u)

    last_error: str = ""
    for url in uniq_urls:
        try:
            data = _http_json(url, timeout=timeout)
            models = [m.get("name", "") for m in data.get("models", []) if m.get("name")]
            if not models:
                return OllamaHealth(
                    ok=True,
                    message=(
                        f"Ollama отвечает ({url.rsplit('/api', 1)[0]}), "
                        f"но модели не загружены. Выполните: ollama pull {settings.model}"
                    ),
                    models=[],
                )
            return OllamaHealth(
                ok=True,
                message=f"Ollama OK · моделей: {len(models)}",
                models=models,
            )
        except urllib.error.URLError as exc:
            last_error = str(exc.reason or exc)
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)

    start_note = ""
    if try_start and _is_local_url(base):
        started, start_msg = try_start_ollama_server()
        start_note = f"\n\nАвтозапуск: {start_msg}"
        if started:
            for url in uniq_urls:
                try:
                    data = _http_json(url, timeout=timeout)
                    models = [
                        m.get("name", "") for m in data.get("models", []) if m.get("name")
                    ]
                    return OllamaHealth(
                        ok=True,
                        message=f"Ollama OK (после автозапуска) · моделей: {len(models)}",
                        models=models,
                    )
                except Exception as exc:  # noqa: BLE001
                    last_error = str(exc)

    exe = find_ollama_executable()
    exe_line = f"\nБинарник: {exe}" if exe else "\nБинарник ollama: не найден (PATH / Program Files)."
    models_dir = (settings.ollama_models_dir or "").strip()
    dir_line = f"\nКаталог моделей: {models_dir}" if models_dir else ""
    return OllamaHealth(
        ok=False,
        message=(
            f"Ollama API недоступен ({base}).\n"
            f"Причина: {last_error or 'нет ответа'}"
            f"{exe_line}{dir_line}{start_note}\n\n"
            "Что сделать:\n"
            "1) Запустите приложение Ollama (иконка в трее) или: ollama serve\n"
            "2) Проверьте URL (по умолчанию http://127.0.0.1:11434)\n"
            "3) При необходимости: ollama pull " + (settings.model or "llama3.2")
        ),
        models=[],
    )


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