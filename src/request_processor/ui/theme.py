"""
Тема Lab_request (v0.10 UI redesign).

Палитра и ttk-стили под макет «современное настольное приложение»:
  фон #F5F7FA, карточки #FFFFFF, акцент #1677FF, текст #1F2329.

AppStyles — именованные стили (Sidebar, Card, Primary, …) без поломки
диалоговых окон: стили scoped, базовые TButton/TLabel сохраняют обратную
совместимость с остальными вкладками.

Ограничения tkinter: без blur, без тяжёлых теней, без веб-градиентов.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ..logging_setup import get_logger

_log = get_logger("ui.theme")

# ---------------------------------------------------------------------------
# Design tokens (макет + Fluent-совместимые ключи для back-compat)
# ---------------------------------------------------------------------------
FLUENT: dict[str, str] = {
    # Surfaces
    "bg": "#F5F7FA",
    "card": "#FFFFFF",
    "card_secondary": "#F8FAFC",
    "layer": "#EEF1F5",
    "inactive_bg": "#EEF1F5",
    "glass_edge": "#D9DEE7",
    "glass_highlight": "#FAFBFC",
    # Brand
    "accent": "#1677FF",
    "accent_hover": "#0958D9",
    "accent_pressed": "#003EB3",
    "accent_light": "#E6F0FF",
    "accent_subtle": "#F0F5FF",
    "accent_disabled": "#91CAFF",
    # Text
    "text": "#1F2329",
    "text_secondary": "#6B7280",
    "text_on_accent": "#FFFFFF",
    "muted": "#6B7280",
    "disabled_text": "#9CA3AF",
    # Chrome
    "border": "#D9DEE7",
    "stroke": "#D9DEE7",
    "divider": "#E5E7EB",
    "success": "#16A34A",
    "success_bg": "#ECFDF5",
    "success_text": "#15803D",
    "warning": "#D97706",
    "warning_bg": "#FFF7ED",
    "warning_text": "#C2410C",
    "error": "#DC2626",
    "error_bg": "#FEF2F2",
    "error_text": "#B91C1C",
    "info_bg": "#EFF6FF",
    "info_text": "#1D4ED8",
    # Header / chrome (legacy keys used across tabs)
    "header_bg": "#FFFFFF",
    "header_text": "#1F2329",
    "header_muted": "#6B7280",
    "header_accent": "#1677FF",
    "header_bar": "#1677FF",
    "climatic_bg": "#E8F4FC",
    "row_alt": "#FAFBFC",
    "parse_bg": "#F0F5FF",
    "status_bg": "#EEF1F5",
    "tab_inactive": "#EEF1F5",
    "tab_selected": "#FFFFFF",
    "shadow": "#C7CCD4",
    "warn_bg": "#FFF7ED",
    "draft_accent": "#D97706",
    "confirmed_accent": "#16A34A",
    "focus": "#1677FF",
    # Sidebar
    "sidebar_bg": "#FFFFFF",
    "sidebar_active_bg": "#E6F0FF",
    "sidebar_hover_bg": "#F0F5FF",
    "sidebar_text": "#374151",
    "sidebar_active_text": "#1677FF",
    "sidebar_width": "210",
    "sidebar_collapsed_width": "64",
}

# Back-compat alias
COLORS = FLUENT

# Типографика (pt; на 125–150% DPI Windows масштабирует ttk/tk)
FONT_UI = ("Segoe UI", 10)
FONT_UI_SM = ("Segoe UI", 9)
FONT_UI_HINT = ("Segoe UI", 9)
FONT_SEMIBOLD = ("Segoe UI Semibold", 10)
FONT_CARD_TITLE = ("Segoe UI Semibold", 11)
FONT_PAGE_TITLE = ("Segoe UI Semibold", 16, "bold")
FONT_STEP = ("Segoe UI", 9)


class AppStyles:
    """
    Централизованная настройка ttk-стилей приложения.

    Вызывать один раз после создания корневого Tk (до построения UI).
    Не перезаписывает глобальные стили сторонних Toplevel без нужды:
    большинство диалогов наследуют TButton / TLabel.
    """

    @staticmethod
    def configure(style: ttk.Style) -> ttk.Style:
        """Применить clam + полный набор именованных стилей."""
        try:
            style.theme_use("clam")
            _log.debug("ttk theme set to clam", extra={"tag": "UI"})
        except tk.TclError:
            _log.warning("clam theme unavailable, using default", extra={"tag": "UI"})

        c = FLUENT

        # --- base ---
        style.configure(".", background=c["bg"], foreground=c["text"], font=FONT_UI)
        style.configure("TFrame", background=c["bg"])
        style.configure("App.TFrame", background=c["bg"])
        style.configure("Card.TFrame", background=c["card"])
        style.configure("Sidebar.TFrame", background=c["sidebar_bg"])
        style.configure("Header.TFrame", background=c["header_bg"])
        style.configure("Upload.TFrame", background=c["info_bg"])
        style.configure("BottomBar.TFrame", background=c["card"])
        style.configure("Context.TFrame", background=c["info_bg"])

        style.configure("TLabel", background=c["bg"], foreground=c["text"], font=FONT_UI)
        style.configure("App.TLabel", background=c["bg"], foreground=c["text"], font=FONT_UI)
        style.configure("Card.TLabel", background=c["card"], foreground=c["text"], font=FONT_UI)
        style.configure(
            "Muted.TLabel",
            background=c["bg"],
            foreground=c["muted"],
            font=FONT_UI_SM,
        )
        style.configure(
            "CardMuted.TLabel",
            background=c["card"],
            foreground=c["muted"],
            font=FONT_UI_SM,
        )
        style.configure(
            "PageTitle.TLabel",
            font=FONT_PAGE_TITLE,
            foreground=c["text"],
            background=c["card"],
        )
        style.configure(
            "CardTitle.TLabel",
            font=FONT_CARD_TITLE,
            foreground=c["text"],
            background=c["card"],
        )
        style.configure(
            "Title.TLabel",
            font=FONT_PAGE_TITLE,
            foreground=c["header_text"],
            background=c["header_bg"],
        )
        style.configure(
            "Subtitle.TLabel",
            font=FONT_UI,
            foreground=c["header_muted"],
            background=c["header_bg"],
        )
        style.configure(
            "Status.TLabel",
            background=c["status_bg"],
            font=FONT_UI_SM,
            foreground=c["muted"],
        )
        style.configure(
            "Hint.TLabel",
            background=c["card"],
            foreground=c["muted"],
            font=FONT_UI_HINT,
        )
        style.configure(
            "StepActive.TLabel",
            background=c["bg"],
            foreground=c["accent"],
            font=("Segoe UI Semibold", 9),
        )
        style.configure(
            "StepDone.TLabel",
            background=c["bg"],
            foreground=c["text_secondary"],
            font=FONT_STEP,
        )
        style.configure(
            "StepIdle.TLabel",
            background=c["bg"],
            foreground=c["disabled_text"],
            font=FONT_STEP,
        )

        # --- Secondary button (default TButton) ---
        style.configure(
            "TButton",
            font=FONT_UI,
            padding=(14, 9),
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
        style.configure("Secondary.TButton", font=FONT_UI, padding=(14, 9))
        # наследуем map от TButton

        # --- Primary ---
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
        style.configure("Primary.TButton", font=("Segoe UI Semibold", 10, "bold"), padding=(16, 9))
        # Primary.TButton maps copy Accent (clam needs explicit configure)
        for name in ("Primary.TButton",):
            style.configure(
                name,
                font=("Segoe UI Semibold", 10, "bold"),
                padding=(16, 9),
                background=c["accent"],
                foreground=c["text_on_accent"],
                bordercolor=c["accent"],
                darkcolor=c["accent"],
                lightcolor=c["accent"],
                borderwidth=0,
                relief="flat",
            )
            style.map(
                name,
                background=[
                    ("disabled", c["accent_disabled"]),
                    ("pressed", c["accent_pressed"]),
                    ("active", c["accent_hover"]),
                    ("!disabled", c["accent"]),
                ],
                foreground=[
                    ("disabled", c["text_on_accent"]),
                    ("!disabled", c["text_on_accent"]),
                ],
            )

        # --- Link / Danger ---
        style.configure(
            "Link.TButton",
            font=FONT_UI,
            padding=(8, 6),
            background=c["card"],
            foreground=c["accent"],
            borderwidth=0,
            relief="flat",
            focuscolor=c["accent_light"],
        )
        style.map(
            "Link.TButton",
            foreground=[
                ("disabled", c["disabled_text"]),
                ("active", c["accent_hover"]),
                ("!disabled", c["accent"]),
            ],
            background=[
                ("active", c["accent_subtle"]),
                ("!disabled", c["card"]),
            ],
        )
        style.configure(
            "Danger.TButton",
            font=FONT_UI,
            padding=(12, 8),
            background=c["card"],
            foreground=c["error"],
            bordercolor=c["error"],
            borderwidth=1,
            relief="solid",
        )
        style.map(
            "Danger.TButton",
            background=[
                ("active", c["error_bg"]),
                ("!disabled", c["card"]),
            ],
            foreground=[("disabled", c["disabled_text"]), ("!disabled", c["error"])],
        )

        # --- Sidebar nav buttons (ttk; active state via style swap) ---
        style.configure(
            "Sidebar.TButton",
            font=FONT_UI,
            padding=(12, 10),
            background=c["sidebar_bg"],
            foreground=c["sidebar_text"],
            borderwidth=0,
            relief="flat",
            anchor="w",
            focuscolor=c["sidebar_bg"],
        )
        style.map(
            "Sidebar.TButton",
            background=[
                ("active", c["sidebar_hover_bg"]),
                ("pressed", c["sidebar_active_bg"]),
                ("!disabled", c["sidebar_bg"]),
            ],
            foreground=[
                ("active", c["sidebar_active_text"]),
                ("!disabled", c["sidebar_text"]),
            ],
        )
        style.configure(
            "SidebarActive.TButton",
            font=("Segoe UI Semibold", 10),
            padding=(12, 10),
            background=c["sidebar_active_bg"],
            foreground=c["sidebar_active_text"],
            borderwidth=0,
            relief="flat",
            anchor="w",
            focuscolor=c["sidebar_active_bg"],
        )
        style.map(
            "SidebarActive.TButton",
            background=[
                ("active", c["sidebar_active_bg"]),
                ("!disabled", c["sidebar_active_bg"]),
            ],
            foreground=[("!disabled", c["sidebar_active_text"])],
        )
        style.configure(
            "SidebarCollapse.TButton",
            font=FONT_UI_SM,
            padding=(8, 8),
            background=c["sidebar_bg"],
            foreground=c["muted"],
            borderwidth=0,
            relief="flat",
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
            font=FONT_SEMIBOLD,
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
            font=FONT_SEMIBOLD,
            foreground=c["text"],
        )

        # --- Treeview ---
        style.configure(
            "Treeview",
            font=FONT_UI_SM,
            rowheight=34,
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
            # Яркий selected: tag_background строк (warning/ok) иначе
            # «съедает» выделение — оператор не видит, что строка выбрана.
            background=[("selected", c["accent"])],
            foreground=[("selected", c["text_on_accent"])],
        )
        style.map(
            "Treeview.Heading",
            background=[("active", c["accent_subtle"])],
        )

        # --- Notebook: обычный (скрыт tabs через Hidden.*) ---
        style.configure(
            "TNotebook",
            background=c["bg"],
            borderwidth=0,
            tabmargins=(0, 0, 0, 0),
        )
        style.configure(
            "TNotebook.Tab",
            font=FONT_UI,
            padding=(14, 8),
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
        )
        # Скрытые вкладки: sidebar-навигация; notebook остаётся API для menubar/тестов
        style.layout("Hidden.TNotebook.Tab", [])
        style.configure(
            "Hidden.TNotebook",
            background=c["bg"],
            borderwidth=0,
            tabmargins=0,
        )

        style.configure("TEntry", font=FONT_UI, padding=7, fieldbackground=c["card"])
        style.configure("TSpinbox", font=FONT_UI, padding=4)
        style.configure("TCombobox", font=FONT_UI, padding=4)
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", c["card"])],
            foreground=[("readonly", c["text"])],
        )
        style.configure(
            "TCheckbutton",
            background=c["bg"],
            foreground=c["text"],
            font=FONT_UI,
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
            font=FONT_UI,
            # без синей «заливки» индикатора при фокусе (clam)
            focuscolor=c["card"],
            # !selected = border, иначе белый индикатор на белой карточке «исчезает»
            indicatorcolor=c["border"],
            indicatorrelief="solid",
            indicatormargin=2,
        )
        style.map(
            "Card.TCheckbutton",
            background=[("active", c["card"]), ("selected", c["card"])],
            indicatorcolor=[
                ("selected", c["accent"]),
                ("!selected", c["border"]),
                ("active", c["muted"]),
            ],
            focuscolor=[("!focus", c["card"]), ("focus", c["card"])],
        )
        style.configure("TRadiobutton", background=c["bg"], font=FONT_UI)
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

        _log.info(
            "AppStyles configured accent=%s bg=%s",
            c["accent"],
            c["bg"],
            extra={"tag": "UI"},
        )
        return style


def apply_fluent_theme(root: tk.Tk | tk.Misc) -> ttk.Style:
    """Back-compat: применить AppStyles к корневому окну."""
    style = ttk.Style(root)
    return AppStyles.configure(style)


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


def make_link_button(parent: tk.Misc, text: str, command, **kwargs) -> tk.Button:
    """Текстовая ссылка (Параметры OCR и т.п.)."""
    c = FLUENT
    return tk.Button(
        parent,
        text=text,
        command=command,
        bg=kwargs.pop("bg", c["card"]),
        fg=c["accent"],
        activebackground=c["accent_subtle"],
        activeforeground=c["accent_hover"],
        disabledforeground=c["disabled_text"],
        font=("Segoe UI", 10),
        relief="flat",
        bd=0,
        padx=kwargs.pop("padx", 8),
        pady=kwargs.pop("pady", 6),
        cursor="hand2",
        highlightthickness=0,
        **kwargs,
    )


def enable_windows_dpi_awareness() -> None:
    """Чёткий UI на 100–150% масштабе Windows (до создания Tk)."""
    import sys

    if sys.platform != "win32":
        return
    try:
        from ctypes import windll

        # 2 = PROCESS_PER_MONITOR_DPI_AWARE_V2 (Win 8.1+)
        windll.shcore.SetProcessDpiAwareness(2)
        _log.debug("DPI awareness: per-monitor v2", extra={"tag": "UI"})
    except Exception:
        try:
            from ctypes import windll

            windll.user32.SetProcessDPIAware()
            _log.debug("DPI awareness: system", extra={"tag": "UI"})
        except Exception:
            _log.debug("DPI awareness unavailable", extra={"tag": "UI"})


def fit_window_to_screen(
    root: tk.Tk,
    *,
    prefer_w: int = 1200,
    prefer_h: int = 860,
    fill: bool = False,
) -> None:
    """Адаптивный размер окна под экран.

    * ``fill=True`` (главное окно) — ~94% рабочего пространства на
      1920×1080 и шире; ``prefer_*`` — нижняя граница, если экран позволяет.
    * ``fill=False`` (диалоги) — ``prefer_*`` как целевой размер, сжимается
      на маленьком экране.
    """
    root.update_idletasks()
    sw = max(1, int(root.winfo_screenwidth()))
    sh = max(1, int(root.winfo_screenheight()))
    # Поля под панель задач и края
    usable_w = max(800, sw - 48)
    usable_h = max(600, sh - 88)

    if fill:
        # Большие мониторы: занять почти весь рабочий стол
        frac_w = 0.94 if sw >= 1600 else 0.92
        frac_h = 0.92 if sh >= 900 else 0.88
        # Не уже prefer, если экран позволяет — иначе «плавающее» 1200×860 на FHD
        w = min(usable_w, max(prefer_w, int(usable_w * frac_w)))
        h = min(usable_h, max(prefer_h, int(usable_h * frac_h)))
        min_w = min(1100, usable_w)
        min_h = min(720, usable_h)
    else:
        w = min(prefer_w, usable_w)
        h = min(prefer_h, usable_h)
        min_w = min(400, usable_w)
        min_h = min(300, usable_h)

    w = max(min(w, usable_w), min(min_w, usable_w) if fill else min(320, usable_w))
    h = max(min(h, usable_h), min(min_h, usable_h) if fill else min(240, usable_h))
    x = max(0, (sw - w) // 2)
    y = max(0, (sh - h - 48) // 2)
    root.geometry(f"{w}x{h}+{x}+{y}")
    root.minsize(min_w if fill else min(400, usable_w), min_h if fill else min(300, usable_h))
    try:
        root.resizable(True, True)
    except tk.TclError:
        pass
