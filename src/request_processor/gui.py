"""
gui.py — минимальный графический интерфейс (tkinter).

Запуск: request-processor gui
"""

from __future__ import annotations

import json
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, simpledialog, ttk

from .cost_calculator import calculate_cost, format_breakdown
from .models import ClimaticTestSettings, TestItemCreate
from .pdf_extractor import DEFAULT_OCR_DPI, extract_from_pdf
from .sqlite_repo import (
    DB_PATH_DEFAULT,
    add_test_item,
    build_default_hours_map,
    get_climatic_settings,
    get_recent_calculations,
    init_db,
    list_cable_marks,
    list_test_items,
    save_calculation,
    save_cable_marks_from_matches,
    save_climatic_settings,
)


class RequestProcessorApp(tk.Tk):
    def __init__(self, db_path: Path = DB_PATH_DEFAULT) -> None:
        super().__init__()
        self.db_path = db_path
        self.title("request-processor")
        self.geometry("980x700")
        self.minsize(800, 560)

        self._ensure_db()
        self._build_ui()
        self._load_history()
        self._load_tests()
        self._load_cable_marks()
        self._load_settings()

    def _ensure_db(self) -> None:
        if not self.db_path.exists():
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            init_db(self.db_path)
        else:
            from .sqlite_repo import _seed_default_settings, migrate_db

            migrate_db(self.db_path)
            _seed_default_settings(self.db_path)

    def _build_ui(self) -> None:
        self.status = tk.StringVar(value="Готово")
        status_bar = ttk.Label(self, textvariable=self.status, anchor="w", padding=(8, 4))
        status_bar.pack(side="bottom", fill="x")

        notebook = ttk.Notebook(self, padding=8)
        notebook.pack(fill="both", expand=True)

        self.tab_calc = ttk.Frame(notebook, padding=8)
        self.tab_pdf = ttk.Frame(notebook, padding=8)
        self.tab_marks = ttk.Frame(notebook, padding=8)
        self.tab_history = ttk.Frame(notebook, padding=8)
        self.tab_tests = ttk.Frame(notebook, padding=8)
        self.tab_settings = ttk.Frame(notebook, padding=8)

        notebook.add(self.tab_calc, text="Расчёт")
        notebook.add(self.tab_pdf, text="PDF")
        notebook.add(self.tab_marks, text="Марки")
        notebook.add(self.tab_history, text="История")
        notebook.add(self.tab_tests, text="Справочник")
        notebook.add(self.tab_settings, text="Настройки")

        self._build_calc_tab()
        self._build_pdf_tab()
        self._build_marks_tab()
        self._build_history_tab()
        self._build_tests_tab()
        self._build_settings_tab()

    def _build_calc_tab(self) -> None:
        form = ttk.Frame(self.tab_calc)
        form.pack(fill="x")

        ttk.Label(form, text="Марка кабеля:").grid(row=0, column=0, sticky="w", pady=4)
        self.mark_var = tk.StringVar()
        ttk.Entry(form, textvariable=self.mark_var, width=70).grid(
            row=0, column=1, sticky="ew", padx=(8, 0), pady=4
        )

        ttk.Label(form, text="Коды испытаний:").grid(row=1, column=0, sticky="w", pady=4)
        self.tests_var = tk.StringVar()
        ttk.Entry(form, textvariable=self.tests_var, width=70).grid(
            row=1, column=1, sticky="ew", padx=(8, 0), pady=4
        )
        ttk.Label(form, text="через запятую", font=("", 8)).grid(row=2, column=1, sticky="w")

        ttk.Label(form, text="Часы (переопределение):").grid(row=3, column=0, sticky="nw", pady=4)
        self.hours_text = scrolledtext.ScrolledText(form, height=4, width=50)
        self.hours_text.grid(row=3, column=1, sticky="ew", padx=(8, 0), pady=4)
        ttk.Label(
            form,
            text="пусто = из настроек; иначе код=часы на строку",
            font=("", 8),
        ).grid(row=4, column=1, sticky="w")

        form.columnconfigure(1, weight=1)

        btns = ttk.Frame(self.tab_calc)
        btns.pack(fill="x", pady=(8, 4))
        ttk.Button(btns, text="Рассчитать", command=self._run_calculate).pack(side="left")
        ttk.Button(btns, text="Очистить", command=self._clear_calc).pack(side="left", padx=8)

        self.calc_output = scrolledtext.ScrolledText(self.tab_calc, height=22, state="disabled")
        self.calc_output.pack(fill="both", expand=True, pady=(8, 0))

    def _build_pdf_tab(self) -> None:
        top = ttk.Frame(self.tab_pdf)
        top.pack(fill="x")

        self.pdf_path_var = tk.StringVar()
        ttk.Entry(top, textvariable=self.pdf_path_var).pack(side="left", fill="x", expand=True)
        ttk.Button(top, text="Обзор…", command=self._browse_pdf).pack(side="left", padx=6)
        ttk.Button(top, text="Извлечь", command=self._run_extract_pdf).pack(side="left")

        opts = ttk.Frame(self.tab_pdf)
        opts.pack(fill="x", pady=4)
        self.ocr_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(opts, text="OCR для сканов", variable=self.ocr_var).pack(side="left")
        ttk.Label(opts, text=f"DPI: {DEFAULT_OCR_DPI} (быстрый режим)").pack(side="left", padx=12)
        self.save_marks_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(opts, text="Сохранять марки в БД", variable=self.save_marks_var).pack(
            side="left"
        )

        mid = ttk.Frame(self.tab_pdf)
        mid.pack(fill="both", expand=True, pady=8)

        left = ttk.LabelFrame(mid, text="Найденные марки", padding=6)
        left.pack(side="left", fill="both", expand=True)

        self.marks_list = tk.Listbox(left, height=12)
        self.marks_list.pack(fill="both", expand=True)
        ttk.Button(left, text="→ В расчёт", command=self._use_mark_in_calc).pack(pady=(6, 0))

        right = ttk.LabelFrame(mid, text="Сводка", padding=6)
        right.pack(side="left", fill="both", expand=True, padx=(8, 0))

        self.pdf_output = scrolledtext.ScrolledText(right, height=12, state="disabled")
        self.pdf_output.pack(fill="both", expand=True)

    def _build_marks_tab(self) -> None:
        toolbar = ttk.Frame(self.tab_marks)
        toolbar.pack(fill="x")
        ttk.Button(toolbar, text="Обновить", command=self._load_cable_marks).pack(side="left")
        self.marks_search_var = tk.StringVar()
        ttk.Entry(toolbar, textvariable=self.marks_search_var, width=30).pack(
            side="left", padx=8
        )
        ttk.Button(toolbar, text="Поиск", command=self._load_cable_marks).pack(side="left")

        cols = (
            "full_mark",
            "brand",
            "fire_class",
            "cores",
            "element",
            "size",
            "document",
        )
        self.cable_marks_tree = ttk.Treeview(
            self.tab_marks, columns=cols, show="headings", height=20
        )
        headers = (
            ("full_mark", "Полная марка", 260),
            ("brand", "Марка", 80),
            ("fire_class", "Пожарный класс", 90),
            ("cores", "ТПЖ", 50),
            ("element", "Элемент", 70),
            ("size", "Размер", 80),
            ("document", "Документ", 180),
        )
        for col, title, width in headers:
            self.cable_marks_tree.heading(col, text=title)
            self.cable_marks_tree.column(col, width=width, anchor="w")
        self.cable_marks_tree.pack(fill="both", expand=True, pady=(8, 0))
        ttk.Button(
            self.tab_marks, text="→ В расчёт", command=self._use_db_mark_in_calc
        ).pack(anchor="w", pady=6)

    def _build_history_tab(self) -> None:
        toolbar = ttk.Frame(self.tab_history)
        toolbar.pack(fill="x")
        ttk.Button(toolbar, text="Обновить", command=self._load_history).pack(side="left")

        cols = ("id", "created_at", "mark", "total", "source")
        self.history_tree = ttk.Treeview(
            self.tab_history, columns=cols, show="headings", height=18
        )
        for col, title, width in (
            ("id", "ID", 50),
            ("created_at", "Дата", 140),
            ("mark", "Марка", 360),
            ("total", "С НДС, ₽", 110),
            ("source", "Источник", 80),
        ):
            self.history_tree.heading(col, text=title)
            self.history_tree.column(col, width=width, anchor="w")
        self.history_tree.pack(fill="both", expand=True, pady=(8, 0))

    def _build_tests_tab(self) -> None:
        toolbar = ttk.Frame(self.tab_tests)
        toolbar.pack(fill="x")
        ttk.Button(toolbar, text="Обновить", command=self._load_tests).pack(side="left")
        ttk.Button(toolbar, text="Добавить испытание…", command=self._add_test_dialog).pack(
            side="left", padx=8
        )

        cols = ("code", "name", "base_cost", "rule_type", "default_hours")
        self.tests_tree = ttk.Treeview(self.tab_tests, columns=cols, show="headings", height=20)
        for col, title, width in (
            ("code", "Код", 140),
            ("name", "Наименование", 360),
            ("base_cost", "Цена", 70),
            ("rule_type", "Правило", 90),
            ("default_hours", "Часы", 60),
        ):
            self.tests_tree.heading(col, text=title)
            self.tests_tree.column(col, width=width, anchor="w")
        self.tests_tree.pack(fill="both", expand=True, pady=(8, 0))

        ttk.Button(
            self.tab_tests, text="Вставить код в расчёт", command=self._use_test_code
        ).pack(anchor="w", pady=6)

    def _build_settings_tab(self) -> None:
        frame = ttk.LabelFrame(
            self.tab_settings,
            text="Время выдержки климатических испытаний (часы)",
            padding=12,
        )
        frame.pack(fill="x", pady=8)

        self.setting_vars: dict[str, tk.StringVar] = {}
        for row, (key, label, hint) in enumerate(
            (
                ("temp_high", "Повышенная температура", "temp_high"),
                ("humidity", "Повышенная влажность", "humidity"),
                ("solar_radiation", "Солнечная радиация", "solar_radiation"),
            )
        ):
            ttk.Label(frame, text=label + ":").grid(row=row, column=0, sticky="w", pady=6)
            var = tk.StringVar()
            self.setting_vars[key] = var
            ttk.Entry(frame, textvariable=var, width=12).grid(
                row=row, column=1, sticky="w", padx=(8, 0), pady=6
            )
            ttk.Label(frame, text=f"ключ: {hint}", font=("", 8)).grid(
                row=row, column=2, sticky="w", padx=8
            )

        ttk.Button(frame, text="Сохранить настройки", command=self._save_settings).grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(12, 0)
        )

        hint = scrolledtext.ScrolledText(self.tab_settings, height=10, state="disabled")
        hint.pack(fill="both", expand=True, pady=8)
        self._set_text(
            hint,
            "Настройки используются при расчёте, если часы не указаны вручную.\n\n"
            "Для испытаний с rule_type=time_based можно задать default_hours "
            "при добавлении в справочник.\n\n"
            "Климатические ключи: temp_high, humidity, solar_radiation.",
        )

    def _parse_hours(self) -> dict[str, float]:
        hours: dict[str, float] = {}
        for line in self.hours_text.get("1.0", "end").splitlines():
            line = line.strip()
            if not line or "=" not in line:
                continue
            key, value = line.split("=", 1)
            try:
                hours[key.strip()] = float(value.strip())
            except ValueError:
                pass
        return hours

    def _resolve_hours(self) -> dict[str, float]:
        manual = self._parse_hours()
        defaults = build_default_hours_map(self.db_path)
        merged = {**defaults, **manual}
        return merged

    def _set_text(self, widget: scrolledtext.ScrolledText, content: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", content)
        widget.configure(state="disabled")

    def _run_calculate(self) -> None:
        mark = self.mark_var.get().strip()
        tests_raw = self.tests_var.get().strip()
        if not mark or not tests_raw:
            messagebox.showwarning("Расчёт", "Укажите марку и коды испытаний.")
            return

        test_list = [t.strip() for t in tests_raw.split(",") if t.strip()]
        hours = self._resolve_hours()
        self.status.set("Расчёт…")

        def work() -> None:
            try:
                calc = calculate_cost(mark, test_list, hours, self.db_path)
                calc_id = save_calculation(calc, self.db_path)
                text = format_breakdown(calc) + f"\n\n✓ Сохранено в БД (id={calc_id})"
                self.after(0, lambda: self._set_text(self.calc_output, text))
                self.after(0, self._load_history)
                self.after(0, lambda: self.status.set("Расчёт выполнен"))
            except Exception as exc:
                self.after(0, lambda: messagebox.showerror("Ошибка расчёта", str(exc)))
                self.after(0, lambda: self.status.set("Ошибка"))

        threading.Thread(target=work, daemon=True).start()

    def _clear_calc(self) -> None:
        self.mark_var.set("")
        self.tests_var.set("")
        self.hours_text.delete("1.0", "end")
        self._set_text(self.calc_output, "")

    def _browse_pdf(self) -> None:
        path = filedialog.askopenfilename(
            title="Выберите PDF",
            filetypes=[("PDF", "*.pdf"), ("Все файлы", "*.*")],
        )
        if path:
            self.pdf_path_var.set(path)

    def _run_extract_pdf(self) -> None:
        pdf_path = self.pdf_path_var.get().strip()
        if not pdf_path:
            messagebox.showwarning("PDF", "Выберите файл.")
            return

        self.status.set("Извлечение PDF…")

        def work() -> None:
            try:
                result = extract_from_pdf(
                    Path(pdf_path),
                    use_ocr=self.ocr_var.get(),
                )
                out_dir = Path("data/extracted")
                out_dir.mkdir(parents=True, exist_ok=True)
                out_file = out_dir / f"{Path(pdf_path).stem}.json"
                out_file.write_text(
                    result.model_dump_json(indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )

                db_stats = {"saved": 0, "errors": 0}
                if self.save_marks_var.get() and result.cable_marks:
                    db_stats = save_cable_marks_from_matches(
                        result.cable_marks,
                        source=str(Path(pdf_path).resolve()),
                        db_path=self.db_path,
                    )

                summary = [
                    f"Файл: {Path(pdf_path).name}",
                    f"Страниц: {result.page_count}",
                    f"Символов: {len(result.text)}",
                    f"Таблиц: {len(result.tables)}",
                    f"Марок: {len(result.cable_marks)}",
                    f"Скан: {'да' if result.is_scanned else 'нет'}",
                    f"OCR: {'да' if result.ocr_used else 'нет'}",
                    f"В БД сохранено: {db_stats['saved']}",
                    f"JSON: {out_file}",
                ]

                def update_ui() -> None:
                    self.marks_list.delete(0, "end")
                    for m in result.cable_marks:
                        self.marks_list.insert("end", m.mark)
                    self._set_text(self.pdf_output, "\n".join(summary))
                    self._load_cable_marks()
                    self.status.set("PDF обработан")

                self.after(0, update_ui)
            except Exception as exc:
                self.after(0, lambda: messagebox.showerror("Ошибка PDF", str(exc)))
                self.after(0, lambda: self.status.set("Ошибка"))

        threading.Thread(target=work, daemon=True).start()

    def _use_mark_in_calc(self) -> None:
        sel = self.marks_list.curselection()
        if not sel:
            messagebox.showinfo("Марка", "Выберите марку из списка.")
            return
        self.mark_var.set(self.marks_list.get(sel[0]))
        self.status.set("Марка подставлена во вкладку «Расчёт»")

    def _use_db_mark_in_calc(self) -> None:
        sel = self.cable_marks_tree.selection()
        if not sel:
            messagebox.showinfo("Марка", "Выберите марку из таблицы.")
            return
        self.mark_var.set(self.cable_marks_tree.item(sel[0], "values")[0])
        self.status.set("Марка из БД подставлена в расчёт")

    def _load_history(self) -> None:
        for item in self.history_tree.get_children():
            self.history_tree.delete(item)
        for row in get_recent_calculations(50, self.db_path):
            self.history_tree.insert(
                "",
                "end",
                values=(
                    row["id"],
                    row["created_at"][:16],
                    row["mark"][:80],
                    f"{row['total_cost_with_vat']:.2f}",
                    row["source"],
                ),
            )

    def _load_tests(self) -> None:
        for item in self.tests_tree.get_children():
            self.tests_tree.delete(item)
        for row in list_test_items(limit=300, db_path=self.db_path):
            rule_params = json.loads(row.get("rule_params") or "{}")
            default_h = rule_params.get("default_hours", "")
            self.tests_tree.insert(
                "",
                "end",
                values=(
                    row["code"],
                    row["name"][:60],
                    f"{row['base_cost']:.0f}",
                    row["rule_type"],
                    default_h,
                ),
            )

    def _load_cable_marks(self) -> None:
        for item in self.cable_marks_tree.get_children():
            self.cable_marks_tree.delete(item)
        search = self.marks_search_var.get().strip() or None
        for row in list_cable_marks(search=search, limit=500, db_path=self.db_path):
            unit = "мм²" if row.get("size_unit") == "mm2" else "мм"
            self.cable_marks_tree.insert(
                "",
                "end",
                values=(
                    row["full_mark"],
                    row["brand"],
                    row.get("fire_class") or "",
                    row["cores_count"],
                    row.get("structural_element_type") or "",
                    f"{row['characteristic_size']} {unit}",
                    (row.get("document") or "")[:50],
                ),
            )

    def _load_settings(self) -> None:
        settings = get_climatic_settings(self.db_path) or ClimaticTestSettings()
        for key, var in self.setting_vars.items():
            var.set(str(getattr(settings, key)))

    def _save_settings(self) -> None:
        try:
            settings = ClimaticTestSettings(
                temp_high=float(self.setting_vars["temp_high"].get()),
                humidity=float(self.setting_vars["humidity"].get()),
                solar_radiation=float(self.setting_vars["solar_radiation"].get()),
            )
        except ValueError:
            messagebox.showerror("Настройки", "Укажите корректные числа часов.")
            return
        save_climatic_settings(settings, self.db_path)
        self.status.set("Настройки выдержки сохранены")

    def _add_test_dialog(self) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("Новое испытание")
        dialog.geometry("480x360")
        dialog.transient(self)
        dialog.grab_set()

        fields: dict[str, tk.Variable] = {
            "code": tk.StringVar(),
            "name": tk.StringVar(),
            "base_cost": tk.StringVar(value="100"),
            "category": tk.StringVar(value="Внешние воздействующие факторы"),
            "rule_type": tk.StringVar(value="fixed"),
            "default_hours": tk.StringVar(value="2"),
            "hours_key": tk.StringVar(),
            "cost_per_hour": tk.StringVar(value="0"),
        }

        row = 0
        for label, key in (
            ("Код (slug):", "code"),
            ("Наименование:", "name"),
            ("Базовая цена:", "base_cost"),
            ("Категория:", "category"),
        ):
            ttk.Label(dialog, text=label).grid(row=row, column=0, sticky="w", padx=8, pady=4)
            ttk.Entry(dialog, textvariable=fields[key], width=40).grid(
                row=row, column=1, sticky="ew", padx=8, pady=4
            )
            row += 1

        ttk.Label(dialog, text="Правило:").grid(row=row, column=0, sticky="w", padx=8, pady=4)
        ttk.Combobox(
            dialog,
            textvariable=fields["rule_type"],
            values=["fixed", "per_core", "per_group", "time_based"],
            state="readonly",
            width=18,
        ).grid(row=row, column=1, sticky="w", padx=8, pady=4)
        row += 1

        ttk.Label(dialog, text="Ключ часов:").grid(row=row, column=0, sticky="w", padx=8, pady=4)
        ttk.Entry(dialog, textvariable=fields["hours_key"], width=40).grid(
            row=row, column=1, sticky="ew", padx=8, pady=4
        )
        row += 1

        ttk.Label(dialog, text="Часы выдержки:").grid(row=row, column=0, sticky="w", padx=8, pady=4)
        ttk.Entry(dialog, textvariable=fields["default_hours"], width=40).grid(
            row=row, column=1, sticky="ew", padx=8, pady=4
        )
        row += 1

        ttk.Label(dialog, text="Цена за час:").grid(row=row, column=0, sticky="w", padx=8, pady=4)
        ttk.Entry(dialog, textvariable=fields["cost_per_hour"], width=40).grid(
            row=row, column=1, sticky="ew", padx=8, pady=4
        )
        row += 1

        def save() -> None:
            code = fields["code"].get().strip()
            if not code:
                messagebox.showwarning("Испытание", "Укажите код.", parent=dialog)
                return
            rule_params: dict = {}
            if fields["rule_type"].get() == "time_based":
                hours_key = fields["hours_key"].get().strip() or code
                rule_params = {
                    "hours_key": hours_key,
                    "default_hours": float(fields["default_hours"].get()),
                    "cost_per_hour": float(fields["cost_per_hour"].get()),
                }
            try:
                item = TestItemCreate(
                    code=code,
                    name=fields["name"].get().strip() or code,
                    base_cost=float(fields["base_cost"].get()),
                    category=fields["category"].get().strip(),
                    rule_type=fields["rule_type"].get(),  # type: ignore[arg-type]
                    rule_params=rule_params,
                )
                add_test_item(item, self.db_path)
            except Exception as exc:
                messagebox.showerror("Ошибка", str(exc), parent=dialog)
                return
            dialog.destroy()
            self._load_tests()
            self.status.set(f"Испытание {code} добавлено")

        ttk.Button(dialog, text="Сохранить", command=save).grid(
            row=row, column=0, columnspan=2, pady=12
        )
        dialog.columnconfigure(1, weight=1)

    def _use_test_code(self) -> None:
        sel = self.tests_tree.selection()
        if not sel:
            messagebox.showinfo("Справочник", "Выберите испытание.")
            return
        code = self.tests_tree.item(sel[0], "values")[0]
        current = self.tests_var.get().strip()
        self.tests_var.set(f"{current},{code}" if current else code)
        self.status.set(f"Код {code} добавлен в расчёт")


def main() -> None:
    app = RequestProcessorApp()
    app.mainloop()


if __name__ == "__main__":
    main()