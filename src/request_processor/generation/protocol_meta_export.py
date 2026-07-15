"""
Экспорт JSON-каркаса протокола для protocol_generator (без измеренных значений).

Формат совместим с meta_with_single_laying.json:
PRIMARY + секции 2–12. Поля «Фактический результат» / выводы — заглушки.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from ..config import GENERATED_DIR
from ..generation.lab_profile import load_lab_profile
from ..persistence.sqlite_repo import (
    DB_PATH_DEFAULT,
    get_calculation_lines,
    get_order_details,
    list_test_items,
)

PRIMARY = {
    "2": "Основание для проведения испытаний",
    "3": "Информация о заказчике",
    "4": "Информация об изготовителе",
    "5": "Информация об объекте испытаний",
    "6": "Даты проведения испытаний",
    "7": "Цель испытаний",
    "8": "Условия окружающей среды при проведении испытаний",
    "9": "Методы испытаний",
    "11": "Перечень применяемого испытательного оборудования и средств измерений",
    "10": "Результаты испытаний",
    "12": "Испытания провели",
}


def _addr(*parts: str | None) -> str:
    return ", ".join(p.strip() for p in parts if p and str(p).strip())


def _org_block(
    *,
    name: str = "",
    legal: str = "",
    actual: str = "",
    phone: str = "",
    email: str = "",
    inn: str = "",
    fsa: str = "",
) -> dict[str, str]:
    return {
        "юридический адрес: ": legal or actual or "",
        "адрес места осуществления деятельности: ": actual or legal or "",
        "наименование: ": name or "",
        "телефон: ": phone or "",
        "e-mail: ": email or "",
        "номер в реестре аккредитованных лиц: ": fsa or "",
        "ИНН: ": inn or "",
    }


def _collect_tests_from_order(
    details: dict[str, Any],
    db_path: Path | str,
) -> list[dict[str, str]]:
    """Уникальные испытания из calculation_lines привязанных расчётов."""
    seen: set[str] = set()
    items: list[dict[str, str]] = []
    # map name -> method from price book
    method_by_name: dict[str, str] = {}
    for ti in list_test_items(limit=500, db_path=db_path):
        n = (ti.get("name") or "").strip()
        if n:
            method_by_name[n.lower()] = (ti.get("method") or "").strip()

    for mark_row in details.get("marks") or []:
        calc_id = mark_row.get("calculation_id")
        if not calc_id:
            continue
        for line in get_calculation_lines(int(calc_id), db_path=db_path):
            name = (line.get("test_name") or "").strip()
            if not name or name.lower() in seen:
                continue
            seen.add(name.lower())
            method = method_by_name.get(name.lower(), "")
            items.append({"name": name, "method": method, "mark": mark_row.get("mark") or ""})
    return items


def build_protocol_meta_json(
    order_id: int,
    *,
    db_path: Path | str = DB_PATH_DEFAULT,
    sample_date: str | None = None,
    basis: str = "",
) -> dict[str, Any]:
    """Собирает dict в формате protocol_generator (измерения пустые)."""
    details = get_order_details(order_id, db_path=db_path)
    if not details:
        raise ValueError(f"Заказ №{order_id} не найден")

    lab = load_lab_profile()
    marks = details.get("marks") or []
    primary_mark = (marks[0].get("mark") if marks else "") or ""
    all_marks = ", ".join(
        m.get("mark") for m in marks if m.get("mark")
    ) or primary_mark

    today = datetime.now().strftime("%d.%m.%Y")
    presented = sample_date or today
    subject = (details.get("subject") or "Проведение испытаний").strip()
    customer_name = details.get("customer_name") or details.get("customer_name") or ""
    # get_order_details may put customer on order row
    if not customer_name:
        customer_name = details.get("customer_name") or ""

    cust = _org_block(
        name=details.get("customer_name") or "",
        legal=details.get("customer_legal_address") or details.get("customer_address") or "",
        actual=details.get("customer_actual_address") or details.get("customer_address") or "",
        phone=details.get("customer_phone") or "",
        email=details.get("customer_email") or "",
        inn=details.get("customer_inn") or "",
    )
    manu = _org_block(
        name=details.get("manufacturer_name") or "",
        legal=details.get("manufacturer_legal_address")
        or details.get("manufacturer_address")
        or "",
        actual=details.get("manufacturer_actual_address")
        or details.get("manufacturer_address")
        or "",
        phone=details.get("manufacturer_phone") or "",
        email=details.get("manufacturer_email") or "",
        inn=details.get("manufacturer_inn") or "",
    )

    tests = _collect_tests_from_order(details, db_path)
    methods: dict[str, str] = {}
    for t in tests:
        m = t.get("method") or ""
        if m and m not in methods:
            methods[m] = m  # generator expects title → description; method alone ok

    # Результаты: одна группа «По программе / расчёту»
    results_group: dict[str, Any] = {}
    for i, t in enumerate(tests, start=1):
        case_id = f"1.{i}"
        results_group[case_id] = {
            "Раздел": "Испытания (шаблон без измерений)",
            "Наименование": t["name"],
            "Пукнты технических требований": "",
            "Методы испытаний": t.get("method") or "",
            "Критерии годности: ": [
                {
                    "Наименование показателя": t["name"],
                    "Разм.": "",
                    "Требования по НД": "—",
                    "Допуск по НД": "—",
                    "Фактический результат": "",
                    "Вывод о соответствии": "",
                }
            ],
        }
    if not results_group:
        results_group["1.1"] = {
            "Раздел": "Испытания (шаблон без измерений)",
            "Наименование": "Перечень испытаний не задан — заполните расчёт заказа",
            "Пукнты технических требований": "",
            "Методы испытаний": "",
            "Критерии годности: ": [
                {
                    "Наименование показателя": "—",
                    "Разм.": "",
                    "Требования по НД": "—",
                    "Допуск по НД": "—",
                    "Фактический результат": "",
                    "Вывод о соответствии": "",
                }
            ],
        }

    purpose = (
        f"{subject}. Марка(и): {all_marks}. "
        f"Заказ №{order_id}. "
        "Шаблон протокола без измеренных значений (request-processor → protocol_generator)."
    )

    basis_text = basis or (
        f"Заявка / договор (заказ №{order_id}). Документ-основание уточняется."
    )

    payload: dict[str, Any] = {
        "PRIMARY": PRIMARY,
        "2": {"Основание для проведения испытаний": basis_text},
        "3": {"Информация о заказчике": cust},
        "4": {"Информация об изготовителе": manu},
        "5": {
            "Информация об объекте испытаний": {
                "ID: ": str(order_id),
                "Образец представлен на испытания: ": presented,
                "Марка: ": primary_mark or all_marks,
                "Партия: ": "",
                "Папка с фото образца: ": "",
            }
        },
        "6": {
            "Даты проведения испытаний": {
                "Дата начала": presented,
                "Дата окончания": "",
            }
        },
        "7": {"Цель испытаний": purpose},
        "8": {
            "Условия окружающей среды при проведении испытаний": {
                "Температура окружающей среды: ": "— °С",
                "Относительная влажность воздуха: ": "— %",
                "Атмосферное давление: ": "— кПа",
            }
        },
        "9": {"Методы испытаний": methods or {"—": "Методы будут указаны по программе испытаний"}},
        "11": {
            "Перечень применяемого испытательного оборудования и средств измерений": {}
        },
        "10": {
            "Результаты испытаний": {
                "1 Испытания (шаблон)": results_group,
            }
        },
        "12": {
            "Испытания провели": {
                "лаборатория: ": lab.name,
                "примечание: ": "Шаблон; исполнители и подписи заполняются при оформлении протокола",
            }
        },
        "_meta": {
            "source": "request-processor",
            "order_id": order_id,
            "exported_at": datetime.now().isoformat(timespec="seconds"),
            "measured_values": False,
            "note": "Пустые «Фактический результат» — шаблон для protocol_generator",
        },
    }
    return payload


def export_protocol_meta_for_order(
    order_id: int,
    *,
    output_path: Path | str | None = None,
    db_path: Path | str = DB_PATH_DEFAULT,
) -> Path:
    """Пишет JSON на диск; возвращает путь."""
    data = build_protocol_meta_json(order_id, db_path=db_path)
    if output_path is None:
        stamp = datetime.now().strftime("%Y%m%d_%H%M")
        mark = ""
        try:
            mark = (data.get("5") or {}).get("Информация об объекте испытаний", {}).get(
                "Марка: ", ""
            )
        except Exception:
            pass
        safe = re.sub(r'[<>:"/\\|?*«»]', "_", mark).strip("._ ")[:40] or "mark"
        output_path = (
            GENERATED_DIR
            / f"protocol_meta_order{order_id}_{safe}_{stamp}.json"
        )
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path.resolve()
