"""Unit tests for ui.modal (geometry / master helpers)."""

from __future__ import annotations

import tkinter as tk

import pytest

from request_processor.ui.modal import create_modal, present_modal, run_modal


@pytest.fixture()
def root() -> tk.Tk:
    r = tk.Tk()
    r.withdraw()
    yield r
    try:
        r.destroy()
    except tk.TclError:
        pass


def test_create_modal_has_title_and_minsize(root: tk.Tk) -> None:
    dlg = create_modal(root, title="Тест", minsize=(400, 200))
    assert dlg.winfo_toplevel() is dlg
    assert dlg.title() == "Тест"
    dlg.destroy()


def test_present_modal_sets_geometry(root: tk.Tk) -> None:
    dlg = create_modal(root, title="Geom", minsize=(300, 150))
    tk.Label(dlg, text="hi").pack()
    present_modal(dlg, prefer_w=400, prefer_h=250)
    dlg.update_idletasks()
    geom = dlg.geometry()
    # parse WxH from geometry string (more stable than winfo_width pre-mainloop)
    size = geom.split("+", 1)[0]
    assert size != "1x1", geom
    w_str, h_str = size.split("x", 1)
    assert int(w_str) >= 200, geom
    assert int(h_str) >= 120, geom
    dlg.destroy()


def test_run_modal_destroys_cleanly(root: tk.Tk) -> None:
    dlg = create_modal(root, title="Wait", minsize=(320, 180))
    tk.Label(dlg, text="x").pack()

    def _close() -> None:
        dlg.destroy()

    # close immediately after map
    dlg.after(10, _close)
    run_modal(dlg, prefer_w=360, prefer_h=200)
    # no hang; dialog gone
    assert not dlg.winfo_exists()
