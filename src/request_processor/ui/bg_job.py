"""
Фоновые GUI-задачи: единый стиль «worker без tkinter + callback на main».

Эталон extract: ``extract_job`` (Queue + poll) — для длинных job с progress.
Этот helper — для коротких операций (расчёт, КП, Word), где достаточно
``Thread`` + ``root.after(0, …)``.

Правила:
- ``work()`` **не** трогает tk / StringVar / messagebox / geometry
- ``on_success`` / ``on_error`` вызываются только на main thread
- если mainloop нет (pytest без loop) — callback не падает, пишем warning
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import TypeVar

_log = logging.getLogger("request_processor.ui.bg_job")

T = TypeVar("T")


def schedule_ui(root: object, callback: Callable[[], None], *, tag: str = "UI") -> bool:
    """Поставить callback на main thread через ``after(0)``.

    Returns:
        True если удалось запланировать, False если mainloop недоступен.
    """
    after = getattr(root, "after", None)
    if after is None:
        _log.warning("schedule_ui: root has no after() tag=%s", tag, extra={"tag": tag})
        return False
    try:
        after(0, callback)
        return True
    except RuntimeError:
        # «main thread is not in main loop» (тесты / worker без GUI)
        _log.warning(
            "schedule_ui: cannot after(0) — no main loop tag=%s",
            tag,
            extra={"tag": tag},
        )
        return False


def run_bg_job(
    root: object,
    work: Callable[[], T],
    *,
    on_success: Callable[[T], None],
    on_error: Callable[[BaseException], None] | None = None,
    name: str = "bg",
    tag: str = "UI",
    daemon: bool = True,
) -> threading.Thread:
    """Запустить ``work`` в daemon-thread; UI-колбэки — через ``schedule_ui``.

    Args:
        root: виджет с ``after`` (обычно ``self`` App / Toplevel).
        work: чистая работа без tkinter; возвращает результат.
        on_success: UI на main thread с результатом ``work``.
        on_error: UI на main thread при исключении; если None — только log.
        name: имя потока (отладка).
        tag: log tag (``Расчёт`` / ``КП`` / …).
        daemon: daemon thread (по умолчанию True).
    """

    def _runner() -> None:
        try:
            result = work()
        except BaseException as exc:  # noqa: BLE001 — доставляем в UI
            _log.exception("%s failed: %s", name, exc, extra={"tag": tag})
            if on_error is not None:
                schedule_ui(root, lambda e=exc: on_error(e), tag=tag)
            return

        schedule_ui(root, lambda r=result: on_success(r), tag=tag)

    thread = threading.Thread(target=_runner, name=name, daemon=daemon)
    thread.start()
    return thread
