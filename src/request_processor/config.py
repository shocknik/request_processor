"""
Пути и константы проекта (единая точка конфигурации).
"""

from __future__ import annotations

from pathlib import Path

# Корень репозитория (на уровень выше src/)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
TEMPLATES_DIR = DATA_DIR / "templates"
GENERATED_DIR = DATA_DIR / "generated"
EXTRACTED_DIR = DATA_DIR / "extracted"
OCR_CACHE_DIR = DATA_DIR / "ocr_cache"
TRAINING_DIR = DATA_DIR / "training"
FAMILIES_DIR = DATA_DIR / "families"
RAG_CORPUS_DIR = TRAINING_DIR / "rag_corpus"
TRAINING_INBOX = TRAINING_DIR / "documents" / "inbox"
TRAINING_REGISTERED = TRAINING_DIR / "documents" / "registered"
TRAINING_CORRECTIONS_DIR = TRAINING_DIR / "corrections"
TRAINING_LABELS_DIR = TRAINING_DIR / "labels"
TRAINING_LABELS_MARKS_DIR = TRAINING_LABELS_DIR / "marks"
TRAINING_EXPORTS_REPORTS_DIR = TRAINING_DIR / "exports" / "reports"
DB_PATH_DEFAULT = DATA_DIR / "app.db"
TOOLS_DIR = PROJECT_ROOT / "tools"

# Шаблоны документов (заявка, протокол испытаний)
PROTOCOL_TEMPLATE_NAME = "Форма Протокола испытаний (2025).docx"

# Алиасы для обратной совместимости (sqlite_repo, cli, gui)
GENERATED_DIR_DEFAULT = GENERATED_DIR
EXTRACTED_DIR_DEFAULT = EXTRACTED_DIR