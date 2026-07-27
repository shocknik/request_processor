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
from ..logging_setup import get_logger
from ..persistence.sqlite_repo import DB_PATH_DEFAULT, get_order_details
from .application_generator import generate_application_from_order
from .protocol_generator import generate_protocol_draft_from_order

_log = get_logger("generation.document_pack")


def safe_filename_part(
    text: str,
    max_len: int = 40,
    *,
    default: str = "заказ",
) -> str:
    """
    Безопасный фрагмент имени файла Windows.

    «ООО «СУПР»» → «ООО_СУПР» (не «ООО _СУПР»).
    """
    cleaned = re.sub(r'[<>:"/\\|?*«»""„]', "_", text or "")
    cleaned = re.sub(r"\s*_\s*", "_", cleaned)
    cleaned = re.sub(r"_+", "_", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ._")
    return (cleaned[:max_len] or default).rstrip("._")


def _safe_name(text: str, max_len: int = 40) -> str:
    return safe_filename_part(text, max_len=max_len, default="заказ")


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
    _log.info(
        "build_document_pack begin order_id=%s output_dir=%s pack_folder=%r db=%s",
        order_id,
        output_dir,
        pack_folder_name,
        db_path,
        extra={"tag": "Пакет"},
    )
    details = get_order_details(order_id, db_path=db_path)
    if not details:
        _log.error(
            "build_document_pack abort: order not found id=%s db=%s",
            order_id,
            db_path,
            extra={"tag": "Пакет"},
        )
        raise ValueError(f"Заказ №{order_id} не найден")

    customer = details.get("customer_name") or "заказчик"
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    base = Path(output_dir) if output_dir else GENERATED_DIR
    try:
        base.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        _log.exception(
            "build_document_pack cannot mkdir base=%s: %s",
            base,
            exc,
            extra={"tag": "Пакет"},
        )
        raise
    if pack_folder_name and pack_folder_name.strip():
        folder = _safe_name(pack_folder_name.strip(), max_len=80)
    else:
        folder = f"pack_order{order_id}_{_safe_name(customer)}_{stamp}"
    pack_dir = base / folder
    try:
        pack_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        _log.exception(
            "build_document_pack cannot mkdir pack_dir=%s: %s",
            pack_dir,
            exc,
            extra={"tag": "Пакет"},
        )
        raise

    files: list[str] = []
    _log.info(
        "build_document_pack pack_dir=%s customer=%r kp_src=%r app_src=%r marks=%s",
        pack_dir,
        customer[:80],
        details.get("kp_output_path"),
        details.get("application_path"),
        len(details.get("marks") or []),
        extra={"tag": "Пакет"},
    )

    # КП
    kp_src = details.get("kp_output_path")
    if kp_src and Path(kp_src).exists():
        kp_dst = pack_dir / Path(kp_src).name
        try:
            shutil.copy2(kp_src, kp_dst)
            files.append(str(kp_dst))
            _log.info("pack step KP copied → %s", kp_dst.name, extra={"tag": "Пакет"})
        except OSError as exc:
            _log.exception(
                "pack step KP copy failed src=%s: %s",
                kp_src,
                exc,
                extra={"tag": "Пакет"},
            )
            raise
    elif kp_src:
        _log.warning(
            "pack step KP missing on disk path=%s (order has path but file absent)",
            kp_src,
            extra={"tag": "Пакет"},
        )
    else:
        _log.warning(
            "pack step KP skipped: no kp_output_path on order_id=%s",
            order_id,
            extra={"tag": "Пакет"},
        )

    # Заявка
    app_path: Path | None = None
    existing_app = details.get("application_path")
    try:
        if existing_app and Path(existing_app).exists() and not regenerate_application:
            app_path = pack_dir / Path(existing_app).name
            shutil.copy2(existing_app, app_path)
            _log.info(
                "pack step application copied → %s",
                app_path.name,
                extra={"tag": "Пакет"},
            )
        else:
            if existing_app and not Path(existing_app).exists():
                _log.warning(
                    "pack step application path stale, regenerating: %s",
                    existing_app,
                    extra={"tag": "Пакет"},
                )
            app_path = generate_application_from_order(
                order_id,
                output_path=pack_dir
                / f"Заявка_заказ{order_id}_{stamp}.docx",
                db_path=db_path,
            )
            _log.info(
                "pack step application generated → %s size=%s",
                app_path.name,
                app_path.stat().st_size if app_path.exists() else 0,
                extra={"tag": "Пакет"},
            )
    except Exception as exc:
        _log.exception(
            "pack step application failed order_id=%s: %s",
            order_id,
            exc,
            extra={"tag": "Пакет"},
        )
        raise
    files.append(str(app_path))

    # Макет протокола
    try:
        protocol_path = generate_protocol_draft_from_order(
            order_id,
            output_path=pack_dir / f"Протокол_макет_заказ{order_id}_{stamp}.docx",
            db_path=db_path,
        )
        _log.info(
            "pack step protocol → %s size=%s",
            protocol_path.name,
            protocol_path.stat().st_size if protocol_path.exists() else 0,
            extra={"tag": "Пакет"},
        )
    except Exception as exc:
        _log.exception(
            "pack step protocol failed order_id=%s: %s",
            order_id,
            exc,
            extra={"tag": "Пакет"},
        )
        raise
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

    _log.info(
        "build_document_pack done order_id=%s pack_dir=%s n_files=%s names=%s",
        order_id,
        pack_dir,
        len(files),
        [Path(f).name for f in files],
        extra={"tag": "Пакет"},
    )
    return {
        "pack_dir": str(pack_dir),
        "files": files,
        "order_id": order_id,
        "summary_path": str(summary_path),
    }
