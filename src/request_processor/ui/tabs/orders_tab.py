"""Mixin: OrdersTabMixin — domain methods for Lab_request GUI."""

from __future__ import annotations

import json
import re
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, simpledialog, ttk

from ...calculation.climatic_tests import climatic_settings_fields, is_climatic_code
from ...calculation.test_rules import (
    CATEGORY_COLORS,
    CATEGORY_SHORT,
    category_sort_key,
    rule_type_label,
)
from ...logging_setup import get_logger
from ...parsing.cable_mark_parser import parse_cable_mark_record
from ...calculation.cost_calculator import calculate_cost, format_breakdown
from ...validation.extraction_validator import apply_operator_edits, validate_extraction
from ...mapping.requirement_mapper import map_requirements_to_tests
from ...models import (
    AssistantLlmSettings,
    DocumentPackSettings,
    CableMarkMatch,
    ClimaticTestSettings,
    FieldStatus,
    MarkValidation,
    PdfExtractionResult,
    TestItemCreate,
    ValidationReport,
)
from ...extraction.test_type_extractor import (
    TEST_TYPE_OPTIONS,
    build_kp_subject,
    detect_test_type,
    format_test_type_label,
)
from ...assistant.feedback import AssistantFeedbackEvent, append_assistant_feedback
from ...assistant.models import AssistantContext
from ...extraction.pdf_extractor import (
    DEFAULT_OCR_DPI,
    EASYOCR_OCR_DPI,
    SCAN_OCR_DPI,
)
from ..theme import (
    COLORS,
    apply_fluent_theme,
    enable_windows_dpi_awareness,
    fit_window_to_screen,
    make_primary_button,
    make_secondary_button,
)
from ..state import ORG_TYPE_LABELS, ORG_TYPE_VALUES, CalcTestEntry, ExtractionDraft
from ...generation.kp_generator import format_money, generate_kp_from_db, proposal_from_calculations
from ...persistence.sqlite_repo import (
    DB_PATH_DEFAULT,
    GENERATED_DIR_DEFAULT,
    add_test_item,
    build_default_hours_map,
    get_calculations_for_kp,
    get_assistant_llm_settings,
    get_climatic_settings,
    get_document_pack_settings,
    get_last_document_extraction,
    get_organization_by_id,
    get_recent_calculations,
    init_db,
    list_cable_marks,
    list_organizations,
    list_test_items,
    save_calculation,
    save_cable_marks_from_matches,
    save_cable_marks_from_validations,
    save_assistant_llm_settings,
    save_climatic_settings,
    save_document_pack_settings,
    push_recent_pack_path,
    save_document_extraction,
    save_organizations_from_extraction,
    update_organization,
    create_order_from_kp,
    list_orders,
    get_order_details,
    list_test_applications,
    list_test_mappings,
    add_test_mapping,
    update_test_mapping,
    delete_test_mapping,
    delete_cable_mark,
    delete_calculation,
    delete_order,
    delete_organization,
    delete_generated_document,
    record_mapping_usage,
    list_test_programs,
    get_test_program,
    delete_test_program,
)

_log = get_logger("ui.gui")

