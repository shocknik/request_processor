"""Mousewheel dispatcher for Canvas scroll areas."""

from __future__ import annotations

import tkinter as tk

import pytest

from request_processor.ui.widgets.mousewheel import (
    MousewheelManager,
    _is_nested_scrollable,
    _scroll_canvas,
    _widget_is_under,
    install_mousewheel,
    register_canvas_mousewheel,
)


def _make_root() -> tk.Tk:
    try:
        r = tk.Tk()
        r.withdraw()
        return r
    except tk.TclError as exc:
        pytest.skip(f"tk unavailable: {exc}")


@pytest.fixture()
def root():
    r = _make_root()
    yield r
    try:
        r.destroy()
    except tk.TclError:
        pass


def test_widget_is_under_parent_chain(root: tk.Tk) -> None:
    outer = tk.Frame(root)
    inner = tk.Frame(outer)
    leaf = tk.Label(inner, text="x")
    assert _widget_is_under(leaf, outer)
    assert _widget_is_under(outer, outer)
    other = tk.Frame(root)
    assert not _widget_is_under(leaf, other)


def test_nested_treeview_detected(root: tk.Tk) -> None:
    from tkinter import ttk

    outer = tk.Frame(root)
    tree = ttk.Treeview(outer, height=2)
    assert _is_nested_scrollable(tree, outer)


def test_scroll_canvas_delta(root: tk.Tk) -> None:
    canvas = tk.Canvas(root, width=100, height=40)
    canvas.pack()
    canvas.create_rectangle(0, 0, 10, 400)
    canvas.configure(scrollregion=(0, 0, 10, 400))

    class E:
        delta = -120
        num = None

    assert _scroll_canvas(canvas, E())  # type: ignore[arg-type]
    first, _ = canvas.yview()
    assert float(first) > 0


def test_manager_register_and_install(root: tk.Tk) -> None:
    install_mousewheel(root)
    outer = tk.Frame(root)
    canvas = tk.Canvas(outer)
    register_canvas_mousewheel(outer, canvas, priority=1)
    mgr = MousewheelManager()
    mgr.install(root)
    mgr.register(outer, canvas)
    assert len(mgr._entries) == 1
