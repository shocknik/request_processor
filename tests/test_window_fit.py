"""fit_window_to_screen: на «большом» экране окно не залипает в 1200×860."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

pytest.importorskip("tkinter")

from request_processor.ui.theme import fit_window_to_screen


def test_fill_mode_uses_most_of_fhd_screen() -> None:
    root = MagicMock()
    root.winfo_screenwidth.return_value = 1920
    root.winfo_screenheight.return_value = 1080
    geometries: list[str] = []
    root.geometry.side_effect = lambda g: geometries.append(g)

    fit_window_to_screen(root, prefer_w=1400, prefer_h=900, fill=True)

    assert geometries
    geo = geometries[-1]
    # "WxH+X+Y"
    size = geo.split("+", 1)[0]
    w_s, h_s = size.split("x")
    w, h = int(w_s), int(h_s)
    # ~94% of (1920-48) ≈ 1760; must be well above old 1200 cap
    assert w >= 1600
    assert h >= 850
    assert w <= 1920
    assert h <= 1080


def test_dialog_mode_respects_prefer_size() -> None:
    root = MagicMock()
    root.winfo_screenwidth.return_value = 1920
    root.winfo_screenheight.return_value = 1080
    geometries: list[str] = []
    root.geometry.side_effect = lambda g: geometries.append(g)

    fit_window_to_screen(root, prefer_w=520, prefer_h=400, fill=False)

    size = geometries[-1].split("+", 1)[0]
    w, h = map(int, size.split("x"))
    assert w == 520
    assert h == 400
