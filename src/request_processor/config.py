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
DB_PATH_DEFAULT = DATA_DIR / "app.db"
TOOLS_DIR = PROJECT_ROOT / "tools"

# Алиасы для обратной совместимости (sqlite_repo, cli, gui)
GENERATED_DIR_DEFAULT = GENERATED_DIR
EXTRACTED_DIR_DEFAULT = EXTRACTED_DIR