class OrdersTabMixin:
    def _build_orders_tab(self) -> None:
        toolbar = ttk.Frame(self.tab_orders)
        toolbar.pack(fill="x", pady=(0, 8))
        self._accent_button(toolbar, "Сформировать заявку", self._generate_order_application).pack(
            side="left"
        )
        self._accent_button(toolbar, "Пакет документов", self._build_order_document_pack).pack(
            side="left", padx=(8, 0)
        )
        self._secondary_button(
            toolbar, "JSON → protocol_generator", self._export_order_protocol_meta
        ).pack(side="left", padx=(8, 0))
        self._secondary_button(toolbar, "Обновить", self._load_orders_table).pack(
            side="left", padx=(8, 0)
        )
        ttk.Button(toolbar, text="Удалить заказ…", command=self._delete_selected_order).pack(
            side="left", padx=(8, 0)
        )
        orders_more = ttk.Menubutton(toolbar, text="Ещё ▾")
        om = tk.Menu(orders_more, tearoff=0)
        om.add_command(label="Макет протокола (простой)", command=self._generate_order_protocol)
        om.add_command(label="Открыть КП", command=self._open_selected_order_kp)
        om.add_command(label="Открыть заявку", command=self._open_selected_order_application)
        om.add_separator()
        om.add_command(label="Печать КП", command=self._print_selected_order_kp)
        om.add_command(label="Печать заявки", command=self._print_selected_order_application)
        orders_more["menu"] = om
        orders_more.pack(side="left", padx=(8, 0))
        ttk.Label(
            toolbar,
            text="Клик — детали; двойной клик — открыть КП",
            style="Muted.TLabel",
        ).pack(side="right")

        paned = ttk.PanedWindow(self.tab_orders, orient="horizontal")
        paned.pack(fill="both", expand=True)

        left = ttk.LabelFrame(
            paned, text="Сохранённые заказы", padding=8, style="Card.TLabelframe"
        )
        paned.add(left, weight=2)
        cols = ("id", "date", "customer", "marks", "total", "status")
        self.orders_tree = ttk.Treeview(
            left, columns=cols, show="headings", height=16, selectmode="browse"
        )
        for col, title, width, anchor in (
            ("id", "№", 45, "center"),
            ("date", "Дата", 130, "w"),
            ("customer", "Заказчик", 240, "w"),
            ("marks", "Марок", 55, "center"),
            ("total", "С НДС, ₽", 110, "e"),
            ("status", "Статус", 100, "w"),
        ):
            self.orders_tree.heading(col, text=title, anchor=anchor)
            self.orders_tree.column(col, width=width, anchor=anchor)
        self.orders_tree.pack(fill="both", expand=True)
        self.orders_tree.bind("<<TreeviewSelect>>", lambda _e: self._show_order_details())
        self.orders_tree.bind("<Double-Button-1>", lambda _e: self._open_selected_order_kp())
        self.orders_tree.bind(
            "<Button-3>",
            lambda e: self._show_orders_context_menu(e),
        )

        right = ttk.LabelFrame(paned, text="Информация о заказе", padding=8, style="Card.TLabelframe")
        paned.add(right, weight=1)
        self.order_details = self._make_readonly_text(
            right,
            height=20,
            font=("Segoe UI", 10),
            bg="#f8fafc",
            relief="flat",
            padx=8,
            pady=8,
        )
        self.order_details.pack(fill="both", expand=True)

    def _load_orders_table(self) -> None:
        if not hasattr(self, "orders_tree"):
            _log.warning("load_orders_table: no orders_tree widget", extra={"tag": "Заказы"})
            return
        for item in self.orders_tree.get_children():
            self.orders_tree.delete(item)
        status_labels = {
            "kp_generated": "КП готов",
            "draft": "Черновик",
            "completed": "Завершён",
        }
        rows = list_orders(limit=200, db_path=self.db_path)
        for row in rows:
            status = status_labels.get(row.get("status") or "", row.get("status") or "")
            if row.get("application_path"):
                status = f"{status} · заявка" if status else "Заявка готова"
            self.orders_tree.insert(
                "",
                "end",
                iid=str(row["id"]),
                values=(
                    row["id"],
                    (row.get("created_at") or "")[:16].replace("T", " "),
                    (row.get("customer_name") or "—")[:40],
                    row.get("marks_count") or 0,
                    f"{float(row.get('total_with_vat') or 0):,.2f}".replace(",", " "),
                    status,
                ),
            )
        _log.info(
            "orders table loaded n=%s first_ids=%s",
            len(rows),
            [r.get("id") for r in rows[:5]],
            extra={"tag": "Заказы"},
        )

    def _show_order_details(self) -> None:
        if not hasattr(self, "orders_tree"):
            return
        sel = self.orders_tree.selection()
        if not sel:
            return
        details = get_order_details(int(sel[0]), self.db_path)
        if not details:
            _log.warning(
                "order details missing id=%s",
                sel[0],
                extra={"tag": "Заказы"},
            )
            self._set_text(self.order_details, "Заказ не найден.")
            return
        lines = [
            f"Заказ №{details['id']}",
            f"Дата: {(details.get('created_at') or '')[:16].replace('T', ' ')}",
            f"Статус: {details.get('status', '')}",
            "",
            "ЗАКАЗЧИК",
            f"  {details.get('customer_name') or '—'}",
        ]
        if details.get("customer_inn"):
            lines.append(f"  ИНН: {details['customer_inn']}")
        if details.get("customer_address"):
            lines.append(f"  {details['customer_address']}")
        lines.extend(["", "ПРОИЗВОДИТЕЛЬ", f"  {details.get('manufacturer_name') or '—'}"])
        if details.get("manufacturer_inn"):
            lines.append(f"  ИНН: {details['manufacturer_inn']}")
        lines.extend([
            "",
            f"Вид испытаний: {details.get('subject') or '—'}",
            f"Без НДС: {float(details.get('total_without_vat') or 0):,.2f} ₽".replace(",", " "),
            f"С НДС: {float(details.get('total_with_vat') or 0):,.2f} ₽".replace(",", " "),
        ])
        if details.get("source_document"):
            lines.append(f"\nЗаявка: {Path(details['source_document']).name}")
        if details.get("kp_output_path"):
            lines.append(f"КП: {details['kp_output_path']}")
        if details.get("application_path"):
            lines.append(f"Заявка на испытания: {details['application_path']}")
        apps = list_test_applications(order_id=int(sel[0]), limit=5, db_path=self.db_path)
        if apps:
            lines.append("\nИСТОРИЯ ЗАЯВОК (БД):")
            for app in apps:
                created = (app.get("created_at") or "")[:16].replace("T", " ")
                lines.append(
                    f"  • №{app.get('id')} от {created} — {app.get('test_type') or '—'}, "
                    f"марок: {app.get('marks_count') or 0}"
                )
                lines.append(f"    {app.get('output_path') or '—'}")
        if details.get("note"):
            lines.append(f"\nПримечание:\n{details['note']}")
        lines.append("\nМАРКИ:")
        for m in details.get("marks") or []:
            mfg = m.get("manufacturer_name") or details.get("manufacturer_name") or "—"
            lines.append(
                f"  • {m.get('mark')} — {float(m.get('total_with_vat') or 0):,.2f} ₽ "
                f"(производитель: {mfg})".replace(",", " ")
            )
        self._set_text(self.order_details, "\n".join(lines))

    def _get_selected_order_kp_path(self) -> Path | None:
        if not hasattr(self, "orders_tree"):
            _log.warning("get_selected_order_kp: no tree", extra={"tag": "Заказы"})
            return None
        sel = self.orders_tree.selection()
        if not sel:
            _log.info("get_selected_order_kp: no selection", extra={"tag": "Заказы"})
            messagebox.showinfo("Заказы", "Выберите заказ в списке.")
            return None
        details = get_order_details(int(sel[0]), self.db_path)
        if not details or not details.get("kp_output_path"):
            _log.warning(
                "get_selected_order_kp: no kp path order_id=%s details=%s",
                sel[0],
                bool(details),
                extra={"tag": "Заказы"},
            )
            messagebox.showwarning("Заказы", "Файл КП для этого заказа не найден.")
            return None
        path = Path(details["kp_output_path"])
        if not path.exists():
            _log.warning(
                "get_selected_order_kp: file missing order_id=%s path=%s",
                sel[0],
                path,
                extra={"tag": "Заказы"},
            )
            messagebox.showwarning("Заказы", f"Файл не существует:\n{path}")
            return None
        return path

    def _open_selected_order_kp(self) -> None:
        path = self._get_selected_order_kp_path()
        if not path:
            return
        try:
            import os

            os.startfile(str(path))
            self.status.set(f"Открыт КП: {path.name}")
            _log.info("open KP path=%s", path, extra={"tag": "Заказы"})
        except OSError as exc:
            _log.exception("open KP failed path=%s: %s", path, exc, extra={"tag": "Заказы"})
            messagebox.showerror("Заказы", str(exc))

    def _print_selected_order_kp(self) -> None:
        path = self._get_selected_order_kp_path()
        if not path:
            return
        try:
            import os

            os.startfile(str(path), "print")
            self.status.set(f"Печать: {path.name}")
            _log.info("print KP path=%s", path, extra={"tag": "Заказы"})
        except OSError as exc:
            _log.exception("print KP failed path=%s: %s", path, exc, extra={"tag": "Заказы"})
            messagebox.showerror("Печать", f"Не удалось отправить на печать:\n{exc}")

    def _get_selected_order_id(self) -> int | None:
        if not hasattr(self, "orders_tree"):
            _log.warning("get_selected_order_id: no tree", extra={"tag": "Заказы"})
            return None
        sel = self.orders_tree.selection()
        if not sel:
            _log.info("get_selected_order_id: no selection", extra={"tag": "Заказы"})
            messagebox.showinfo("Заказы", "Выберите заказ в списке.")
            return None
        try:
            oid = int(sel[0])
        except (TypeError, ValueError):
            _log.warning(
                "get_selected_order_id: bad iid=%r",
                sel[0],
                extra={"tag": "Заказы"},
            )
            return None
        _log.debug("get_selected_order_id id=%s", oid, extra={"tag": "Заказы"})
        return oid

    def _get_selected_order_application_path(self) -> Path | None:
        order_id = self._get_selected_order_id()
        if order_id is None:
            return None
        details = get_order_details(order_id, self.db_path)
        if not details or not details.get("application_path"):
            _log.warning(
                "application path missing order_id=%s",
                order_id,
                extra={"tag": "Заказы"},
            )
            messagebox.showwarning(
                "Заказы",
                "Заявка на испытания для этого заказа ещё не сформирована.\n"
                "Нажмите «Сформировать заявку».",
            )
            return None
        path = Path(details["application_path"])
        if not path.exists():
            _log.warning(
                "application file missing order_id=%s path=%s",
                order_id,
                path,
                extra={"tag": "Заказы"},
            )
            messagebox.showwarning("Заказы", f"Файл не существует:\n{path}")
            return None
        return path

    def _export_order_protocol_meta(self) -> None:
        """JSON без измерений для protocol_generator (S3)."""
        order_id = self._get_selected_order_id()
        if order_id is None:
            messagebox.showinfo("JSON протокола", "Выберите заказ.")
            return
        _log.info("export protocol_meta start order_id=%s", order_id, extra={"tag": "Протокол"})
        self.status.set("Экспорт JSON для protocol_generator…")
        self.update_idletasks()
        db_path = self.db_path

        from ..bg_job import run_bg_job

        def work() -> Path:
            from ...generation.protocol_meta_export import export_protocol_meta_for_order

            return export_protocol_meta_for_order(order_id, db_path=db_path)

        def on_ok(path: Path) -> None:
            self.status.set(f"JSON: {path.name}")
            _log.info(
                "protocol meta exported order=%s path=%s",
                order_id,
                path,
                extra={"tag": "Протокол"},
            )
            messagebox.showinfo(
                "JSON для protocol_generator",
                f"Сохранено (без измеренных значений):\n{path}\n\n"
                "На машине с protocol_generator:\n"
                f'  cd D:\\My_projects\\protocol_generator\n'
                f'  .\\venv\\Scripts\\python.exe main.py "{path}"\n\n'
                "Или: scripts\\run_protocol_from_json.ps1",
            )
            try:
                import os

                os.startfile(str(path.parent))
            except OSError:
                pass

        def on_err(exc: BaseException) -> None:
            self.status.set("Ошибка экспорта JSON")
            messagebox.showerror("JSON протокола", str(exc))

        run_bg_job(
            self,
            work,
            on_success=on_ok,
            on_error=on_err,
            name="protocol_meta",
            tag="Протокол",
        )

    def _generate_order_application(self) -> None:
        order_id = self._get_selected_order_id()
        if order_id is None:
            return

        self.status.set("Формирование заявки на испытания…")
        self.update_idletasks()
        db_path = self.db_path
        _log.info(
            "application generate start order_id=%s",
            order_id,
            extra={"tag": "Заявка"},
        )

        from ..bg_job import run_bg_job

        def work() -> Path:
            from ...generation.application_generator import generate_application_from_order

            return generate_application_from_order(order_id, db_path=db_path)

        def on_ok(saved_path: Path) -> None:
            _log.info(
                "application generate ok order_id=%s path=%s",
                order_id,
                saved_path,
                extra={"tag": "Заявка"},
            )
            self.status.set(f"Заказ №{order_id} · заявка: {saved_path.name}")
            self._load_orders_table()
            self._show_order_details()
            try:
                import os

                os.startfile(str(saved_path))
            except OSError as exc:
                _log.warning(
                    "application startfile failed: %s",
                    exc,
                    extra={"tag": "Заявка"},
                )
            messagebox.showinfo(
                "Заявка сформирована",
                f"Заявка на испытания сохранена:\n{saved_path}",
            )

        def on_err(exc: BaseException) -> None:
            self.status.set("Ошибка формирования заявки")
            messagebox.showerror("Заявка на испытания", str(exc))

        run_bg_job(
            self,
            work,
            on_success=on_ok,
            on_error=on_err,
            name="application",
            tag="Заявка",
        )

    def _generate_order_protocol(self) -> None:
        order_id = self._get_selected_order_id()
        if order_id is None:
            return
        self.status.set("Формирование макета протокола…")
        self.update_idletasks()
        db_path = self.db_path
        _log.info("protocol draft start order_id=%s", order_id, extra={"tag": "Протокол"})

        from ..bg_job import run_bg_job

        def work() -> Path:
            from ...generation.protocol_generator import generate_protocol_draft_from_order

            return generate_protocol_draft_from_order(order_id, db_path=db_path)

        def on_ok(saved_path: Path) -> None:
            _log.info(
                "protocol draft ok order_id=%s path=%s",
                order_id,
                saved_path,
                extra={"tag": "Протокол"},
            )
            self.status.set(f"Заказ №{order_id} · протокол: {saved_path.name}")
            try:
                import os

                os.startfile(str(saved_path))
            except OSError as exc:
                _log.warning(
                    "protocol startfile failed: %s",
                    exc,
                    extra={"tag": "Протокол"},
                )
            messagebox.showinfo(
                "Макет протокола",
                f"Черновик протокола сохранён:\n{saved_path}\n\n"
                "Доработайте результаты испытаний вручную.",
            )

        def on_err(exc: BaseException) -> None:
            self.status.set("Ошибка макета протокола")
            messagebox.showerror("Макет протокола", str(exc))

        run_bg_job(
            self,
            work,
            on_success=on_ok,
            on_error=on_err,
            name="protocol_draft",
            tag="Протокол",
        )

    def _build_order_document_pack(self) -> None:
        """North Star: заявка + КП + макет протокола + summary в одну папку.

        Сборка на **main thread**: python-docx ~1–3 с, без thread/after гонок
        (раньше worker + after() ломал UI; диалог 1×1 — «пакет не работает»).
        """
        order_id = self._get_selected_order_id()
        if order_id is None:
            _log.info("document pack: no order selected", extra={"tag": "Пакет"})
            return
        opts = self._ask_document_pack_options(order_id)
        if not opts:
            _log.info(
                "document pack: dialog cancelled order_id=%s",
                order_id,
                extra={"tag": "Пакет"},
            )
            self.status.set("Пакет: отменено")
            return
        pack_settings = get_document_pack_settings(self.db_path)
        pack_settings.base_dir = opts["output_dir"]
        save_document_pack_settings(pack_settings, self.db_path)
        if hasattr(self, "pack_base_dir_var"):
            self.pack_base_dir_var.set(opts["output_dir"])

        out_dir = opts["output_dir"]
        pack_name = opts["pack_folder_name"]
        self.status.set("Сборка пакета документов…")
        self.update_idletasks()
        _log.info(
            "document pack start order_id=%s out_dir=%s pack_name=%r",
            order_id,
            out_dir,
            pack_name,
            extra={"tag": "Пакет"},
        )
        try:
            from ...generation.document_pack import build_document_pack

            pack = build_document_pack(
                order_id,
                output_dir=out_dir,
                pack_folder_name=pack_name,
                db_path=self.db_path,
            )
            push_recent_pack_path(pack["pack_dir"], self.db_path)
            _log.info(
                "document pack ok order_id=%s dir=%s files=%s",
                order_id,
                pack.get("pack_dir"),
                len(pack.get("files") or []),
                extra={"tag": "Пакет"},
            )
        except Exception as exc:
            _log.exception(
                "document pack failed order_id=%s: %s",
                order_id,
                exc,
                extra={"tag": "Пакет"},
            )
            self.status.set("Ошибка пакета документов")
            messagebox.showerror(
                "Пакет документов",
                f"{exc}\n\n"
                "Нужен заказ с КП (сначала «Сформировать КП» на вкладке КП).\n"
                f"Заказ №{order_id}.",
            )
            return

        pack_dir = pack["pack_dir"]
        self.status.set(f"Заказ №{order_id} · пакет: {Path(pack_dir).name}")
        self._load_orders_table()
        try:
            if hasattr(self, "orders_tree") and str(order_id) in self.orders_tree.get_children(""):
                self.orders_tree.selection_set(str(order_id))
                self.orders_tree.see(str(order_id))
        except tk.TclError:
            pass
        self._show_order_details()
        if hasattr(self, "_load_settings"):
            self._load_settings()
        try:
            import os

            os.startfile(pack_dir)
        except OSError:
            pass
        names = "\n".join(f"  • {Path(f).name}" for f in pack.get("files") or [])
        messagebox.showinfo(
            "Пакет документов",
            f"Папка:\n{pack_dir}\n\n{names}\n\n"
            "Макет протокола — черновик; ТУ/ПМИ-выдержки — в следующих итерациях.",
        )

    def _open_selected_order_application(self) -> None:
        path = self._get_selected_order_application_path()
        if not path:
            return
        try:
            import os

            os.startfile(str(path))
            self.status.set(f"Открыта заявка: {path.name}")
        except OSError as exc:
            messagebox.showerror("Заказы", str(exc))

    def _print_selected_order_application(self) -> None:
        path = self._get_selected_order_application_path()
        if not path:
            return
        try:
            import os

            os.startfile(str(path), "print")
            self.status.set(f"Печать заявки: {path.name}")
        except OSError as exc:
            messagebox.showerror("Печать", f"Не удалось отправить на печать:\n{exc}")

    def _delete_selected_order(self) -> None:
        sel = self.orders_tree.selection()
        if not sel:
            messagebox.showinfo("Заказы", "Выберите заказ.")
            return
        order_id = int(sel[0])
        if not messagebox.askyesno(
            "Удалить заказ",
            f"Удалить заказ №{order_id}?\n\n"
            "Каскадно: позиции заказа, заявки на испытания;\n"
            "записи generated отвяжутся. Файлы КП на диске и расчёты\n"
            "в «Истории» не удаляются автоматически.",
        ):
            return
        result = delete_order(order_id, self.db_path, cascade=True)
        if result.get("ok"):
            self._load_orders_table()
            self._set_text(self.order_details, "")
            self.status.set(f"Заказ №{order_id} удалён")
            _log.info("deleted order id=%s", order_id, extra={"tag": "БД"})
        else:
            messagebox.showerror("Заказы", f"Не удалось: {result.get('reason')}")

    def _show_orders_context_menu(self, event: tk.Event) -> None:
        row = self.orders_tree.identify_row(event.y)
        if row:
            self.orders_tree.selection_set(row)
        order_id = self._get_selected_order_id()
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Открыть КП", command=self._open_selected_order_kp)
        menu.add_command(label="Открыть заявку", command=self._open_selected_order_application)
        menu.add_command(label="Сформировать заявку", command=self._generate_order_application)
        menu.add_command(label="Пакет документов…", command=self._build_order_document_pack)
        menu.add_command(label="Макет протокола", command=self._generate_order_protocol)
        menu.add_separator()
        if order_id is not None:
            menu.add_command(
                label=f"Копировать № заказа ({order_id})",
                command=lambda: self._copy_text_to_clipboard(str(order_id)),
            )
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

