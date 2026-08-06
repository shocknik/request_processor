"""Clipboard: Ctrl+C копирует, не вставляет (регресс work 06.08)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("tkinter")


@pytest.fixture
def gui_app(tmp_path: Path):
    from request_processor.ui.gui import RequestProcessorApp

    try:
        app = RequestProcessorApp(db_path=tmp_path / "clip.db")
    except Exception as exc:  # noqa: BLE001
        if exc.__class__.__name__ == "TclError":
            pytest.skip(str(exc))
        raise
    app.withdraw()
    yield app
    app.destroy()


def test_ctrl_c_keycode_copies_not_pastes(gui_app) -> None:
    import tkinter as tk

    text = tk.Text(gui_app, height=3, width=40)
    text.insert("1.0", "445043, г. Тольятти, ул. Северная")
    text.pack()
    gui_app._enable_field_clipboard(text, editable=True)
    text.focus_set()
    text.tag_add("sel", "1.0", "end-1c")

    # Имитация Ctrl+C: keycode 67 (VK_C)
    event = SimpleNamespace(widget=text, keycode=67, state=0x4)
    result = gui_app._evt_ctrl_keycode(event)  # type: ignore[arg-type]
    assert result == "break"
    # Поле не должно раздуться от «вставки»
    content = text.get("1.0", "end-1c")
    assert content.count("445043") == 1
    assert "Тольятти" in content

    # Clipboard содержит адрес
    clip = gui_app.clipboard_get()
    assert "Тольятти" in clip


def test_paste_blocked_while_copy_busy(gui_app) -> None:
    import tkinter as tk

    text = tk.Text(gui_app, height=2, width=30)
    text.insert("1.0", "addr")
    text.pack()
    gui_app._enable_field_clipboard(text, editable=True)
    text._rp_clip_busy = "copy"  # type: ignore[attr-defined]
    event = SimpleNamespace(widget=text, keycode=86, state=0x4)
    assert gui_app._evt_paste(event) == "break"  # type: ignore[arg-type]
    assert text.get("1.0", "end-1c") == "addr"
