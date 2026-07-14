"""
Прогресс извлечения заявки (OCR / страницы / марки).

Потокобезопасный callback: GUI обновляет Progressbar, CLI — print.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Protocol


class ProgressCallback(Protocol):
    def __call__(
        self,
        message: str,
        *,
        current: int | None = None,
        total: int | None = None,
        stage: str = "",
    ) -> None: ...


@dataclass
class NullProgress:
    """Заглушка — без UI."""

    def __call__(
        self,
        message: str,
        *,
        current: int | None = None,
        total: int | None = None,
        stage: str = "",
    ) -> None:
        return


@dataclass
class ExtractProgress:
    """
    Удобная обёртка: percent 0–100 + message.

    on_update(message, percent) — percent None, если неизвестно.
    """

    on_update: Callable[[str, float | None], None] | None = None
    _last_percent: float = field(default=0.0, repr=False)

    def __call__(
        self,
        message: str,
        *,
        current: int | None = None,
        total: int | None = None,
        stage: str = "",
    ) -> None:
        percent: float | None = None
        if current is not None and total and total > 0:
            percent = max(0.0, min(100.0, 100.0 * current / total))
            self._last_percent = percent
        label = message
        if stage:
            label = f"[{stage}] {message}"
        if self.on_update:
            self.on_update(label, percent)


NULL_PROGRESS: ProgressCallback = NullProgress()
