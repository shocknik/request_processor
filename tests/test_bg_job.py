"""Unit tests for ui.bg_job (no mainloop required)."""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest

from request_processor.ui.bg_job import run_bg_job, schedule_ui


class _FakeRoot:
    """Minimal root: after(0) runs callback immediately (test harness)."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def after(self, _ms: int, callback: Any) -> str:
        callback()
        return "after-1"


def test_schedule_ui_runs_callback() -> None:
    root = _FakeRoot()
    seen: list[int] = []
    assert schedule_ui(root, lambda: seen.append(1), tag="Test") is True
    assert seen == [1]


def test_schedule_ui_no_after() -> None:
    assert schedule_ui(object(), lambda: None) is False


def test_run_bg_job_success() -> None:
    root = _FakeRoot()
    done = threading.Event()
    out: list[int] = []

    def work() -> int:
        return 42

    def on_ok(value: int) -> None:
        out.append(value)
        done.set()

    run_bg_job(root, work, on_success=on_ok, name="t", tag="Test")
    assert done.wait(timeout=2.0)
    assert out == [42]


def test_run_bg_job_error() -> None:
    root = _FakeRoot()
    done = threading.Event()
    errs: list[str] = []

    def work() -> int:
        raise ValueError("boom")

    def on_ok(_value: int) -> None:
        pytest.fail("on_success must not run")

    def on_err(exc: BaseException) -> None:
        errs.append(str(exc))
        done.set()

    run_bg_job(root, work, on_success=on_ok, on_error=on_err, name="t", tag="Test")
    assert done.wait(timeout=2.0)
    assert errs == ["boom"]


def test_run_bg_job_error_without_handler() -> None:
    root = _FakeRoot()
    started = threading.Event()

    def work() -> None:
        started.set()
        raise RuntimeError("silent")

    thr = run_bg_job(root, work, on_success=lambda _: None, name="t", tag="Test")
    thr.join(timeout=2.0)
    assert started.is_set()
    # give logger path a tick
    time.sleep(0.05)
