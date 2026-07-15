"""КП: 3 стиля бланка + логотип (если файл есть)."""

from __future__ import annotations

from pathlib import Path

from request_processor.generation.kp_generator import render_kp_style_previews
from request_processor.generation.lab_profile import load_lab_profile


def test_render_three_kp_style_previews(tmp_path: Path) -> None:
    paths = render_kp_style_previews(tmp_path)
    assert len(paths) == 3
    for p in paths:
        assert p.is_file()
        assert p.stat().st_size > 1000


def test_lab_profile_defaults() -> None:
    profile = load_lab_profile(path=Path("docs/lab_profile.example.yaml"))
    assert profile.name
    assert profile.kp_style in ("classic", "modern", "compact")
