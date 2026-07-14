"""Тесты LLM-провайдера (Ollama, mock HTTP)."""

from __future__ import annotations

import json
from unittest.mock import patch

from request_processor.assistant.llm_provider import (
    OllamaMarkProvider,
    _extract_json_blob,
    check_ollama_health,
    default_llm_settings,
    resolve_llm_settings,
    should_try_llm,
    try_llm_suggestion,
)
from request_processor.assistant.mark_corrector import suggest_mark_correction
from request_processor.assistant.models import AssistantContext, MarkSuggestion
from request_processor.models import AssistantLlmSettings
from request_processor.persistence.sqlite_repo import (
    get_assistant_llm_settings,
    init_db,
    save_assistant_llm_settings,
)


def test_extract_json_from_markdown_fence() -> None:
    blob = _extract_json_blob('```json\n{"mark": "ВВГ 3х2,5", "confidence": 0.9}\n```')
    assert blob is not None
    assert blob["mark"] == "ВВГ 3х2,5"


def test_should_try_llm_when_unchanged() -> None:
    settings = AssistantLlmSettings(enabled=True)
    det = MarkSuggestion(
        raw="XXX",
        suggested="XXX",
        confidence=0.95,
        source="deterministic",
    )
    assert should_try_llm(det, settings) is True


def test_should_skip_llm_when_confident_change() -> None:
    settings = AssistantLlmSettings(enabled=True, skip_if_confidence_above=0.92)
    det = MarkSuggestion(
        raw="KCBur",
        suggested="КСБнг",
        confidence=0.93,
        source="brand_db",
    )
    assert should_try_llm(det, settings) is False


def test_llm_disabled_returns_none() -> None:
    settings = AssistantLlmSettings(enabled=False)
    result = try_llm_suggestion(
        "KCBur(A) 3x2,5",
        context=None,
        candidates=[],
        settings=settings,
    )
    assert result is None


def test_ollama_provider_parses_chat_response() -> None:
    settings = AssistantLlmSettings(enabled=True, model="llama3.2")
    provider = OllamaMarkProvider(settings)
    payload = {
        "message": {
            "content": json.dumps(
                {
                    "mark": "КСБнг(А)-LS 3х2,5",
                    "confidence": 0.88,
                    "reason": "латиница→кириллица",
                },
                ensure_ascii=False,
            )
        }
    }

    with patch(
        "request_processor.assistant.llm_provider._http_json",
        return_value=payload,
    ):
        result = provider.suggest_mark(
            "KCBur(A)-LS 3x2,5",
            context=AssistantContext(),
            candidates=["КСБнг(А)-LS 3х2,5"],
        )

    assert result is not None
    assert result.source == "llm"
    assert "КСБ" in result.suggested
    assert result.changed


def test_check_ollama_health_lists_models() -> None:
    settings = default_llm_settings()
    with patch(
        "request_processor.assistant.llm_provider._http_json",
        return_value={"models": [{"name": "llama3.2:latest"}]},
    ):
        health = check_ollama_health(settings)
    assert health.ok
    assert "llama3.2:latest" in health.models


def test_mark_corrector_uses_llm_when_enabled(tmp_path) -> None:
    db = tmp_path / "llm.db"
    init_db(db)
    save_assistant_llm_settings(AssistantLlmSettings(enabled=True, model="llama3.2"), db)

    llm_suggestion = MarkSuggestion(
        raw="KCBur(A)-LS 3x2,5",
        suggested="КСБнг(А)-LS 3х2,5",
        confidence=0.9,
        source="llm",
        reason="test llm",
    )

    with patch(
        "request_processor.assistant.mark_corrector.try_llm_suggestion",
        return_value=llm_suggestion,
    ):
        result = suggest_mark_correction("KCBur(A)-LS 3x2,5", db_path=db)

    assert result.source == "llm"
    assert result.changed


def test_settings_persist_in_db(tmp_path) -> None:
    db = tmp_path / "s.db"
    init_db(db)
    save_assistant_llm_settings(
        AssistantLlmSettings(enabled=True, model="mistral", ollama_models_dir="D:/ollama/models"),
        db,
    )
    loaded = get_assistant_llm_settings(db)
    assert loaded.enabled is True
    assert loaded.model == "mistral"
    assert loaded.ollama_models_dir.replace("\\", "/") == "D:/ollama/models"


def test_env_overrides_enabled(monkeypatch) -> None:
    monkeypatch.setenv("ASSISTANT_LLM_ENABLED", "1")
    monkeypatch.setenv("ASSISTANT_LLM_MODEL", "qwen2.5")
    resolved = resolve_llm_settings(AssistantLlmSettings(enabled=False))
    assert resolved.enabled is True
    assert resolved.model == "qwen2.5"