"""
Централизованное логирование приложения.

Файлы: data/logs/app_YYYY-MM-DD.log
Уровни: DEBUG в файл, INFO+ в консоль (можно переопределить).
"""

from __future__ import annotations

import logging
import sys
from datetime import date
from pathlib import Path

from .config import LOGS_DIR

_CONFIGURED = False
LOGGER_NAME = "request_processor"


def setup_logging(
    *,
    level: int | str = logging.INFO,
    log_dir: Path | None = None,
    console: bool = True,
    force: bool = False,
) -> logging.Logger:
    """Инициализирует root-логгер пакета. Идемпотентно (если не force)."""
    global _CONFIGURED
    logger = logging.getLogger(LOGGER_NAME)
    if _CONFIGURED and not force:
        return logger

    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)

    log_dir = Path(log_dir or LOGS_DIR)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"app_{date.today().isoformat()}.log"

    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()
    logger.propagate = False

    fmt = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    if console:
        ch = logging.StreamHandler(sys.stderr)
        ch.setLevel(level)
        ch.setFormatter(fmt)
        logger.addHandler(ch)

    # Подключаем дочерние логгеры extraction/ui/…
    for name in (
        "request_processor.extraction",
        "request_processor.ui",
        "request_processor.validation",
        "request_processor.persistence",
    ):
        child = logging.getLogger(name)
        child.handlers.clear()
        child.setLevel(logging.DEBUG)
        child.propagate = True

    # extraction.pdf_extractor uses __name__ under request_processor.extraction
    logging.getLogger("request_processor").setLevel(logging.DEBUG)

    _CONFIGURED = True
    logger.info("Логирование: файл %s, console=%s", log_file, console)
    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    if not _CONFIGURED:
        setup_logging()
    if name:
        return logging.getLogger(f"{LOGGER_NAME}.{name}" if not name.startswith(LOGGER_NAME) else name)
    return logging.getLogger(LOGGER_NAME)
