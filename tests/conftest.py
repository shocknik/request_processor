"""Общие фикстуры pytest + запись сессии в data/logs/tests_YYYY-MM-DD.log."""

from __future__ import annotations

import logging

import pytest

from request_processor.logging_setup import get_logger, setup_test_logging


def pytest_configure(config: pytest.Config) -> None:
    """Старт pytest: отдельный файл tests_*.log + banner в app_*.log."""
    path = setup_test_logging()
    log = get_logger("tests")
    log.info(
        "pytest configure rootdir=%s",
        config.rootpath,
        extra={"tag": "Тесты"},
    )
    # config.option may not have verbose always
    try:
        log.info(
            "pytest args verbose=%s file_or_dir=%s",
            getattr(config.option, "verbose", None),
            getattr(config.option, "file_or_dir", None),
            extra={"tag": "Тесты"},
        )
    except Exception:
        pass
    config._rp_tests_log = path  # type: ignore[attr-defined]


def pytest_sessionstart(session: pytest.Session) -> None:
    log = get_logger("tests")
    log.info(
        "session start collected will run under %s",
        session.config.rootpath,
        extra={"tag": "Тесты"},
    )


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    """Пишем результат каждого теста (call phase) в tests_*.log."""
    if report.when != "call" and not (report.when == "setup" and report.failed):
        return
    log = get_logger("tests")
    outcome = report.outcome  # passed / failed / skipped
    level = logging.INFO
    if outcome == "failed":
        level = logging.ERROR
    elif outcome == "skipped":
        level = logging.WARNING
    msg = f"{outcome.upper():7} {report.nodeid} ({report.duration:.2f}s)"
    log.log(level, msg, extra={"tag": "Тесты"})
    if report.failed and report.longrepr:
        # longrepr может быть длинным — обрежем для читаемости
        text = str(report.longrepr)
        if len(text) > 4000:
            text = text[:4000] + "\n...[truncated]..."
        log.error("failure detail:\n%s", text, extra={"tag": "Тесты"})


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    log = get_logger("tests")
    log.info(
        "session finish exitstatus=%s",
        exitstatus,
        extra={"tag": "Тесты"},
    )
    path = getattr(session.config, "_rp_tests_log", None)
    if path:
        log.info("tests log file: %s", path, extra={"tag": "Тесты"})
