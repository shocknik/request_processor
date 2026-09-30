"""Mixin: ProgramsTabMixin — domain methods for Lab_request GUI."""

from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from ...logging_setup import get_logger

_log = get_logger("ui.gui")

class ProgramsTabMixin:
    def _build_programs_tab(self) -> None:
        """Программы испытаний: импорт DOCX, просмотр, → в расчёт."""
        toolbar = ttk.Frame(self.tab_programs)
        toolbar.pack(fill="x", pady=(0, 8))
        ttk.Button(toolbar, text="Обновить", command=self._load_programs_table).pack(side="left")
        self._accent_button(toolbar, "Импорт DOCX…", self._import_program_docx).pack(
            side="left", padx=(8, 0)
        )
        ttk.Button(toolbar, text="→ В расчёт", command=self._apply_program_to_calc).pack(
            side="left", padx=(8, 0)
        )
        ttk.Button(toolbar, text="Сопоставить прайс", command=self._match_program_price).pack(
            side="left", padx=(8, 0)
        )
        ttk.Button(toolbar, text="Удалить…", command=self._delete_selected_program).pack(
            side="left", padx=(8, 0)
        )
        self.programs_search_var = tk.StringVar()
        ttk.Entry(toolbar, textvariable=self.programs_search_var, width=28).pack(
            side="left", padx=(12, 0), ipady=2
        )
        ttk.Button(toolbar, text="Поиск", command=self._load_programs_table).pack(
            side="left", padx=(4, 0)
        )

        paned = ttk.PanedWindow(self.tab_programs, orient="horizontal")
        paned.pack(fill="both", expand=True)

        left = ttk.LabelFrame(paned, text="Программы", padding=8, style="Card.TLabelframe")
        paned.add(left, weight=2)
        cols = ("id", "type", "items", "mark", "name")
        self.programs_tree = ttk.Treeview(
            left, columns=cols, show="headings", height=16, selectmode="browse"
        )
        for col, title, w in (
            ("id", "№", 40),
            ("type", "Вид", 100),
            ("items", "Пунктов", 60),
            ("mark", "Марка", 160),
            ("name", "Название", 280),
        ):
            self.programs_tree.heading(col, text=title)
            self.programs_tree.column(col, width=w, anchor="w")
        self.programs_tree.pack(fill="both", expand=True)
        self.programs_tree.bind("<<TreeviewSelect>>", lambda _e: self._show_program_details())

        right = ttk.LabelFrame(paned, text="Позиции программы", padding=8, style="Card.TLabelframe")
        paned.add(right, weight=3)
        icols = ("n", "name", "req", "meth", "price")
        self.program_items_tree = ttk.Treeview(
            right, columns=icols, show="headings", height=16
        )
        for col, title, w in (
            ("n", "№", 40),
            ("name", "Испытание", 260),
            ("req", "П. треб.", 90),
            ("meth", "П. метода", 90),
            ("price", "Код прайса", 120),
        ):
            self.program_items_tree.heading(col, text=title)
            self.program_items_tree.column(col, width=w, anchor="w")
        self.program_items_tree.pack(fill="both", expand=True)
        self.program_info_var = tk.StringVar(value="Выберите программу")
        ttk.Label(right, textvariable=self.program_info_var, style="Muted.TLabel").pack(
            anchor="w", pady=(6, 0)
        )

        # S5: нормы / aliases — компактная полоса под таблицей
        norm_bar = ttk.LabelFrame(
            self.tab_programs,
            text="Нормы и синонимы (S5)",
            padding=8,
            style="Card.TLabelframe",
        )
        norm_bar.pack(fill="x", pady=(8, 0))
        ttk.Button(
            norm_bar, text="Импорт ТУ .txt…", command=self._import_norm_text_dialog
        ).pack(side="left")
        ttk.Button(
            norm_bar, text="Aliases из YAML…", command=self._import_aliases_yaml_dialog
        ).pack(side="left", padx=(8, 0))
        ttk.Button(norm_bar, text="Список норм", command=self._show_norms_summary).pack(
            side="left", padx=(8, 0)
        )
        ttk.Label(
            norm_bar,
            text="Корпус ТУ локально (raw_text), не в git · migrate создаёт seed",
            style="Muted.TLabel",
        ).pack(side="left", padx=12)

    def _load_programs_table(self) -> None:
        if not hasattr(self, "programs_tree"):
            return
        from ...persistence.sqlite_repo import list_test_programs

        for item in self.programs_tree.get_children():
            self.programs_tree.delete(item)
        search = (
            self.programs_search_var.get().strip() or None
            if hasattr(self, "programs_search_var")
            else None
        )
        for row in list_test_programs(search=search, limit=200, db_path=self.db_path):
            self.programs_tree.insert(
                "",
                "end",
                iid=str(row["id"]),
                values=(
                    row["id"],
                    (row.get("test_type") or "—")[:24],
                    row.get("items_count") or 0,
                    (row.get("cable_mark_text") or "—")[:40],
                    (row.get("name") or "")[:80],
                ),
            )

    def _show_program_details(self) -> None:
        if not hasattr(self, "program_items_tree"):
            return
        sel = self.programs_tree.selection()
        for item in self.program_items_tree.get_children():
            self.program_items_tree.delete(item)
        if not sel:
            return
        from ...persistence.sqlite_repo import get_test_program

        prog = get_test_program(int(sel[0]), db_path=self.db_path)
        if not prog:
            self.program_info_var.set("Не найдено")
            return
        marks_preview = (prog.get("cable_mark_text") or "").replace("\n", " · ")
        if len(marks_preview) > 100:
            marks_preview = marks_preview[:100] + "…"
        items = prog.get("items") or []
        matched_n = sum(1 for it in items if (it.get("price_test_code") or "").strip())
        total_n = len(items)
        from ...mapping.program_price_matcher import match_rate_summary

        rate_txt = match_rate_summary(matched_n, total_n)
        self.program_info_var.set(
            f"{rate_txt}  |  "
            f"Марки: {marks_preview or '—'}  |  "
            f"ТУ: {prog.get('tu_ref') or '—'}  |  "
            f"{(prog.get('source_path') or '')[-40:]}"
        )
        for it in items:
            self.program_items_tree.insert(
                "",
                "end",
                values=(
                    it.get("sort_order"),
                    (it.get("name") or "")[:80],
                    (it.get("requirement_clause") or "")[:20],
                    (it.get("method_clause") or "")[:20],
                    it.get("price_test_code") or "—",
                ),
            )

    def _import_program_docx(self) -> None:
        path = filedialog.askopenfilename(
            title="Программа испытаний (Word)",
            filetypes=[("Word", "*.docx"), ("Все", "*.*")],
        )
        if not path:
            return
        self.status.set("Импорт программы…")
        self.update_idletasks()
        db_path = self.db_path

        from ..bg_job import run_bg_job

        def work() -> dict:
            from ...generation.program_importer import import_program_from_docx

            return import_program_from_docx(path, db_path=db_path)

        def on_ok(result: dict) -> None:
            self._load_programs_table()
            self.programs_tree.selection_set(str(result["program_id"]))
            self._show_program_details()
            self.status.set(
                f"Программа #{result['program_id']}: {result['items_count']} пунктов"
            )
            _log.info(
                "imported program id=%s items=%s from %s",
                result["program_id"],
                result["items_count"],
                path,
                extra={"tag": "Программа"},
            )
            m = int(result.get("matched") or 0)
            u = int(result.get("unmatched") or 0)
            from ...mapping.program_price_matcher import match_rate_summary

            rate = result.get("summary") or match_rate_summary(m, m + u)
            messagebox.showinfo(
                "Программа импортирована",
                f"id={result['program_id']}\n"
                f"{result['name'][:100]}\n\n"
                f"Пунктов: {result['items_count']}\n"
                f"Прайс: {rate}",
            )

        def on_err(exc: BaseException) -> None:
            messagebox.showerror("Программы", str(exc))
            self.status.set("Ошибка импорта программы")

        run_bg_job(
            self,
            work,
            on_success=on_ok,
            on_error=on_err,
            name="import_program",
            tag="Программа",
        )

    def _match_program_price(self) -> None:
        sel = self.programs_tree.selection()
        if not sel:
            messagebox.showinfo("Программы", "Выберите программу.")
            return
        from ...persistence.sqlite_repo import match_program_items_to_price

        # overwrite: пересчёт (в т.ч. исправление ложных codes)
        stats = match_program_items_to_price(
            int(sel[0]), db_path=self.db_path, overwrite=True
        )
        self._show_program_details()
        summary = stats.get("summary") or (
            f"matched={stats['matched']} unmatched={stats['unmatched']}"
        )
        self.status.set(f"Прайс: {summary}")
        messagebox.showinfo(
            "Сопоставление с прайсом",
            f"{summary}\n\n"
            f"Сопоставлено: {stats['matched']}\n"
            f"Без кода: {stats['unmatched']}\n"
            f"Всего пунктов: {stats.get('total', stats['matched'] + stats['unmatched'])}",
        )

    def _delete_selected_program(self) -> None:
        sel = self.programs_tree.selection()
        if not sel:
            return
        pid = int(sel[0])
        if not messagebox.askyesno("Программы", f"Удалить программу №{pid}?"):
            return
        from ...persistence.sqlite_repo import delete_test_program

        delete_test_program(pid, db_path=self.db_path)
        self._load_programs_table()
        for item in self.program_items_tree.get_children():
            self.program_items_tree.delete(item)
        self.status.set(f"Программа #{pid} удалена")

    def _apply_program_to_calc(self) -> None:
        """Отмечает в расчёте испытания с известным price_test_code."""
        sel = self.programs_tree.selection()
        if not sel:
            messagebox.showinfo("Программы", "Выберите программу.")
            return
        from ...persistence.sqlite_repo import get_test_program

        prog = get_test_program(int(sel[0]), db_path=self.db_path)
        if not prog:
            return
        codes: list[str] = []
        for it in prog.get("items") or []:
            code = (it.get("price_test_code") or "").strip()
            if code:
                codes.append(code)
        if not codes:
            messagebox.showwarning(
                "Программы",
                "Нет сопоставленных кодов прайса.\n"
                "Нажмите «Сопоставить прайс» или задайте price_test_code.",
            )
            return
        # mark from program if empty
        if not self.mark_var.get().strip() and prog.get("cable_mark_text"):
            self.mark_var.set(prog["cable_mark_text"])
        if self.notebook:
            self.notebook.select(self.tab_calc)
        self._refresh_calc_picker()
        added = 0
        for code in codes:
            if any(e.code == code for e in self._calc_entries):
                continue
            if code in self._tests_by_code:
                self._add_test_to_calc(code)
                added += 1
        self._refresh_calc_picker()
        self.status.set(f"Из программы: +{added} испытаний (кодов {len(codes)})")
        messagebox.showinfo(
            "В расчёт",
            f"Добавлено: {added}\n"
            f"Кодов с прайсом в программе: {len(codes)}\n"
            f"Марка: {self.mark_var.get() or '—'}",
        )

