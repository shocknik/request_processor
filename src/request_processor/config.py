"""
Пути и константы проекта (единая точка конфигурации).
"""

from __future__ import annotations

import os
from pathlib import Path

# Корень репозитория (на уровень выше src/)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
TEMPLATES_DIR = DATA_DIR / "templates"
GENERATED_DIR = DATA_DIR / "generated"
EXTRACTED_DIR = DATA_DIR / "extracted"
OCR_CACHE_DIR = DATA_DIR / "ocr_cache"
LOGS_DIR = DATA_DIR / "logs"
PARSE_SNAPSHOTS_DIR = DATA_DIR / "parse_snapshots"
TRAINING_DIR = DATA_DIR / "training"
FAMILIES_DIR = DATA_DIR / "families"
RAG_CORPUS_DIR = TRAINING_DIR / "rag_corpus"
TRAINING_INBOX = TRAINING_DIR / "documents" / "inbox"
TRAINING_REGISTERED = TRAINING_DIR / "documents" / "registered"
TRAINING_CORRECTIONS_DIR = TRAINING_DIR / "corrections"
# Создаём каталог при импорте конфигурации (безопасно, если data/ есть)
try:
    TRAINING_CORRECTIONS_DIR.mkdir(parents=True, exist_ok=True)
except OSError:
    pass
TRAINING_LABELS_DIR = TRAINING_DIR / "labels"
TRAINING_LABELS_MARKS_DIR = TRAINING_LABELS_DIR / "marks"
TRAINING_EXPORTS_REPORTS_DIR = TRAINING_DIR / "exports" / "reports"
DB_PATH_DEFAULT = DATA_DIR / "app.db"
TOOLS_DIR = PROJECT_ROOT / "tools"

# Расчёт (шаблон прайса Obsidian §39)
VAT_RATE = 0.22
MINIMUM_ORDER_CODE = "базовая_стоимость"
SAMPLE_PREP_CODE = "базовая_подготовка_образцов"

# Шаблоны документов (заявка, протокол испытаний)
PROTOCOL_TEMPLATE_NAME = "Форма Протокола испытаний (2025).docx"

# Алиасы для обратной совместимости (sqlite_repo, cli, gui)
GENERATED_DIR_DEFAULT = GENERATED_DIR
EXTRACTED_DIR_DEFAULT = EXTRACTED_DIR

# ИИ-ассистент (LLM, Obsidian §34 фаза C) — по умолчанию выключен
ASSISTANT_LLM_ENABLED_DEFAULT = False
ASSISTANT_LLM_BASE_URL_DEFAULT = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
ASSISTANT_LLM_MODEL_DEFAULT = os.environ.get("ASSISTANT_LLM_MODEL", "llama3.2")
# Стандартный каталог Ollama на Windows: %USERPROFILE%\.ollama\models
# (напр. C:\Users\User\.ollama\models). Перекрывается OLLAMA_MODELS.
_OLLAMA_MODELS_FALLBACK = str(Path.home() / ".ollama" / "models")
OLLAMA_MODELS_DIR_DEFAULT = os.environ.get("OLLAMA_MODELS", _OLLAMA_MODELS_FALLBACK)
ASSISTANT_LLM_TIMEOUT_DEFAULT = float(os.environ.get("ASSISTANT_LLM_TIMEOUT", "60"))
ASSISTANT_LLM_SKIP_ABOVE_CONFIDENCE = 0.92