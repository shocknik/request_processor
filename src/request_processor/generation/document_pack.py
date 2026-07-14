"""
Пакет выходных документов по заказу (North Star v1).

Собирает в одну папку:
  - КП (копия, если есть)
  - заявка по форме (генерирует при отсутствии)
  - макет протокола
  - summary.json (снимок для обучения/аудита)
"""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from ..config import GENERATED_DIR
from ..persistence.sqlite_repo import DB_PATH_DEFAULT, get_order_details
from .application_generator import generate_application_from_order
from .protocol_generator import generate_protocol_draft_from_order


def _safe_name(text: str, max_len: int = 40) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*«»]', "_", text or "").strip("._ ")
    return (cleaned[:max_len] or "заказ").rstrip("._")


def build_document_pack(
    order_id: int,
    *,
    output_dir: Path | str | None = None,
    pack_folder_name: str | None = None,
    db_path: Path | str = DB_PATH_DEFAULT,
    regenerate_application: bool = False,
) -> dict[str, Any]:
    """
    Формирует папку пакета документов.

    Returns:
        dict с ключами: pack_dir, files (list[str]), order_id, summary_path
    """
    details = get_order_details(order_id, db_path=db_path)
    if not details:
        raise ValueError(f"Заказ №{order_id} не найден")

    customer = details.get("customer_name") or "заказчик"
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    base = Path(output_dir) if output_dir else GENERATED_DIR
    base.mkdir(parents=True, exist_ok=True)
    if pack_folder_name and pack_folder_name.strip():
        folder = _safe_name(pack_folder_name.strip(), max_len=80)
    else:
        folder = f"pack_order{order_id}_{_safe_name(customer)}_{stamp}"
    pack_dir = base / folder
    pack_dir.mkdir(parents=True, exist_ok=True)

    files: list[str] = []

    # КП
    kp_src = details.get("kp_output_path")
    if kp_src and Path(kp_src).exists():
        kp_dst = pack_dir / Path(kp_src).name
        shutil.copy2(kp_src, kp_dst)
        files.append(str(kp_dst))

    # Заявка
    app_path: Path | None = None
    existing_app = details.get("application_path")
    if existing_app and Path(existing_app).exists() and not regenerate_application:
        app_path = pack_dir / Path(existing_app).name
        shutil.copy2(existing_app, app_path)
    else:
        app_path = generate_application_from_order(
            order_id,
            output_path=pack_dir
            / f"Заявка_заказ{order_id}_{stamp}.docx",
            db_path=db_path,
        )
    files.append(str(app_path))

    # Макет протокола
    protocol_path = generate_protocol_draft_from_order(
        order_id,
        output_path=pack_dir / f"Протокол_макет_заказ{order_id}_{stamp}.docx",
        db_path=db_path,
    )
    files.append(str(protocol_path))

    # Технический снимок (JSON) — для аудита и обучения
    summary = {
        "order_id": order_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "customer_name": details.get("customer_name"),
        "manufacturer_name": details.get("manufacturer_name"),
        "subject": details.get("subject"),
        "total_without_vat": details.get("total_without_vat"),
        "total_with_vat": details.get("total_with_vat"),
        "marks": details.get("marks") or [],
        "source_document": details.get("source_document"),
        "kp_output_path": details.get("kp_output_path"),
        "application_path": str(app_path),
        "protocol_path": str(protocol_path),
        "files": [Path(f).name for f in files],
        "note": (
            "Пакет v1: заявка + КП (если был) + макет протокола + JSON. "
            "Набор выдержек из ТУ/ПМИ — в следующих итерациях (rag_corpus)."
        ),
    }
    summary_path = pack_dir / "summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    files.append(str(summary_path))

    # README для оператора
    readme = pack_dir / "README.txt"
    readme.write_text(
        "\n".join(
            [
                f"Пакет документов · заказ №{order_id}",
                f"Заказчик: {customer}",
                f"Сформирован: {stamp}",
                "",
                "Содержимое:",
                *[f"  - {Path(f).name}" for f in files],
                "",
                "Макет протокола — черновик для доработки оператором.",
                "Проверьте реквизиты, НД, объём испытаний и результаты.",
            ]
        ),
        encoding="utf-8",
    )
    files.append(str(readme))

    return {
        "pack_dir": str(pack_dir),
        "files": files,
        "order_id": order_id,
        "summary_path": str(summary_path),
    }
