"""
Централизованное логирование приложения.

Файлы:
  data/logs/app_YYYY-MM-DD.log           — основной (рядом с установкой)
  %LOCALAPPDATA%/Lab_request/logs/…      — зеркало (важно для work / сеть W:)
  data/logs/scripts_YYYY-MM-DD.log       — install / update (PS1)
  data/logs/tests_YYYY-MM-DD.log         — pytest

Уровни: DEBUG в файл(ы), INFO+ в консоль (если не pythonw).
На рабочем ПК ярлык = pythonw → консоли нет, всё смотрим в файле.

Необработанные исключения — в app_*.log.
"""

from __future__ import annotations

import logging
import os
import platform
import re
import socket
import sys
import traceback
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .config import LOGS_DIR, PROJECT_ROOT

_CONFIGURED = False
_EXCEPTHOOK_INSTALLED = False
LOGGER_NAME = "request_processor"

# Активные пути app-логов (после setup_logging)
_ACTIVE_LOG_FILES: list[Path] = []
_ACTIVE_LOG_DIRS: list[Path] = []

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


class FlushFileHandler(logging.FileHandler):
    """FileHandler с flush после каждой записи (сеть W: / pythonw / crash)."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            super().emit(record)
            self.flush()
        except Exception:
            self.handleError(record)


def _user_log_fallback_dir() -> Path:
    """Локальный каталог логов (всегда доступен на work, даже если W: отвалился)."""
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("TEMP") or str(Path.home())
    return Path(base) / "Lab_request" / "logs"


def resolve_logs_dir(preferred: Path | None = None) -> Path:
    """Каталог основной записи: data/logs или fallback LOCALAPPDATA."""
    preferred = Path(preferred or LOGS_DIR)
    try:
        preferred.mkdir(parents=True, exist_ok=True)
        probe = preferred / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return preferred
    except OSError:
        fallback = _user_log_fallback_dir()
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def _resolve_app_log_paths(preferred_dir: Path | None = None) -> tuple[Path, Path]:
    """(log_dir, log_file) для app_YYYY-MM-DD.log (основной)."""
    log_dir = resolve_logs_dir(preferred_dir)
    return log_dir, log_dir / f"app_{date.today().isoformat()}.log"


def log_path_for(kind: str = "app", day: date | None = None) -> Path:
    """Путь к файлу лога: app | scripts | tests."""
    d = day or date.today()
    prefix = {"app": "app", "scripts": "scripts", "tests": "tests"}.get(kind, kind)
    if kind == "app":
        files = get_active_log_files()
        if files:
            return files[0]
        return resolve_logs_dir() / f"{prefix}_{d.isoformat()}.log"
    return Path(LOGS_DIR) / f"{prefix}_{d.isoformat()}.log"


def _ensure_logs_dir() -> Path:
    return resolve_logs_dir()


def get_active_log_files() -> list[Path]:
    """Список app-файлов, куда сейчас пишем (основной + зеркало)."""
    return list(_ACTIVE_LOG_FILES)


def get_active_log_dirs() -> list[Path]:
    return list(_ACTIVE_LOG_DIRS)


def is_pythonw() -> bool:
    exe = (sys.executable or "").lower().replace("\\", "/")
    return exe.endswith("pythonw.exe") or "pythonw" in Path(exe).name.lower()


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
    path = log_path_for(kind) if kind != "app" else (
        resolve_logs_dir() / f"app_{date.today().isoformat()}.log"
    )
    if kind == "app":
        path = resolve_logs_dir() / f"app_{date.today().isoformat()}.log"
    else:
        path = Path(LOGS_DIR) / f"{kind}_{date.today().isoformat()}.log"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            path = _user_log_fallback_dir() / f"{kind}_{date.today().isoformat()}.log"
            path.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{ts} | {level:<7} | {source} | [-] {message}\n"
    with path.open("a", encoding="utf-8") as f:
        f.write(line)
        f.flush()
    return path


def log_operator(
    message: str,
    *args: object,
    tag: str = "Оператор",
    level: int = logging.INFO,
    **fields: object,
) -> None:
    """
    Явный след действий оператора (всегда INFO → в файл на work).

    Пример::
        log_operator("confirm customer=%r marks=%s", name, n, tag="Заявка")
    """
    log = get_logger()
    if fields:
        extra_bits = " ".join(f"{k}={v!r}" for k, v in fields.items())
        if args:
            msg = (message % args) if args else message
            message = f"{msg} | {extra_bits}"
            args = ()
        else:
            message = f"{message} | {extra_bits}"
    log.log(level, message, *args, extra={"tag": tag})


def log_environment(logger: logging.Logger | None = None) -> None:
    """Снимок окружения — полезно при разборе логов с рабочего ПК."""
    log = logger or get_logger()
    try:
        import request_processor as rp

        ver = getattr(rp, "__version__", "?")
    except Exception:
        ver = "?"
    extra = {"tag": "Окружение"}
    log.info("======== SESSION ENVIRONMENT ========", extra=extra)
    log.info("python=%s", sys.version.replace("\n", " "), extra=extra)
    log.info("executable=%s", sys.executable, extra=extra)
    log.info("pythonw=%s", is_pythonw(), extra=extra)
    log.info("platform=%s", platform.platform(), extra=extra)
    log.info("hostname=%s", socket.gethostname(), extra=extra)
    log.info(
        "user=%s",
        os.environ.get("USERNAME") or os.environ.get("USER") or "-",
        extra=extra,
    )
    log.info("cwd=%s", Path.cwd(), extra=extra)
    log.info("PROJECT_ROOT=%s", PROJECT_ROOT, extra=extra)
    log.info("package_version=%s", ver, extra=extra)
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
    for i, p in enumerate(get_active_log_files()):
        log.info("log_file[%s]=%s", i, p, extra=extra)
    for i, d in enumerate(get_active_log_dirs()):
        log.info("log_dir[%s]=%s", i, d, extra=extra)
    log.info("======== END ENVIRONMENT ========", extra=extra)


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
        logger.critical(
            "traceback:\n%s",
            "".join(traceback.format_exception(exc_type, exc, tb)),
            extra={"tag": "Crash"},
        )
        # сбросить буферы на диск
        for h in logger.handlers:
            try:
                h.flush()
            except Exception:
                pass
        prev(exc_type, exc, tb)

    sys.excepthook = _hook
    _EXCEPTHOOK_INSTALLED = True


def _try_add_file_handler(
    logger: logging.Logger,
    log_file: Path,
    *,
    fmt: logging.Formatter,
    tag_filter: logging.Filter,
    label: str,
) -> Path | None:
    """Добавить FlushFileHandler; None если не удалось."""
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        fh = FlushFileHandler(log_file, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)
        fh.addFilter(tag_filter)
        fh._rp_label = label  # type: ignore[attr-defined]
        logger.addHandler(fh)
        # пробная запись
        with log_file.open("a", encoding="utf-8") as f:
            f.write("")
            f.flush()
        return log_file
    except OSError as exc:
        # не логируем через logger (ещё не готов) — stderr
        try:
            sys.stderr.write(f"log file open failed ({label}): {log_file}: {exc}\n")
        except Exception:
            pass
        return None


def setup_logging(
    *,
    level: int | str = logging.INFO,
    log_dir: Path | None = None,
    console: bool = True,
    force: bool = False,
    log_env: bool = True,
    mirror_local: bool | None = None,
) -> logging.Logger:
    """
    Инициализирует root-логгер пакета.

    Пишет:
      1) data/logs/app_*.log (или fallback, если сеть недоступна)
      2) всегда зеркало в %LOCALAPPDATA%\\Lab_request\\logs (если путь другой)

    ``mirror_local=False`` или env REQUEST_PROCESSOR_LOG_MIRROR=0 — без зеркала.
    """
    global _CONFIGURED, _ACTIVE_LOG_FILES, _ACTIVE_LOG_DIRS
    logger = logging.getLogger(LOGGER_NAME)
    if _CONFIGURED and not force:
        return logger

    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)

    env_level = os.environ.get("REQUEST_PROCESSOR_LOG", "").strip().upper()
    if env_level in ("DEBUG", "INFO", "WARNING", "ERROR"):
        level = getattr(logging, env_level)

    # pythonw: консоль бесполезна
    if console and is_pythonw():
        console = False

    preferred_dir = Path(log_dir or LOGS_DIR)
    primary_dir, primary_file = _resolve_app_log_paths(preferred_dir)

    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()
    logger.propagate = False

    fmt = _make_formatter()
    tag_filter = _TagFilter()
    active_files: list[Path] = []
    active_dirs: list[Path] = []

    p = _try_add_file_handler(
        logger, primary_file, fmt=fmt, tag_filter=tag_filter, label="primary"
    )
    if p is None:
        # только LOCALAPPDATA
        fb = _user_log_fallback_dir() / f"app_{date.today().isoformat()}.log"
        p = _try_add_file_handler(
            logger, fb, fmt=fmt, tag_filter=tag_filter, label="fallback"
        )
        if p is not None:
            active_files.append(p)
            active_dirs.append(p.parent)
    else:
        active_files.append(p)
        active_dirs.append(p.parent)

    # Зеркало: всегда пишем ещё и локально на work (pythonw + сеть)
    if mirror_local is None:
        mirror_env = os.environ.get("REQUEST_PROCESSOR_LOG_MIRROR", "1").strip()
        mirror_local = mirror_env not in ("0", "false", "no", "off")
    if mirror_local and active_files:
        mirror_dir = _user_log_fallback_dir()
        mirror_file = mirror_dir / f"app_{date.today().isoformat()}.log"
        try:
            same = mirror_file.resolve() == active_files[0].resolve()
        except OSError:
            same = str(mirror_file) == str(active_files[0])
        if not same:
            m = _try_add_file_handler(
                logger, mirror_file, fmt=fmt, tag_filter=tag_filter, label="mirror"
            )
            if m is not None:
                active_files.append(m)
                active_dirs.append(m.parent)

    _ACTIVE_LOG_FILES = active_files
    _ACTIVE_LOG_DIRS = active_dirs

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

    for noisy in ("PIL", "urllib3", "openai", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _CONFIGURED = True

    files_s = ", ".join(str(f) for f in active_files) or "(нет файла!)"
    logger.info(
        "======== Lab_request LOG SESSION START %s ========",
        datetime.now().isoformat(timespec="seconds"),
        extra={"tag": "Лог"},
    )
    logger.info(
        "Логирование: files=[%s] console=%s file_level=DEBUG console_level=%s pythonw=%s",
        files_s,
        console,
        logging.getLevelName(level) if isinstance(level, int) else level,
        is_pythonw(),
        extra={"tag": "Лог"},
    )
    if len(active_files) > 1:
        logger.info(
            "Зеркало логов: пишем и в установку, и в %%LOCALAPPDATA%%\\Lab_request\\logs "
            "(чтобы на work всегда было что снять)",
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
    try:
        path = Path(LOGS_DIR) / f"tests_{date.today().isoformat()}.log"
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        path = _user_log_fallback_dir() / f"tests_{date.today().isoformat()}.log"
        path.parent.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger("request_processor")
    if not _CONFIGURED:
        setup_logging(console=False, log_env=False, force=True, mirror_local=False)

    fmt = _make_formatter()
    tag_filter = _TagFilter()
    for h in list(root.handlers):
        if getattr(h, "_rp_tests_handler", False):
            return path
    fh = FlushFileHandler(path, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    fh.addFilter(tag_filter)
    fh._rp_tests_handler = True  # type: ignore[attr-defined]
    root.addHandler(fh)
    root.info("=== pytest session log → %s ===", path, extra={"tag": "Тесты"})
    return path
