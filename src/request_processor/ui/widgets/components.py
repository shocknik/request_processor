"""
Переиспользуемые UI-компоненты редизайна Lab_request.

Компоненты только визуальные/компоновочные: не содержат OCR/парсинга.
Бизнес-логика остаётся в tab mixins (pdf_tab и др.).

Классы:
  CardFrame, PageHeader, StatusBadge, StepIndicator,
  UploadPanel, EmptyState, BottomActionBar
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable

from ...logging_setup import get_logger
from ..theme import (
    COLORS,
    FONT_PAGE_TITLE,
    FONT_UI,
    FONT_UI_HINT,
    FONT_UI_SM,
    make_link_button,
    make_primary_button,
    make_secondary_button,
)

_log = get_logger("ui.widgets")


class CardFrame(ttk.Frame):
    """Белая карточка с тонкой обводкой (tk.Frame border + ttk content)."""

    def __init__(self, parent: tk.Misc, *, padding: int = 14, **kwargs) -> None:
        # Внешняя обводка через tk.Frame — ttk border на clam непредсказуем
        self._border = tk.Frame(
            parent,
            bg=COLORS["border"],
            highlightthickness=0,
            bd=0,
        )
        super().__init__(self._border, style="Card.TFrame", **kwargs)
        self.pack(fill="both", expand=True, padx=1, pady=1)
        self._pad = padding
        self._inner = ttk.Frame(self, style="Card.TFrame", padding=padding)
        self._inner.pack(fill="both", expand=True)

    @property
    def body(self) -> ttk.Frame:
        return self._inner

    def place_in(self, **grid_or_pack) -> "CardFrame":
        """Упаковать внешнюю рамку (pack kwargs)."""
        self._border.pack(**grid_or_pack)
        return self

    def grid_in(self, **kwargs) -> "CardFrame":
        self._border.grid(**kwargs)
        return self


class StatusBadge(tk.Frame):
    """
    Компактный бейдж статуса заявки.

    Цвета:
      grey  — не обработана
      blue  — выполняется
      orange — требуется проверка
      green — завершено / подтверждена
      red   — ошибка
    """

    _PALETTE = {
        "grey": (COLORS["layer"], COLORS["text_secondary"]),
        "blue": (COLORS["accent_light"], COLORS["accent"]),
        "orange": (COLORS["warning_bg"], COLORS["warning_text"]),
        "green": (COLORS["success_bg"], COLORS["success_text"]),
        "red": (COLORS["error_bg"], COLORS["error_text"]),
    }

    def __init__(self, parent: tk.Misc, text: str = "", tone: str = "grey", **kwargs) -> None:
        bg, fg = self._PALETTE.get(tone, self._PALETTE["grey"])
        super().__init__(parent, bg=bg, padx=10, pady=3, **kwargs)
        self._label = tk.Label(
            self,
            text=text,
            bg=bg,
            fg=fg,
            font=("Segoe UI", 9),
        )
        self._label.pack()
        self._tone = tone

    def set_status(self, text: str, tone: str = "grey") -> None:
        bg, fg = self._PALETTE.get(tone, self._PALETTE["grey"])
        self.configure(bg=bg)
        self._label.configure(text=text, bg=bg, fg=fg)
        self._tone = tone


class PageHeader(ttk.Frame):
    """Заголовок страницы: title + badge + subtitle."""

    def __init__(
        self,
        parent: tk.Misc,
        *,
        title: str = "",
        subtitle: str = "",
        status_text: str = "",
        status_tone: str = "grey",
    ) -> None:
        super().__init__(parent, style="Card.TFrame")
        # Обводка
        border = tk.Frame(self, bg=COLORS["border"], bd=0)
        border.pack(fill="x")
        inner = tk.Frame(border, bg=COLORS["card"], padx=16, pady=14)
        inner.pack(fill="x", padx=1, pady=1)

        row = tk.Frame(inner, bg=COLORS["card"])
        row.pack(fill="x")
        self.title_var = tk.StringVar(value=title)
        self._title_lbl = tk.Label(
            row,
            textvariable=self.title_var,
            bg=COLORS["card"],
            fg=COLORS["text"],
            font=FONT_PAGE_TITLE,
            anchor="w",
        )
        self._title_lbl.pack(side="left")
        self.badge = StatusBadge(row, text=status_text, tone=status_tone)
        self.badge.pack(side="left", padx=(12, 0))

        self.subtitle_var = tk.StringVar(value=subtitle)
        tk.Label(
            inner,
            textvariable=self.subtitle_var,
            bg=COLORS["card"],
            fg=COLORS["muted"],
            font=FONT_UI,
            anchor="w",
            justify="left",
        ).pack(fill="x", pady=(6, 0))

    def set_title(self, title: str) -> None:
        self.title_var.set(title)

    def set_subtitle(self, subtitle: str) -> None:
        self.subtitle_var.set(subtitle)

    def set_status(self, text: str, tone: str = "grey") -> None:
        self.badge.set_status(text, tone)


class StepIndicator(ttk.Frame):
    """
    Этапы обработки заявки (не путать с бизнес-разделами Расчёт/КП/Заказ).

    1. Загрузка → 2. Распознавание → 3. Проверка → 4. Подтверждение
    active — синий круг; done — галочка; future — серый.
    """

    STEPS = (
        "1. Загрузка",
        "2. Распознавание",
        "3. Проверка",
        "4. Подтверждение",
    )

    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent, style="App.TFrame")
        self._active_index = 0
        self._nodes: list[dict] = []
        self.columnconfigure(tuple(range(len(self.STEPS) * 2 - 1)), weight=1)

        for i, label in enumerate(self.STEPS):
            col = i * 2
            cell = ttk.Frame(self, style="App.TFrame")
            cell.grid(row=0, column=col, sticky="ew", padx=2)
            cell.columnconfigure(0, weight=1)

            circle = tk.Canvas(
                cell,
                width=28,
                height=28,
                bg=COLORS["bg"],
                highlightthickness=0,
                bd=0,
            )
            circle.grid(row=0, column=0)
            # keep reference
            oval = circle.create_oval(4, 4, 24, 24, outline=COLORS["border"], width=2, fill=COLORS["card"])
            text_id = circle.create_text(
                14, 14, text=str(i + 1), fill=COLORS["muted"], font=("Segoe UI Semibold", 9)
            )
            lbl = ttk.Label(cell, text=label, style="StepIdle.TLabel", anchor="center")
            lbl.grid(row=1, column=0, pady=(4, 0))

            self._nodes.append(
                {"circle": circle, "oval": oval, "text": text_id, "label": lbl, "index": i}
            )

            if i < len(self.STEPS) - 1:
                line = tk.Frame(self, bg=COLORS["border"], height=2)
                line.grid(row=0, column=col + 1, sticky="ew", padx=4)
                # store on node for recolor
                self._nodes[i]["line"] = line

        self.set_step(0)

    def set_step(self, index: int) -> None:
        """index 0..3 — активный этап; предыдущие считаются пройденными."""
        index = max(0, min(index, len(self.STEPS) - 1))
        self._active_index = index
        for i, node in enumerate(self._nodes):
            circle: tk.Canvas = node["circle"]
            if i < index:
                # done
                circle.itemconfigure(
                    node["oval"], outline=COLORS["accent"], fill=COLORS["accent"]
                )
                circle.itemconfigure(node["text"], text="✓", fill=COLORS["text_on_accent"])
                node["label"].configure(style="StepDone.TLabel")
                if "line" in node:
                    node["line"].configure(bg=COLORS["accent"])
            elif i == index:
                circle.itemconfigure(
                    node["oval"], outline=COLORS["accent"], fill=COLORS["accent"]
                )
                circle.itemconfigure(
                    node["text"], text=str(i + 1), fill=COLORS["text_on_accent"]
                )
                node["label"].configure(style="StepActive.TLabel")
                if "line" in node:
                    node["line"].configure(bg=COLORS["border"])
            else:
                circle.itemconfigure(
                    node["oval"], outline=COLORS["border"], fill=COLORS["card"]
                )
                circle.itemconfigure(node["text"], text=str(i + 1), fill=COLORS["muted"])
                node["label"].configure(style="StepIdle.TLabel")
                if "line" in node:
                    node["line"].configure(bg=COLORS["border"])
        _log.debug("StepIndicator active=%s", index, extra={"tag": "UI"})


class UploadPanel(ttk.Frame):
    """
    Большая зона загрузки документа.

    Состояния: empty (drag/drop hint) / file (метаданные файла).
    Drag-and-drop опционален (tkinterdnd2); без него — только кнопка.
    """

    def __init__(
        self,
        parent: tk.Misc,
        *,
        on_browse: Callable[[], None] | None = None,
        on_ocr_params: Callable[[], None] | None = None,
        on_drop_path: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(parent, style="App.TFrame")
        self._on_browse = on_browse
        self._on_ocr_params = on_ocr_params
        self._on_drop_path = on_drop_path

        # Пунктирная «рамка» — Canvas + прямоугольник
        self._outer = tk.Frame(self, bg=COLORS["border"], bd=0)
        self._outer.pack(fill="x")
        self._panel = tk.Frame(self._outer, bg=COLORS["info_bg"], padx=24, pady=28)
        self._panel.pack(fill="x", padx=1, pady=1)

        self._icon = tk.Label(
            self._panel,
            text="⬆",
            bg=COLORS["info_bg"],
            fg=COLORS["accent"],
            font=("Segoe UI", 22),
        )
        self._icon.pack()

        self._title = tk.Label(
            self._panel,
            text="Перетащите документ сюда",
            bg=COLORS["info_bg"],
            fg=COLORS["text"],
            font=("Segoe UI Semibold", 12),
        )
        self._title.pack(pady=(8, 2))

        self._hint = tk.Label(
            self._panel,
            text="PDF, DOCX, XLSX или изображение",
            bg=COLORS["info_bg"],
            fg=COLORS["muted"],
            font=FONT_UI_HINT,
        )
        self._hint.pack()

        btns = tk.Frame(self._panel, bg=COLORS["info_bg"])
        btns.pack(pady=(14, 0))
        self.browse_btn = make_primary_button(
            btns, "Выбрать файл", self._handle_browse, padx=16, pady=8
        )
        self.browse_btn.pack(side="left", padx=(0, 10))
        self.ocr_link = make_link_button(
            btns, "Параметры OCR", self._handle_ocr, bg=COLORS["info_bg"]
        )
        self.ocr_link.pack(side="left")

        # Hover feedback
        for w in (self._panel, self._title, self._hint, self._icon):
            w.bind("<Enter>", self._on_enter)
            w.bind("<Leave>", self._on_leave)

        self._try_enable_dnd()
        self._file_meta: dict | None = None

    def _handle_browse(self) -> None:
        if self._on_browse:
            self._on_browse()

    def _handle_ocr(self) -> None:
        if self._on_ocr_params:
            self._on_ocr_params()

    def _on_enter(self, _event=None) -> None:
        if self._file_meta:
            return
        self._panel.configure(bg=COLORS["accent_subtle"])
        for w in (self._title, self._hint, self._icon):
            w.configure(bg=COLORS["accent_subtle"])
        self.ocr_link.configure(bg=COLORS["accent_subtle"])

    def _on_leave(self, _event=None) -> None:
        if self._file_meta:
            return
        self._panel.configure(bg=COLORS["info_bg"])
        for w in (self._title, self._hint, self._icon):
            w.configure(bg=COLORS["info_bg"])
        self.ocr_link.configure(bg=COLORS["info_bg"])

    def set_empty(self) -> None:
        """Сброс к состоянию «файл не выбран»."""
        self._file_meta = None
        self._icon.configure(text="⬆", fg=COLORS["accent"])
        self._title.configure(text="Перетащите документ сюда")
        self._hint.configure(text="PDF, DOCX, XLSX или изображение")
        self.browse_btn.configure(text="Выбрать файл")
        self._on_leave()
        _log.debug("UploadPanel empty", extra={"tag": "UI"})

    def set_file(self, name: str, *, size_label: str = "", kind: str = "") -> None:
        """Показать выбранный файл."""
        self._file_meta = {"name": name, "size": size_label, "kind": kind}
        self._icon.configure(text="📄", fg=COLORS["accent"])
        self._title.configure(text=name)
        parts = [p for p in (kind, size_label, "готов к распознаванию") if p]
        self._hint.configure(text=" · ".join(parts) if parts else "готов к распознаванию")
        self.browse_btn.configure(text="Заменить файл")
        self._panel.configure(bg=COLORS["info_bg"])
        for w in (self._title, self._hint, self._icon):
            w.configure(bg=COLORS["info_bg"])
        self.ocr_link.configure(bg=COLORS["info_bg"])
        _log.info("UploadPanel file=%s size=%s", name, size_label, extra={"tag": "UI"})

    def _try_enable_dnd(self) -> None:
        """Опциональный drag-and-drop через tkinterdnd2."""
        try:
            from tkinterdnd2 import DND_FILES  # type: ignore

            # Нужен TkinterDnD.Tk — если root обычный Tk, drop не сработает
            target = self._panel
            target.drop_target_register(DND_FILES)  # type: ignore[attr-defined]
            target.dnd_bind("<<Drop>>", self._on_drop)  # type: ignore[attr-defined]
            _log.info("UploadPanel DnD enabled", extra={"tag": "UI"})
        except Exception:
            _log.debug("UploadPanel DnD unavailable (ok)", extra={"tag": "UI"})

    def _on_drop(self, event) -> None:  # noqa: ANN001
        raw = (event.data or "").strip()
        if not raw:
            return
        # Windows: {C:\path with spaces\file.pdf}
        if raw.startswith("{") and raw.endswith("}"):
            path = raw[1:-1]
        else:
            path = raw.split()[0]
        _log.info("UploadPanel drop path=%s", path, extra={"tag": "UI"})
        if self._on_drop_path:
            self._on_drop_path(path)


class EmptyState(ttk.Frame):
    """Пустое состояние таблицы (центр карточки)."""

    def __init__(
        self,
        parent: tk.Misc,
        *,
        title: str = "Нет данных",
        subtitle: str = "",
        icon_text: str = "◇",
    ) -> None:
        super().__init__(parent, style="Card.TFrame")
        wrap = tk.Frame(self, bg=COLORS["card"])
        wrap.place(relx=0.5, rely=0.5, anchor="center")
        tk.Label(
            wrap,
            text=icon_text,
            bg=COLORS["card"],
            fg=COLORS["disabled_text"],
            font=("Segoe UI", 28),
        ).pack()
        tk.Label(
            wrap,
            text=title,
            bg=COLORS["card"],
            fg=COLORS["text"],
            font=("Segoe UI Semibold", 10),
        ).pack(pady=(8, 2))
        if subtitle:
            tk.Label(
                wrap,
                text=subtitle,
                bg=COLORS["card"],
                fg=COLORS["muted"],
                font=FONT_UI_HINT,
                justify="center",
            ).pack()


class BottomActionBar(ttk.Frame):
    """
    Нижняя закреплённая панель действий страницы заявки.

    Слева — статус документа; справа — вторичные + одна primary-кнопка.
    """

    def __init__(
        self,
        parent: tk.Misc,
        *,
        on_snapshot: Callable[[], None] | None = None,
        on_cancel: Callable[[], None] | None = None,
        on_primary: Callable[[], None] | None = None,
    ) -> None:
        border = tk.Frame(parent, bg=COLORS["border"], bd=0)
        # store for external pack
        self.border = border
        super().__init__(border, style="Card.TFrame")
        self.pack(fill="x", padx=1, pady=1)

        bar = tk.Frame(self, bg=COLORS["card"], padx=14, pady=10)
        bar.pack(fill="x")

        self.doc_status_var = tk.StringVar(value="Документ не выбран")
        tk.Label(
            bar,
            textvariable=self.doc_status_var,
            bg=COLORS["card"],
            fg=COLORS["muted"],
            font=FONT_UI_SM,
            anchor="w",
        ).pack(side="left", fill="x", expand=True)

        right = tk.Frame(bar, bg=COLORS["card"])
        right.pack(side="right")

        self.progress = ttk.Progressbar(right, mode="indeterminate", length=100)
        # progress packed only while processing

        self.snapshot_btn = make_secondary_button(
            right, "Сохранить снимок", on_snapshot or (lambda: None), padx=12, pady=7
        )
        self.snapshot_btn.pack(side="left", padx=(0, 8))
        self.cancel_btn = make_secondary_button(
            right, "Отменить", on_cancel or (lambda: None), padx=12, pady=7
        )
        self.cancel_btn.pack(side="left", padx=(0, 8))
        self.primary_btn = make_primary_button(
            right, "Извлечь данные", on_primary or (lambda: None), padx=16, pady=8
        )
        self.primary_btn.pack(side="left")
        self._primary_enabled = False
        self.set_primary_enabled(False)

    def pack_bar(self, **kwargs) -> None:
        self.border.pack(**kwargs)

    def set_doc_status(self, text: str) -> None:
        self.doc_status_var.set(text)

    def set_primary_text(self, text: str) -> None:
        self.primary_btn.configure(text=text)

    def set_primary_enabled(self, enabled: bool) -> None:
        self._primary_enabled = enabled
        c = COLORS
        if enabled:
            self.primary_btn.configure(
                state="normal",
                bg=c["accent"],
                fg=c["text_on_accent"],
                cursor="hand2",
            )
        else:
            self.primary_btn.configure(
                state="disabled",
                bg=c["accent_disabled"],
                fg=c["text_on_accent"],
                disabledforeground=c["text_on_accent"],
                cursor="arrow",
            )

    def set_processing(self, processing: bool) -> None:
        if processing:
            self.progress.pack(side="left", padx=(0, 10), before=self.snapshot_btn)
            try:
                self.progress.start(12)
            except tk.TclError:
                pass
            self.set_primary_enabled(False)
        else:
            try:
                self.progress.stop()
            except tk.TclError:
                pass
            self.progress.pack_forget()
