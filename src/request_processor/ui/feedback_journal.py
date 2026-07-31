"""
Журнал пожеланий и обратной связи (меню Файл).

Список записей + форма новой записи. Данные в SQLite (feedback_journal)
и уезжают в zip export-prod-data.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk
from typing import Any, Callable

from ..logging_setup import get_logger, log_operator
from ..persistence.sqlite_repo import (
    add_feedback_entry,
    get_feedback_entry,
    list_feedback_entries,
)
from .modal import create_modal, present_modal
from .theme import COLORS

_log = get_logger("ui.feedback")

# Справочники формы (русский UI)
CATEGORIES = (
    "пожелание",
    "ошибка",
    "удобство",
    "данные",
    "вопрос",
    "другое",
)
SECTIONS = (
    "Заявка",
    "Расчёт",
    "КП",
    "Заказы",
    "Пакет документов",
    "Марки",
    "Организации",
    "Справочник испытаний",
    "Программы",
    "Логи / обновление",
    "Другое",
)
PRIORITIES = ("низкий", "обычный", "высокий")


def open_feedback_journal(
    parent: tk.Misc,
    *,
    db_path: Any,
) -> None:
    """Окно журнала: список + «Новая запись»."""
    dlg = create_modal(
        parent,
        title="Журнал пожеланий и обратной связи",
        minsize=(720, 420),
    )

    bar = ttk.Frame(dlg, padding=(12, 10, 12, 6))
    bar.pack(side="top", fill="x")
    ttk.Label(
        bar,
        text="Записи с рабочего места попадают в архив «Экспорт данных prod».",
        style="Muted.TLabel",
        wraplength=680,
    ).pack(side="left", fill="x", expand=True)

    btns = ttk.Frame(dlg, padding=(12, 6, 12, 12))
    btns.pack(side="bottom", fill="x")

    body = ttk.Frame(dlg, padding=(12, 0, 12, 0))
    body.pack(side="top", fill="both", expand=True)
    body.rowconfigure(0, weight=1)
    body.columnconfigure(0, weight=1)

    cols = ("id", "date", "category", "section", "priority", "title")
    tree = ttk.Treeview(
        body,
        columns=cols,
        show="headings",
        height=12,
        selectmode="browse",
    )
    for col, title, w, stretch in (
        ("id", "№", 40, False),
        ("date", "Дата", 130, False),
        ("category", "Тип", 90, False),
        ("section", "Раздел", 120, True),
        ("priority", "Важность", 80, False),
        ("title", "Заголовок", 280, True),
    ):
        tree.heading(col, text=title)
        tree.column(col, width=w, stretch=stretch, anchor="w")
    ysb = ttk.Scrollbar(body, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=ysb.set)
    tree.grid(row=0, column=0, sticky="nsew")
    ysb.grid(row=0, column=1, sticky="ns")

    def refresh() -> None:
        for iid in tree.get_children():
            tree.delete(iid)
        try:
            rows = list_feedback_entries(limit=300, db_path=db_path)
        except Exception as exc:  # noqa: BLE001
            _log.exception("list feedback: %s", exc)
            messagebox.showerror("Журнал", f"Не удалось загрузить: {exc}", parent=dlg)
            return
        for r in rows:
            created = (r.get("created_at") or "")[:19].replace("T", " ")
            tree.insert(
                "",
                "end",
                iid=str(r["id"]),
                values=(
                    r["id"],
                    created,
                    r.get("category") or "",
                    r.get("section") or "",
                    r.get("priority") or "",
                    (r.get("title") or "")[:80],
                ),
            )

    def on_add() -> None:
        open_feedback_entry_form(
            dlg,
            db_path=db_path,
            on_saved=refresh,
        )

    def on_view() -> None:
        sel = tree.selection()
        if not sel:
            messagebox.showinfo("Журнал", "Выберите запись в списке.", parent=dlg)
            return
        eid = int(sel[0])
        row = get_feedback_entry(eid, db_path=db_path)
        if not row:
            messagebox.showerror("Журнал", "Запись не найдена.", parent=dlg)
            refresh()
            return
        open_feedback_view(dlg, row)

    def on_dbl(_e: tk.Event) -> None:
        on_view()

    tree.bind("<Double-Button-1>", on_dbl)

    ttk.Button(btns, text="Новая запись…", style="Accent.TButton", command=on_add).pack(
        side="left"
    )
    ttk.Button(btns, text="Открыть…", command=on_view).pack(side="left", padx=(8, 0))
    ttk.Button(btns, text="Обновить", command=refresh).pack(side="left", padx=(8, 0))
    ttk.Button(btns, text="Закрыть", command=dlg.destroy).pack(side="right")

    present_modal(dlg, prefer_w=780, prefer_h=480)
    refresh()
    log_operator("feedback journal opened", tag="Журнал")


def open_feedback_view(parent: tk.Misc, row: dict[str, Any]) -> None:
    """Просмотр одной записи (только чтение)."""
    dlg = create_modal(parent, title=f"Запись №{row.get('id')}", minsize=(520, 400))
    btns = ttk.Frame(dlg, padding=12)
    btns.pack(side="bottom", fill="x")
    form = ttk.Frame(dlg, padding=12)
    form.pack(side="top", fill="both", expand=True)

    lines = [
        f"Дата: {(row.get('created_at') or '')[:19].replace('T', ' ')}",
        f"Тип: {row.get('category') or '—'}",
        f"Раздел: {row.get('section') or '—'}",
        f"Важность: {row.get('priority') or '—'}",
        f"Версия: {row.get('app_version') or '—'}",
        f"ПК: {row.get('host_name') or '—'}",
        "",
        f"Заголовок: {row.get('title') or ''}",
        "",
        "Описание:",
        row.get("body") or "",
    ]
    if row.get("steps"):
        lines.extend(["", "Как воспроизвести:", row["steps"]])
    if row.get("expected"):
        lines.extend(["", "Ожидалось:", row["expected"]])
    if row.get("actual"):
        lines.extend(["", "Фактически:", row["actual"]])

    txt = scrolledtext.ScrolledText(form, height=18, wrap="word", font=("Segoe UI", 10))
    txt.pack(fill="both", expand=True)
    txt.insert("1.0", "\n".join(lines))
    txt.configure(state="disabled")
    ttk.Button(btns, text="Закрыть", command=dlg.destroy).pack(side="right")
    present_modal(dlg, prefer_w=560, prefer_h=480)


def open_feedback_entry_form(
    parent: tk.Misc,
    *,
    db_path: Any,
    on_saved: Callable[[], None] | None = None,
) -> None:
    """Форма новой записи обратной связи."""
    dlg = create_modal(parent, title="Новая запись — обратная связь", minsize=(560, 520))

    btns = ttk.Frame(dlg, padding=(12, 8, 12, 12))
    btns.pack(side="bottom", fill="x")

    form = ttk.Frame(dlg, padding=12)
    form.pack(side="top", fill="both", expand=True)
    form.columnconfigure(1, weight=1)

    cat_var = tk.StringVar(master=dlg, value=CATEGORIES[0])
    sec_var = tk.StringVar(master=dlg, value=SECTIONS[0])
    prio_var = tk.StringVar(master=dlg, value="обычный")
    title_var = tk.StringVar(master=dlg, value="")

    row = 0
    ttk.Label(form, text="Тип записи:").grid(row=row, column=0, sticky="w", pady=4)
    ttk.Combobox(
        form, textvariable=cat_var, values=CATEGORIES, state="readonly", width=28
    ).grid(row=row, column=1, sticky="ew", pady=4)

    row += 1
    ttk.Label(form, text="Раздел программы:").grid(row=row, column=0, sticky="w", pady=4)
    ttk.Combobox(
        form, textvariable=sec_var, values=SECTIONS, state="readonly", width=28
    ).grid(row=row, column=1, sticky="ew", pady=4)

    row += 1
    ttk.Label(form, text="Важность:").grid(row=row, column=0, sticky="w", pady=4)
    ttk.Combobox(
        form, textvariable=prio_var, values=PRIORITIES, state="readonly", width=28
    ).grid(row=row, column=1, sticky="ew", pady=4)

    row += 1
    ttk.Label(form, text="Краткий заголовок:").grid(row=row, column=0, sticky="w", pady=4)
    ttk.Entry(form, textvariable=title_var).grid(row=row, column=1, sticky="ew", pady=4)

    row += 1
    ttk.Label(form, text="Свободный текст (описание):").grid(
        row=row, column=0, columnspan=2, sticky="w", pady=(10, 2)
    )
    row += 1
    body = scrolledtext.ScrolledText(
        form, height=8, wrap="word", font=("Segoe UI", 10)
    )
    body.grid(row=row, column=0, columnspan=2, sticky="nsew", pady=2)
    form.rowconfigure(row, weight=2)

    row += 1
    ttk.Label(
        form,
        text="Как повторить (необязательно):",
        style="Muted.TLabel",
    ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(8, 2))
    row += 1
    steps = scrolledtext.ScrolledText(form, height=3, wrap="word", font=("Segoe UI", 10))
    steps.grid(row=row, column=0, columnspan=2, sticky="ew", pady=2)

    row += 1
    exp_fr = ttk.Frame(form)
    exp_fr.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(8, 0))
    exp_fr.columnconfigure(0, weight=1)
    exp_fr.columnconfigure(1, weight=1)
    ttk.Label(exp_fr, text="Ожидалось:", style="Muted.TLabel").grid(
        row=0, column=0, sticky="w"
    )
    ttk.Label(exp_fr, text="Фактически:", style="Muted.TLabel").grid(
        row=0, column=1, sticky="w", padx=(8, 0)
    )
    expected = scrolledtext.ScrolledText(exp_fr, height=2, wrap="word", font=("Segoe UI", 10))
    expected.grid(row=1, column=0, sticky="ew", pady=2)
    actual = scrolledtext.ScrolledText(exp_fr, height=2, wrap="word", font=("Segoe UI", 10))
    actual.grid(row=1, column=1, sticky="ew", pady=2, padx=(8, 0))

    def save() -> None:
        try:
            eid = add_feedback_entry(
                category=cat_var.get(),
                section=sec_var.get(),
                priority=prio_var.get(),
                title=title_var.get(),
                body=body.get("1.0", "end").strip(),
                steps=steps.get("1.0", "end").strip() or None,
                expected=expected.get("1.0", "end").strip() or None,
                actual=actual.get("1.0", "end").strip() or None,
                db_path=db_path,
            )
        except ValueError as exc:
            messagebox.showwarning("Журнал", str(exc), parent=dlg)
            return
        except Exception as exc:  # noqa: BLE001
            _log.exception("add feedback: %s", exc)
            messagebox.showerror("Журнал", f"Не удалось сохранить: {exc}", parent=dlg)
            return
        log_operator(
            "feedback saved id=%s category=%s section=%s title=%r",
            eid,
            cat_var.get(),
            sec_var.get(),
            (title_var.get() or "")[:60],
            tag="Журнал",
        )
        messagebox.showinfo(
            "Журнал",
            f"Запись №{eid} сохранена.\n"
            "Она попадёт в архив при «Экспорт данных prod».",
            parent=dlg,
        )
        dlg.destroy()
        if on_saved:
            on_saved()

    ttk.Button(btns, text="Сохранить", style="Accent.TButton", command=save).pack(
        side="left"
    )
    ttk.Button(btns, text="Отмена", command=dlg.destroy).pack(side="left", padx=8)
    present_modal(dlg, prefer_w=600, prefer_h=560, focus=None)
    try:
        # фокус на заголовок
        for w in form.winfo_children():
            if isinstance(w, ttk.Entry):
                w.focus_set()
                break
    except tk.TclError:
        pass
