"""
Централизованное логирование приложения.

Файлы в data/logs/:
  app_YYYY-MM-DD.log      — GUI / CLI / runtime
  scripts_YYYY-MM-DD.log  — install / update / shortcut (PS1)
  tests_YYYY-MM-DD.log    — pytest session

Уровни: DEBUG в файл, INFO+ в консоль (можно переопределить).
Необработанные исключения пишутся в app_*.log автоматически.
"""

from __future__ import annotations

import logging
import os
import platform
import re
import sys
import traceback
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .config import LOGS_DIR, PROJECT_ROOT

_CONFIGURED = False
_EXCEPTHOOK_INSTALLED = False
LOGGER_NAME = "request_processor"

# Дочерние пакеты — всё под request_processor.* уходит в один файл
_CHILD_PACKAGES = (
    "request_processor.extraction",
    "request_processor.ui",
    "request_processor.validation",
    "request_processor.persistence",
    "request_processor.calculation",
    "request_processor.generation",
    "request_processor.mapping",
    "request_processor.assistant",
    "request_processor.training",
    "request_processor.parsing",
    "request_processor.nlp",
    "request_processor.parse_compare",
    "request_processor.cli",
    "request_processor.knowledge",
)


def log_path_for(kind: str = "app", day: date | None = None) -> Path:
    """Путь к файлу лога: app | scripts | tests."""
    d = day or date.today()
    prefix = {"app": "app", "scripts": "scripts", "tests": "tests"}.get(kind, kind)
    return Path(LOGS_DIR) / f"{prefix}_{d.isoformat()}.log"


def _ensure_logs_dir() -> Path:
    p = Path(LOGS_DIR)
    p.mkdir(parents=True, exist_ok=True)
    return p


class _TagFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "tag"):
            record.tag = "-"  # type: ignore[attr-defined]
        return True


def _make_formatter() -> logging.Formatter:
    return logging.Formatter(
        fmt="%(asctime)s | %(levelname)-7s | %(name)s | [%(tag)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def append_ops_log(
    message: str,
    *,
    kind: str = "scripts",
    level: str = "INFO",
    source: str = "ops",
) -> Path:
    """
    Простая запись в data/logs/{kind}_YYYY-MM-DD.log без полной настройки logging.
    Для PS1/bat через python -c, либо из Python-скриптов ops.
    """
    path = log_path_for(kind)
    _ensure_logs_dir()
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{ts} | {level:<7} | {source} | [-] {message}\n"
    with path.open("a", encoding="utf-8") as f:
        f.write(line)
    return path


def log_environment(logger: logging.Logger | None = None) -> None:
    """Снимок окружения — полезно при разборе логов с рабочего ПК."""
    log = logger or get_logger()
    try:
        import request_processor as rp

        ver = getattr(rp, "__version__", "?")
    except Exception:
        ver = "?"
    extra = {"tag": "Окружение"}
    log.info("python=%s", sys.version.replace("\n", " "), extra=extra)
    log.info("executable=%s", sys.executable, extra=extra)
    log.info("platform=%s", platform.platform(), extra=extra)
    log.info("cwd=%s", Path.cwd(), extra=extra)
    log.info("PROJECT_ROOT=%s", PROJECT_ROOT, extra=extra)
    log.info("package_version=%s", ver, extra=extra)
    # D7: stale egg-info (0.8.x) при pyproject 0.9.x — не путать с source_sha
    try:
        pp = PROJECT_ROOT / "pyproject.toml"
        if pp.is_file():
            text = pp.read_text(encoding="utf-8")
            m = re.search(r'(?m)^version\s*=\s*["\']([^"\']+)["\']', text)
            if m:
                src_ver = m.group(1)
                log.info("pyproject_version=%s", src_ver, extra=extra)
                if ver not in ("?", "0.0.0-dev") and src_ver != ver:
                    log.warning(
                        "version mismatch: package=%s pyproject=%s "
                        "→ на dev: pip install -e .",
                        ver,
                        src_ver,
                        extra=extra,
                    )
    except Exception:
        pass
    log.info(
        "env LANG=%s PYTHONUTF8=%s REQUEST_PROCESSOR_LOG=%s",
        os.environ.get("LANG") or os.environ.get("LC_ALL") or "-",
        os.environ.get("PYTHONUTF8", "-"),
        os.environ.get("REQUEST_PROCESSOR_LOG", "-"),
        extra=extra,
    )


