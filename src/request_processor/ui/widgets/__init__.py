"""UI widgets: clipboard helpers + redesign components."""

from .clipboard import ClipboardMixin
from .components import (
    BottomActionBar,
    CardFrame,
    EmptyState,
    PageHeader,
    StatusBadge,
    StepIndicator,
    UploadPanel,
)
from .sidebar import NAV_ITEMS, SECTION_TO_TAB, TAB_TO_SECTION, Sidebar

__all__ = [
    "BottomActionBar",
    "CardFrame",
    "ClipboardMixin",
    "EmptyState",
    "NAV_ITEMS",
    "PageHeader",
    "SECTION_TO_TAB",
    "Sidebar",
    "StatusBadge",
    "StepIndicator",
    "TAB_TO_SECTION",
    "UploadPanel",
]
