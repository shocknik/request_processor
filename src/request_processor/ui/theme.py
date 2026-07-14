"""
Liquid Glass (matte) — светлая тема без прозрачности/зеркальности.

Вдохновение: Apple Human Interface (iOS/macOS):
- мягкий фон, «стеклянные» карточки с тонкой обводкой
- акцент #007AFF, плавные hover-состояния
- без blur и полупрозрачности (ограничения tkinter)
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

# Fluent 2 / Win11 light tokens (упрощённо)
FLUENT: dict[str, str] = {
    # Surfaces (matte glass)
    "bg": "#f2f2f7",
    "card": "#ffffff",
    "card_secondary": "#f9f9fb",
    "layer": "#ececf1",
    "glass_edge": "#e5e5ea",
    "glass_highlight": "#fafafc",
    # Brand (iOS blue)
    "accent": "#007aff",
    "accent_hover": "#0066d6",
    "accent_pressed": "#004db3",
    "accent_light": "#d6ebff",
    "accent_subtle": "#eef4ff",
    "accent_disabled": "#99c7ff",
    # Text
    "text": "#1a1a1a",
    "text_secondary": "#5d5d5d",
    "text_on_accent": "#ffffff",
    "muted": "#6b6b6b",
    "disabled_text": "#9a9a9a",
    # Chrome
    "border": "#e5e5ea",
    "stroke": "#d1d1d6",
    "divider": "#e8e8ed",
    "success": "#107c10",
    "header_bg": "#ffffff",
    "header_text": "#1a1a1a",
    "header_muted": "#6b6b6b",
    "header_accent": "#0078d4",
    "header_bar": "#0078d4",   # thin top brand line
    "climatic_bg": "#e8f4fc",
    "row_alt": "#fafafa",
    "parse_bg": "#f3f9fd",
    "status_bg": "#f0f0f0",
    "tab_inactive": "#ececf1",
    "tab_selected": "#ffffff",
    "shadow": "#c7c7cc",
    "warn_bg": "#fff4ce",
    "error_bg": "#fde7e9",
    "draft_accent": "#c43e1c",
    "confirmed_accent": "#107c10",
    "focus": "#0078d4",
}

# Back-compat
COLORS = FLUENT


def apply_fluent_theme(root: tk.Tk | tk.Misc) -> ttk.Style:
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    c = FLUENT
    font_ui = ("Segoe UI", 10)
    font_ui_sm = ("Segoe UI", 9)
    font_title = ("Segoe UI Semibold", 16, "bold")
    font_sub = ("Segoe UI", 10)

    # --- base ---
    style.configure(".", background=c["bg"], foreground=c["text"], font=font_ui)
    style.configure("TFrame", background=c["bg"])
    style.configure("Card.TFrame", background=c["card"])
    style.configure("Header.TFrame", background=c["header_bg"])
    style.configure("TLabel", background=c["bg"], foreground=c["text"], font=font_ui)
    style.configure("Card.TLabel", background=c["card"], foreground=c["text"], font=font_ui)
    style.configure(
        "Muted.TLabel", background=c["bg"], foreground=c["muted"], font=font_ui_sm
    )
    style.configure(
        "CardMuted.TLabel",
        background=c["card"],
        foreground=c["muted"],
        font=font_ui_sm,
    )
    style.configure(
        "Title.TLabel",
        font=font_title,
        foreground=c["header_text"],
        background=c["header_bg"],
    )
    style.configure(
        "Subtitle.TLabel",
        font=font_sub,
        foreground=c["header_muted"],
        background=c["header_bg"],
    )

    # --- Secondary button (default TButton): white surface, dark text, visible stroke ---
    style.configure(
        "TButton",
        font=font_ui,
        padding=(14, 8),
        background=c["card"],
        foreground=c["text"],
        bordercolor=c["stroke"],
        darkcolor=c["stroke"],
        lightcolor=c["card"],
        borderwidth=1,
        relief="solid",
        focuscolor=c["accent_light"],
    )
    style.map(
        "TButton",
        background=[
            ("disabled", c["card_secondary"]),
            ("pressed", c["accent_light"]),
            ("active", c["accent_subtle"]),
            ("!disabled", c["card"]),
        ],
        foreground=[
            ("disabled", c["disabled_text"]),
            ("pressed", c["accent"]),
            ("active", c["accent"]),
            ("!disabled", c["text"]),
        ],
        bordercolor=[
            ("disabled", c["border"]),
            ("active", c["accent"]),
            ("!disabled", c["stroke"]),
        ],
    )

    # --- Primary (Accent): solid blue, ALWAYS white text ---
    style.configure(
        "Accent.TButton",
        font=("Segoe UI Semibold", 10, "bold"),
        padding=(16, 9),
        background=c["accent"],
        foreground=c["text_on_accent"],
        bordercolor=c["accent"],
        darkcolor=c["accent"],
        lightcolor=c["accent"],
        borderwidth=0,
        relief="flat",
        focuscolor=c["accent_hover"],
    )
    style.map(
        "Accent.TButton",
        background=[
            ("disabled", c["accent_disabled"]),
            ("pressed", c["accent_pressed"]),
            ("active", c["accent_hover"]),
            ("!disabled", c["accent"]),
        ],
        foreground=[
            ("disabled", c["text_on_accent"]),
            ("pressed", c["text_on_accent"]),
            ("active", c["text_on_accent"]),
            ("!disabled", c["text_on_accent"]),
        ],
        bordercolor=[
            ("disabled", c["accent_disabled"]),
            ("!disabled", c["accent"]),
        ],
    )

    # --- Labelframes / cards ---
    style.configure(
        "TLabelframe",
        background=c["bg"],
        borderwidth=1,
        relief="solid",
        bordercolor=c["border"],
    )
    style.configure(
        "TLabelframe.Label",
        background=c["bg"],
        font=("Segoe UI Semibold", 10),
        foreground=c["text"],
    )
    style.configure(
        "Card.TLabelframe",
        background=c["card"],
        borderwidth=1,
        relief="solid",
        bordercolor=c.get("glass_edge", c["border"]),
    )
    style.configure(
        "Card.TLabelframe.Label",
        background=c["card"],
        font=("Segoe UI Semibold", 10),
        foreground=c["text"],
    )

    # --- Treeview ---
    style.configure(
        "Treeview",
        font=font_ui_sm,
        rowheight=36,
        background=c["card"],
        fieldbackground=c["card"],
        foreground=c["text"],
        borderwidth=0,
        relief="flat",
    )
    style.configure(
        "Treeview.Heading",
        font=("Segoe UI Semibold", 9),
        background=c["layer"],
        foreground=c["text_secondary"],
        relief="flat",
        borderwidth=0,
    )
    style.map(
        "Treeview",
        background=[("selected", c["accent_light"])],
        foreground=[("selected", c["text"])],
    )
    style.map(
        "Treeview.Heading",
        background=[("active", c["accent_subtle"])],
    )

    # --- Notebook (pivot-like) ---
    style.configure(
        "TNotebook",
        background=c["bg"],
        borderwidth=0,
        tabmargins=(8, 8, 8, 0),
    )
    style.configure(
        "TNotebook.Tab",
        font=font_ui,
        padding=(18, 11),
        background=c["tab_inactive"],
        foreground=c["muted"],
        borderwidth=0,
        focuscolor=c["bg"],
    )
    style.map(
        "TNotebook.Tab",
        background=[
            ("selected", c["tab_selected"]),
            ("active", c["accent_subtle"]),
            ("!selected", c["tab_inactive"]),
        ],
        foreground=[
            ("selected", c["accent"]),
            ("active", c["text"]),
            ("!selected", c["muted"]),
        ],
        font=[
            ("selected", ("Segoe UI Semibold", 10)),
            ("!selected", font_ui),
        ],
        expand=[("selected", [1, 1, 1, 0])],
    )

    style.configure(
        "Status.TLabel",
        background=c["status_bg"],
        font=font_ui_sm,
        foreground=c["muted"],
    )
    style.configure("TEntry", font=font_ui, padding=6, fieldbackground=c["card"])
    style.configure("TSpinbox", font=font_ui, padding=4)
    style.configure("TCombobox", font=font_ui, padding=4)
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", c["card"])],
        foreground=[("readonly", c["text"])],
    )
    style.configure(
        "TCheckbutton",
        background=c["bg"],
        foreground=c["text"],
        font=font_ui,
        focuscolor=c["bg"],
    )
    style.map(
        "TCheckbutton",
        background=[("active", c["bg"])],
        foreground=[("disabled", c["disabled_text"]), ("!disabled", c["text"])],
    )
    style.configure(
        "Card.TCheckbutton",
        background=c["card"],
        foreground=c["text"],
        font=font_ui,
    )
    style.configure("TRadiobutton", background=c["bg"], font=font_ui)
    style.configure(
        "Horizontal.TProgressbar",
        background=c["accent"],
        troughcolor=c["border"],
        borderwidth=0,
        thickness=4,
    )
    style.configure("TPanedwindow", background=c["bg"])
    style.configure("Sash", sashthickness=6, sashrelief="flat")
    style.configure("TSeparator", background=c["divider"])

    return style


def make_primary_button(parent: tk.Misc, text: str, command, **kwargs) -> tk.Button:
    """Primary action — solid accent, white label (always readable)."""
    c = FLUENT
    return tk.Button(
        parent,
        text=text,
        command=command,
        bg=c["accent"],
        fg=c["text_on_accent"],
        activebackground=c["accent_hover"],
        activeforeground=c["text_on_accent"],
        disabledforeground=c["text_on_accent"],
        font=("Segoe UI Semibold", 10),
        relief="flat",
        bd=0,
        padx=kwargs.pop("padx", 18),
        pady=kwargs.pop("pady", 9),
        cursor="hand2",
        highlightthickness=0,
        **kwargs,
    )


def make_secondary_button(parent: tk.Misc, text: str, command, **kwargs) -> tk.Button:
    """Secondary — white fill, dark text, visible 1px stroke."""
    c = FLUENT
    return tk.Button(
        parent,
        text=text,
        command=command,
        bg=c["card"],
        fg=c["text"],
        activebackground=c["accent_subtle"],
        activeforeground=c["accent"],
        disabledforeground=c["disabled_text"],
        font=("Segoe UI", 10),
        relief="solid",
        bd=1,
        padx=kwargs.pop("padx", 14),
        pady=kwargs.pop("pady", 8),
        cursor="hand2",
        highlightthickness=0,
        highlightbackground=c["stroke"],
        **kwargs,
    )


def fit_window_to_screen(root: tk.Tk, *, prefer_w: int = 1200, prefer_h: int = 860) -> None:
    """Адаптивный размер: ~90% экрана, min для ноутбука."""
    root.update_idletasks()
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    usable_h = max(600, sh - 80)
    usable_w = max(900, sw - 40)
    w = min(prefer_w, max(960, int(usable_w * 0.92)))
    h = min(prefer_h, max(680, int(usable_h * 0.90)))
    w = min(w, usable_w)
    h = min(h, usable_h)
    x = max(0, (sw - w) // 2)
    y = max(0, (usable_h - h) // 2)
    root.geometry(f"{w}x{h}+{x}+{y}")
    root.minsize(min(960, usable_w), min(640, usable_h))
