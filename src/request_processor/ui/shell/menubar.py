"""Application menu bar for Lab_request."""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..app import RequestProcessorApp


def install_menubar(app: Any) -> tk.Menu:
    """Classic menu: Файл / Вид / Данные / Сервис / Справка."""
    root_menu = tk.Menu(app, tearoff=0)
    app.config(menu=root_menu)

    def go_tab(tab_attr: str) -> None:
        """Переключить раздел; сайдбар синхронизируется в <<NotebookTabChanged>>."""
        tab = getattr(app, tab_attr, None)
        if tab is not None and getattr(app, "notebook", None) is not None:
            app.notebook.select(tab)
            # Явная синхронизация сайдбара (если map доступен)
            go_section = getattr(app, "go_section", None)
            tab_to_section = getattr(app, "_tab_widget_to_section", None)
            if callable(go_section) and isinstance(tab_to_section, dict):
                section = tab_to_section.get(tab)
                if section and getattr(app, "sidebar", None) is not None:
                    app.sidebar.set_active(section)

    def call(name: str, *args: Any) -> None:
        fn = getattr(app, name, None)
        if callable(fn):
            fn(*args)

    # --- File ---
    m_file = tk.Menu(root_menu, tearoff=0)
    root_menu.add_cascade(label="Файл", menu=m_file)
    m_file.add_command(
        label="Открыть заявку…",
        command=lambda: (go_tab("tab_pdf"), call("_browse_pdf")),
        accelerator="Ctrl+O",
    )
    m_file.add_command(
        label="Извлечь из файла",
        command=lambda: (go_tab("tab_pdf"), call("_run_extract_pdf")),
    )
    m_file.add_separator()
    m_file.add_command(
        label="Журнал пожеланий…",
        command=lambda: call("_open_feedback_journal"),
    )
    m_file.add_separator()
    m_file.add_command(label="Выход", command=app.destroy, accelerator="Alt+F4")

    # --- View (workflow) ---
    m_view = tk.Menu(root_menu, tearoff=0)
    root_menu.add_cascade(label="Вид", menu=m_view)
    for label, attr, accel in (
        ("Заявка", "tab_pdf", "Ctrl+1"),
        ("Расчёт", "tab_calc", "Ctrl+2"),
        ("КП", "tab_kp", "Ctrl+3"),
        ("Заказы", "tab_orders", "Ctrl+4"),
    ):
        m_view.add_command(
            label=label,
            command=lambda a=attr: go_tab(a),
            accelerator=accel,
        )

    # --- Data ---
    m_data = tk.Menu(root_menu, tearoff=0)
    root_menu.add_cascade(label="Данные", menu=m_data)
    for label, attr in (
        ("Марки", "tab_marks"),
        ("Организации", "tab_orgs"),
        ("Справочник испытаний", "tab_tests"),
        ("Программы", "tab_programs"),
        ("История расчётов", "tab_history"),
    ):
        m_data.add_command(label=label, command=lambda a=attr: go_tab(a))
    m_data.add_separator()
    m_data.add_command(
        label="Обновить справочник",
        command=lambda: (go_tab("tab_tests"), call("_load_tests")),
    )

    # --- Tools ---
    m_tools = tk.Menu(root_menu, tearoff=0)
    root_menu.add_cascade(label="Сервис", menu=m_tools)
    m_tools.add_command(label="Сравнение OCR", command=lambda: go_tab("tab_compare"))
    m_tools.add_separator()
    m_tools.add_command(label="Настройки", command=lambda: go_tab("tab_settings"))
    m_tools.add_separator()
    m_tools.add_command(
        label="Просмотр логов…",
        command=lambda: call("_show_log_viewer"),
    )
    m_tools.add_command(
        label="Открыть папку логов…",
        command=lambda: call("_open_logs_folder"),
    )

    # --- Help ---
    m_help = tk.Menu(root_menu, tearoff=0)
    root_menu.add_cascade(label="Справка", menu=m_help)
    m_help.add_command(
        label="О программе",
        command=lambda: messagebox.showinfo(
            "Lab_request",
            "Lab_request — обработка заявок на испытания кабелей.\n\n"
            "Цикл: заявка → расчёт → КП → заказ / пакет документов.\n"
            "Меню «Данные» — справочники; «Сервис» — настройки.\n"
            "Файл → Журнал пожеланий — обратная связь (уезжает в экспорт prod).\n"
            "Логи: data/logs и %LOCALAPPDATA%\\Lab_request\\logs.",
            parent=app,
        ),
    )

    def _bind_goto(event: tk.Event, attr: str) -> str:
        go_tab(attr)
        return "break"

    app.bind_all("<Control-o>", lambda e: (go_tab("tab_pdf"), call("_browse_pdf")) or "break")
    app.bind_all("<Control-O>", lambda e: (go_tab("tab_pdf"), call("_browse_pdf")) or "break")
    app.bind_all("<Control-Key-1>", lambda e: _bind_goto(e, "tab_pdf"))
    app.bind_all("<Control-Key-2>", lambda e: _bind_goto(e, "tab_calc"))
    app.bind_all("<Control-Key-3>", lambda e: _bind_goto(e, "tab_kp"))
    app.bind_all("<Control-Key-4>", lambda e: _bind_goto(e, "tab_orders"))
    return root_menu
