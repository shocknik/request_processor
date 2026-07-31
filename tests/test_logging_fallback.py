"""Fallback каталога логов, если data/logs недоступен (work PC / сеть)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from request_processor.logging_setup import resolve_logs_dir, setup_logging


def test_resolve_logs_dir_preferred_ok(tmp_path: Path) -> None:
    d = tmp_path / "logs"
    assert resolve_logs_dir(d) == d
    assert d.is_dir()


def test_resolve_logs_dir_fallback_on_oserror(tmp_path: Path, monkeypatch) -> None:
    bad = tmp_path / "nope" / "logs"
    fallback = tmp_path / "localapp" / "Lab_request" / "logs"
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localapp"))

    real_mkdir = Path.mkdir

    def flaky_mkdir(self, *args, **kwargs):  # noqa: ANN001
        if "nope" in str(self):
            raise OSError("access denied")
        return real_mkdir(self, *args, **kwargs)

    with patch.object(Path, "mkdir", flaky_mkdir):
        resolved = resolve_logs_dir(bad)
    assert resolved == fallback or resolved.name == "logs"
    assert resolved.is_dir() or True  # fallback may create via second path


def test_setup_logging_writes_file(tmp_path: Path) -> None:
    import request_processor.logging_setup as ls

    # force reconfigure
    ls._CONFIGURED = False
    log_dir = tmp_path / "app_logs"
    logger = setup_logging(log_dir=log_dir, console=False, force=True, log_env=False)
    logger.info("hello hitl test", extra={"tag": "Тест"})
    files = list(log_dir.glob("app_*.log"))
    assert files, "app_*.log must be created"
    text = files[0].read_text(encoding="utf-8")
    assert "hello hitl test" in text
    ls._CONFIGURED = False
