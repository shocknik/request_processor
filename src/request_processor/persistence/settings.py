"""Настройки приложения в app_settings (климат, пакет, LLM)."""

from __future__ import annotations

import json
from pathlib import Path

from ..models import (
    AssistantLlmSettings,
    ClimaticTestSettings,
    DocumentPackSettings,
)
from .db import DB_PATH_DEFAULT, get_connection

CLIMATIC_SETTINGS_KEY = "climatic_test_hours"
DOCUMENT_PACK_SETTINGS_KEY = "document_pack_settings"
ASSISTANT_LLM_SETTINGS_KEY = "assistant_llm_settings"


def _seed_default_settings(db_path: str | Path) -> None:
    if get_climatic_settings(db_path) is not None:
        return
    save_climatic_settings(ClimaticTestSettings(), db_path)


def get_climatic_settings(db_path: str | Path = DB_PATH_DEFAULT) -> ClimaticTestSettings | None:
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT value FROM app_settings WHERE key = ?", (CLIMATIC_SETTINGS_KEY,)
        ).fetchone()
        if not row:
            return None
        return ClimaticTestSettings(**json.loads(row["value"]))


def save_climatic_settings(
    settings: ClimaticTestSettings,
    db_path: str | Path = DB_PATH_DEFAULT,
) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO app_settings (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (CLIMATIC_SETTINGS_KEY, settings.model_dump_json()),
        )


def get_document_pack_settings(
    db_path: str | Path = DB_PATH_DEFAULT,
) -> DocumentPackSettings:
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT value FROM app_settings WHERE key = ?", (DOCUMENT_PACK_SETTINGS_KEY,)
        ).fetchone()
        if not row:
            return DocumentPackSettings()
        return DocumentPackSettings(**json.loads(row["value"]))


def save_document_pack_settings(
    settings: DocumentPackSettings,
    db_path: str | Path = DB_PATH_DEFAULT,
) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO app_settings (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (DOCUMENT_PACK_SETTINGS_KEY, settings.model_dump_json()),
        )


def get_assistant_llm_settings(
    db_path: str | Path = DB_PATH_DEFAULT,
) -> AssistantLlmSettings:
    from ..assistant.llm_provider import default_llm_settings, resolve_llm_settings

    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT value FROM app_settings WHERE key = ?", (ASSISTANT_LLM_SETTINGS_KEY,)
        ).fetchone()
        if not row:
            return resolve_llm_settings(default_llm_settings())
        return resolve_llm_settings(AssistantLlmSettings(**json.loads(row["value"])))


def save_assistant_llm_settings(
    settings: AssistantLlmSettings,
    db_path: str | Path = DB_PATH_DEFAULT,
) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO app_settings (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (ASSISTANT_LLM_SETTINGS_KEY, settings.model_dump_json()),
        )
