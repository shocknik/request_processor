"""Чередование фона строк ttk.Treeview — соседние позиции отличаются."""

from __future__ import annotations

from tkinter import ttk

ZEBRA_EVEN = "#FFFFFF"
ZEBRA_ODD = "#E8EEF5"
TAG_EVEN = "zebra_even"
TAG_ODD = "zebra_odd"


def configure_zebra(tree: ttk.Treeview) -> None:
    """Вешает теги чёт/нечет. Вызывать один раз после создания дерева."""
    tree.tag_configure(TAG_EVEN, background=ZEBRA_EVEN)
    tree.tag_configure(TAG_ODD, background=ZEBRA_ODD)


def zebra_tags(index: int) -> tuple[str, ...]:
    """Тег для строки с индексом 0, 1, 2…"""
    return (TAG_ODD if index % 2 else TAG_EVEN,)