def _install_excepthook(logger: logging.Logger) -> None:
    global _EXCEPTHOOK_INSTALLED
    if _EXCEPTHOOK_INSTALLED:
        return
    prev = sys.excepthook

    def _hook(exc_type: type[BaseException], exc: BaseException, tb: Any) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            prev(exc_type, exc, tb)
            return
        logger.critical(
            "Необработанное исключение: %s: %s",
            exc_type.__name__,
            exc,
            exc_info=(exc_type, exc, tb),
            extra={"tag": "Crash"},
        )
        # traceback уже в exc_info; дополнительно одной строкой для поиска
        logger.critical(
            "traceback:\n%s",
            "".join(traceback.format_exception(exc_type, exc, tb)),
            extra={"tag": "Crash"},
        )
        prev(exc_type, exc, tb)

    sys.excepthook = _hook
    _EXCEPTHOOK_INSTALLED = True


def setup_logging(
    *,
    level: int | str = logging.INFO,
    log_dir: Path | None = None,
    console: bool = True,
    force: bool = False,
    log_env: bool = True,
) -> logging.Logger:
    """Инициализирует root-логгер пакета. Идемпотентно (если не force)."""
    global _CONFIGURED
    logger = logging.getLogger(LOGGER_NAME)
    if _CONFIGURED and not force:
        return logger

    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)

    # REQUEST_PROCESSOR_LOG=DEBUG — больше в консоль с рабочего ПК
    env_level = os.environ.get("REQUEST_PROCESSOR_LOG", "").strip().upper()
    if env_level in ("DEBUG", "INFO", "WARNING", "ERROR"):
        level = getattr(logging, env_level)

    log_dir = Path(log_dir or LOGS_DIR)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"app_{date.today().isoformat()}.log"

    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()
    logger.propagate = False

    fmt = _make_formatter()
    tag_filter = _TagFilter()

    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    fh.addFilter(tag_filter)
    logger.addHandler(fh)

    if console:
        ch = logging.StreamHandler(sys.stderr)
        ch.setLevel(level)
        ch.setFormatter(fmt)
        ch.addFilter(tag_filter)
        logger.addHandler(ch)

    for name in _CHILD_PACKAGES:
        child = logging.getLogger(name)
        child.handlers.clear()
        child.setLevel(logging.DEBUG)
        child.propagate = True

    logging.getLogger("request_processor").setLevel(logging.DEBUG)

    # Не засорять DEBUG сторонними lib, но WARNING+ — в наш handler через root? нет, propagate only our tree
    for noisy in ("PIL", "urllib3", "openai", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _CONFIGURED = True
    logger.info(
        "Логирование: файл %s, console=%s, file_level=DEBUG, console_level=%s",
        log_file,
        console,
        logging.getLevelName(level) if isinstance(level, int) else level,
        extra={"tag": "Лог"},
    )
    _install_excepthook(logger)
    if log_env:
        log_environment(logger)
    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    if not _CONFIGURED:
        setup_logging()
    if name:
        return logging.getLogger(
            f"{LOGGER_NAME}.{name}" if not name.startswith(LOGGER_NAME) else name
        )
    return logging.getLogger(LOGGER_NAME)


def setup_test_logging() -> Path:
    """Отдельный файл для pytest: data/logs/tests_YYYY-MM-DD.log."""
    path = log_path_for("tests")
    _ensure_logs_dir()
    root = logging.getLogger("request_processor")
    # Если app-лог ещё не настроен — настроим без console env spam в pytest
    if not _CONFIGURED:
        setup_logging(console=False, log_env=False, force=True)

    # Доп. handler только для tests_* (чтобы pytest-сессия была отдельным файлом)
    fmt = _make_formatter()
    tag_filter = _TagFilter()
    # не дублировать тот же путь
    for h in list(root.handlers):
        if getattr(h, "_rp_tests_handler", False):
            return path
    fh = logging.FileHandler(path, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    fh.addFilter(tag_filter)
    fh._rp_tests_handler = True  # type: ignore[attr-defined]
    root.addHandler(fh)
    root.info("=== pytest session log → %s ===", path, extra={"tag": "Тесты"})
    return path
