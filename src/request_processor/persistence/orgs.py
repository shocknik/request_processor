"""Организации: upsert, слияние дублей, HITL confirm."""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from ..extraction.organization_extractor import (
    is_placeholder_org_name,
    normalize_org_name,
)
from ..models import OrganizationExtract
from .db import DB_PATH_DEFAULT, _log, get_connection

def upsert_organization(
    extract: OrganizationExtract,
    *,
    source: str | None = None,
    db_path: str | Path = DB_PATH_DEFAULT,
) -> int:
    """Сохраняет организацию без дублей (по ИНН или нормализованному названию)."""
    from ..extraction.organization_extractor import finalize_organization_address

    extract = finalize_organization_address(extract)
    now = datetime.now().isoformat()
    name_normalized = normalize_org_name(extract.name)
    inn_key = extract.inn or ""

    if is_placeholder_org_name(extract.name):
        existing = find_organization_id_by_name(extract.name, db_path)
        if existing:
            return existing
        _log.warning(
            "skip placeholder org name=%r",
            extract.name,
            extra={"tag": "Организации"},
        )
        return 0

    merge_keep: int | None = None
    merge_drop: int | None = None
    legal = extract.legal_address or extract.address
    actual = extract.actual_address or legal

    with get_connection(db_path) as conn:
        row = None
        if extract.inn:
            row = conn.execute(
                "SELECT * FROM organizations WHERE inn = ?",
                (extract.inn,),
            ).fetchone()
        if row is None:
            row = conn.execute(
                "SELECT * FROM organizations WHERE name_normalized = ? AND COALESCE(inn, '') = ?",
                (name_normalized, inn_key),
            ).fetchone()
        # Тот же name_normalized: карточка с ИНН и дубль без ИНН
        # (work 14.08: Спецкабель id=3 с ИНН vs id=16 пустой).
        if row is not None:
            row_id = int(row["id"])
            inn_now = extract.inn or row["inn"]
            if inn_now:
                empty_twin = conn.execute(
                    """
                    SELECT id FROM organizations
                    WHERE id != ?
                      AND name_normalized = ?
                      AND COALESCE(inn, '') = ''
                    LIMIT 1
                    """,
                    (row_id, name_normalized),
                ).fetchone()
                if empty_twin is not None:
                    merge_keep = row_id
                    merge_drop = int(empty_twin["id"])
                else:
                    by_inn = conn.execute(
                        "SELECT id FROM organizations WHERE inn = ? AND id != ?",
                        (inn_now, row_id),
                    ).fetchone()
                    if by_inn is not None:
                        merge_keep = int(by_inn["id"])
                        merge_drop = row_id

        if merge_keep is None:
            if row:
                org_id = int(row["id"])
                conn.execute(
                    """
                    UPDATE organizations SET
                        name = ?,
                        address = COALESCE(?, address),
                        legal_address = COALESCE(?, legal_address),
                        actual_address = COALESCE(?, actual_address),
                        postal_code = COALESCE(?, postal_code),
                        phone = COALESCE(?, phone),
                        email = COALESCE(?, email),
                        inn = COALESCE(?, inn),
                        kpp = COALESCE(?, kpp),
                        is_accredited = MAX(is_accredited, ?),
                        fsa_registry_number = COALESCE(?, fsa_registry_number),
                        org_type = CASE WHEN ? = 'unknown' THEN org_type ELSE ? END,
                        source = COALESCE(?, source),
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        extract.name,
                        extract.address,
                        legal,
                        actual,
                        extract.postal_code,
                        extract.phone,
                        extract.email,
                        extract.inn,
                        extract.kpp,
                        int(extract.is_accredited),
                        extract.fsa_registry_number,
                        extract.org_type,
                        extract.org_type,
                        source,
                        now,
                        org_id,
                    ),
                )
                return org_id

            cursor = conn.execute(
                """
                INSERT INTO organizations (
                    name, name_normalized, address, legal_address, actual_address,
                    postal_code, phone, email,
                    inn, kpp, is_accredited, fsa_registry_number, org_type,
                    source, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    extract.name,
                    name_normalized,
                    extract.address,
                    legal,
                    actual,
                    extract.postal_code,
                    extract.phone,
                    extract.email,
                    extract.inn,
                    extract.kpp,
                    int(extract.is_accredited),
                    extract.fsa_registry_number,
                    extract.org_type,
                    source,
                    now,
                    now,
                ),
            )
            return int(cursor.lastrowid or 0)

    assert merge_keep is not None and merge_drop is not None
    merge_organizations(merge_keep, merge_drop, db_path=db_path)
    return upsert_organization(extract, source=source, db_path=db_path)


def find_similar_organizations(
    name: str,
    *,
    min_ratio: float = 0.82,
    limit: int = 8,
    db_path: str | Path = DB_PATH_DEFAULT,
) -> list[dict[str, Any]]:
    """
    Кандидаты-дубликаты по нормализованному имени (SequenceMatcher + substring).

    Каждый элемент: {id, name, name_normalized, org_type, inn, score}.
    Exact match (score=1.0) идёт первым.
    """
    from difflib import SequenceMatcher

    raw = (name or "").strip()
    if len(raw) < 2:
        return []
    key = normalize_org_name(raw)
    if not key:
        return []

    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT id, name, name_normalized, org_type, inn FROM organizations"
        ).fetchall()

    scored: list[dict[str, Any]] = []
    for row in rows:
        other_key = (row["name_normalized"] or normalize_org_name(row["name"] or "")).strip()
        if not other_key:
            continue
        if other_key == key:
            score = 1.0
        else:
            score = SequenceMatcher(None, key, other_key).ratio()
            if key in other_key or other_key in key:
                score = max(score, 0.88)
        if score >= min_ratio:
            scored.append(
                {
                    "id": int(row["id"]),
                    "name": row["name"],
                    "name_normalized": other_key,
                    "org_type": row["org_type"],
                    "inn": row["inn"],
                    "score": round(score, 3),
                }
            )
    scored.sort(key=lambda x: (-x["score"], x["name"] or ""))
    return scored[:limit]


def create_organization(
    *,
    name: str,
    address: str | None = None,
    postal_code: str | None = None,
    phone: str | None = None,
    email: str | None = None,
    inn: str | None = None,
    kpp: str | None = None,
    is_accredited: bool = False,
    fsa_registry_number: str | None = None,
    org_type: str = "unknown",
    source: str | None = "manual",
    db_path: str | Path = DB_PATH_DEFAULT,
) -> int:
    """Создаёт организацию (CRUD «+ Добавить»). Без fuzzy — вызывающий решает."""
    if is_placeholder_org_name(name):
        raise ValueError(
            f"«{(name or '').strip()}» похоже на логин Windows или заглушку "
            "и не сохраняется как организация."
        )
    extract = OrganizationExtract(
        name=name.strip(),
        address=address,
        legal_address=address,
        actual_address=address,
        postal_code=postal_code,
        phone=phone,
        email=email,
        inn=inn,
        kpp=kpp,
        is_accredited=is_accredited,
        fsa_registry_number=fsa_registry_number,
        org_type=org_type if org_type in (
            "manufacturer",
            "certification_body",
            "testing_center",
            "dealer",
            "unknown",
        ) else "unknown",
        role="unknown",
        confidence=1.0,
    )
    return upsert_organization(extract, source=source, db_path=db_path)


def save_organizations_from_extraction(
    organizations: list[OrganizationExtract],
    *,
    source: str | None = None,
    customer_name: str | None = None,
    manufacturer_name: str | None = None,
    customer_inn: str | None = None,
    customer_address: str | None = None,
    skip_own_lab: bool = True,
    db_path: str | Path = DB_PATH_DEFAULT,
) -> dict[str, int | None]:
    """
    Сохраняет организации из заявки; возвращает id заказчика и производителя.

    - Наша ИЛ (lab_profile / Кабель-Тест) **не** пишется в справочник и **не**
      становится customer/manufacturer.
    - customer_name / manufacturer_name из GUI (после правок оператора) —
      приоритетнее списка extract, если роли в extract пустые.
    - Нет fallback manufacturer_id = customer_id (ломало направления: ИЛ = «производитель»).
    """
    from ..generation.lab_profile import is_own_lab_name

    customer_id: int | None = None
    manufacturer_id: int | None = None

    def _skip(org: OrganizationExtract) -> bool:
        if not skip_own_lab:
            return False
        if is_own_lab_name(org.name):
            return True
        if org.org_type == "testing_center" and is_own_lab_name(org.name):
            return True
        return False

    # 1) Явные строки GUI — надёжный источник ролей после human-in-the-loop
    cust = (customer_name or "").strip()
    mfg = (manufacturer_name or "").strip()
    if is_placeholder_org_name(cust):
        cust = ""
    if is_placeholder_org_name(mfg):
        mfg = ""
    if cust and not (skip_own_lab and is_own_lab_name(cust)):
        cust_org = OrganizationExtract(
            name=cust,
            inn=customer_inn,
            address=customer_address,
            legal_address=customer_address,
            actual_address=customer_address,
            org_type="certification_body"
            if re.search(r"сертификац|фаер|fire\s*lab", cust, re.I)
            else "unknown",
            role="customer",
            confidence=0.95,
        )
        # если в extract уже есть customer с тем же именем — подтянуть тип/телефон
        for o in organizations:
            if o.role == "customer" and normalize_org_name(o.name) == normalize_org_name(cust):
                cust_org = o.model_copy(
                    update={
                        "name": cust,
                        "inn": customer_inn or o.inn,
                        "address": customer_address or o.address,
                        "role": "customer",
                    }
                )
                break
            if o.org_type == "certification_body" and normalize_org_name(
                o.name
            ) == normalize_org_name(cust):
                cust_org = o.model_copy(
                    update={
                        "name": cust,
                        "inn": customer_inn or o.inn,
                        "address": customer_address or o.address,
                        "role": "customer",
                    }
                )
                break
        customer_id = upsert_organization(cust_org, source=source, db_path=db_path)

    if mfg and not (skip_own_lab and is_own_lab_name(mfg)):
        mfg_org = OrganizationExtract(
            name=mfg,
            org_type="manufacturer",
            role="manufacturer",
            confidence=0.95,
        )
        for o in organizations:
            if o.role == "manufacturer" and normalize_org_name(o.name) == normalize_org_name(
                mfg
            ):
                mfg_org = o.model_copy(update={"name": mfg, "role": "manufacturer"})
                break
        manufacturer_id = upsert_organization(mfg_org, source=source, db_path=db_path)

    # 2) Остальные из extract (не ИЛ; роли customer/manufacturer если ещё не заданы)
    for org in organizations:
        if _skip(org):
            continue
        if is_placeholder_org_name(org.name):
            continue
        if org.role not in ("customer", "manufacturer", "dealer") and org.org_type not in (
            "manufacturer",
            "certification_body",
            "dealer",
        ):
            # testing_center чужой — можно сохранить справочно, без ролей заказа
            if org.org_type == "testing_center":
                continue
        org_id = upsert_organization(org, source=source, db_path=db_path)
        if org.role == "customer" and customer_id is None and not is_own_lab_name(org.name):
            customer_id = org_id
        if org.role == "manufacturer" and manufacturer_id is None and not is_own_lab_name(
            org.name
        ):
            manufacturer_id = org_id
        if (
            customer_id is None
            and org.org_type == "certification_body"
            and not is_own_lab_name(org.name)
        ):
            customer_id = org_id

    return {"customer_org_id": customer_id, "manufacturer_org_id": manufacturer_id}


def save_document_extraction(
    *,
    source_path: str,
    source_type: str,
    text: str,
    marks_count: int,
    customer_org_id: int | None = None,
    manufacturer_org_id: int | None = None,
    subject: str | None = None,
    db_path: str | Path = DB_PATH_DEFAULT,
) -> int:
    with get_connection(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO document_extractions (
                source_path, source_type, customer_org_id, manufacturer_org_id,
                subject, raw_text_length, marks_count, extracted_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source_path,
                source_type,
                customer_org_id,
                manufacturer_org_id,
                subject,
                len(text),
                marks_count,
                datetime.now().isoformat(),
            ),
        )
        return int(cursor.lastrowid or 0)


def _normalize_org_search(text: str) -> str:
    """Нормализация строки поиска org: casefold, ё→е, кавычки/пробелы."""
    s = (text or "").replace("ё", "е").replace("Ё", "Е")
    s = s.casefold().strip()
    # убрать типовые кавычки, чтобы «тольят» ловил ООО «"ТОЛЬЯТТИ…»"
    for ch in "«»\"'“”„":
        s = s.replace(ch, "")
    s = " ".join(s.split())
    return s


def list_organizations(
    search: str | None = None,
    org_type: str | None = None,
    limit: int = 100,
    db_path: str | Path = DB_PATH_DEFAULT,
    *,
    exclude_placeholders: bool = False,
) -> list[dict[str, Any]]:
    """Список организаций.

    Поиск по name/inn/address с **Unicode casefold** (кириллица: «тольят» = «Тольят»).
    SQLite LIKE для не-ASCII регистрозависим — фильтр в Python.
    При поиске читаем **все** org (не LIMIT до фильтра), иначе «хвост» списка
    не участвует в поиске.
    """
    query = "SELECT * FROM organizations"
    params: list[Any] = []
    conditions: list[str] = []
    if org_type:
        conditions.append("org_type = ?")
        params.append(org_type)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY updated_at DESC"

    with get_connection(db_path) as conn:
        rows = [dict(row) for row in conn.execute(query, params).fetchall()]

    needle = _normalize_org_search(search or "")
    if needle:
        def _blob(row: dict[str, Any]) -> str:
            parts: list[str] = []
            for key in (
                "name",
                "inn",
                "address",
                "legal_address",
                "actual_address",
                "postal_code",
                "phone",
                "fsa_registry_number",
                "note",
            ):
                val = row.get(key)
                if val:
                    parts.append(str(val))
            return _normalize_org_search(" ".join(parts))

        # все токены запроса должны встретиться (порядок не важен)
        tokens = [t for t in needle.split() if t]
        rows = [
            r
            for r in rows
            if all(tok in _blob(r) for tok in tokens)
        ]
    if exclude_placeholders:
        rows = [r for r in rows if not is_placeholder_org_name(r.get("name"))]
    return rows[:limit]


def get_organization_by_id(
    org_id: int,
    db_path: str | Path = DB_PATH_DEFAULT,
) -> dict[str, Any] | None:
    with get_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM organizations WHERE id = ?", (org_id,)).fetchone()
        return dict(row) if row else None


def _retarget_organization_fks(conn: sqlite3.Connection, from_id: int, to_id: int) -> None:
    """Переназначает ссылки с одной организации на другую."""
    if from_id == to_id:
        return
    for sql in (
        "UPDATE orders SET customer_org_id = ? WHERE customer_org_id = ?",
        "UPDATE orders SET manufacturer_org_id = ? WHERE manufacturer_org_id = ?",
        "UPDATE order_marks SET manufacturer_org_id = ? WHERE manufacturer_org_id = ?",
        "UPDATE document_extractions SET customer_org_id = ? WHERE customer_org_id = ?",
        "UPDATE document_extractions SET manufacturer_org_id = ? WHERE manufacturer_org_id = ?",
    ):
        conn.execute(sql, (to_id, from_id))


def merge_organizations(
    keep_id: int,
    drop_id: int,
    *,
    db_path: str | Path = DB_PATH_DEFAULT,
) -> int:
    """Сливает drop в keep: копирует пустые реквизиты, переносит ссылки, удаляет drop.

    Work 14.08: две карточки Спецкабеля (с ИНН и без) ломали confirm UNIQUE.
    """
    if keep_id == drop_id:
        return keep_id
    now = datetime.now().isoformat()
    with get_connection(db_path) as conn:
        keep = conn.execute(
            "SELECT * FROM organizations WHERE id = ?", (keep_id,)
        ).fetchone()
        drop = conn.execute(
            "SELECT * FROM organizations WHERE id = ?", (drop_id,)
        ).fetchone()
        if keep is None:
            raise ValueError(f"Нет организации id={keep_id}")
        if drop is None:
            return keep_id
        fill_cols = (
            "inn",
            "kpp",
            "address",
            "legal_address",
            "actual_address",
            "postal_code",
            "phone",
            "email",
            "fsa_registry_number",
        )
        updates: dict[str, Any] = {}
        for col in fill_cols:
            if not keep[col] and drop[col]:
                updates[col] = drop[col]
        if updates:
            sets = ", ".join(f"{col} = ?" for col in updates)
            conn.execute(
                f"UPDATE organizations SET {sets}, updated_at = ? WHERE id = ?",
                [*updates.values(), now, keep_id],
            )
        _retarget_organization_fks(conn, drop_id, keep_id)
        conn.execute("DELETE FROM organizations WHERE id = ?", (drop_id,))
        _log.info(
            "merge organizations keep=%s drop=%s filled=%s",
            keep_id,
            drop_id,
            list(updates),
            extra={"tag": "Организации"},
        )
    return keep_id


def _find_org_dedup_conflict(
    conn: sqlite3.Connection,
    *,
    org_id: int,
    name_normalized: str,
    inn_key: str,
) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT * FROM organizations
        WHERE id != ?
          AND name_normalized = ?
          AND COALESCE(inn, '') = ?
        LIMIT 1
        """,
        (org_id, name_normalized, inn_key),
    ).fetchone()


def attach_organization_details(
    org_id: int,
    *,
    inn: str | None = None,
    address: str | None = None,
    kpp: str | None = None,
    org_type: str | None = None,
    db_path: str | Path = DB_PATH_DEFAULT,
) -> int:
    """Дописывает ИНН/адрес к карточке. При UNIQUE — сливает с существующей.

    Возвращает id карточки, которой нужно пользоваться дальше (может быть не org_id).
    """
    inn_val = (inn or "").strip() or None
    addr_val = (address or "").strip() or None
    now = datetime.now().isoformat()

    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM organizations WHERE id = ?", (org_id,)
        ).fetchone()
        if row is None:
            return org_id
        name_norm = row["name_normalized"] or normalize_org_name(row["name"] or "")
        new_inn_key = inn_val or (row["inn"] or "")
        conflict = _find_org_dedup_conflict(
            conn,
            org_id=org_id,
            name_normalized=name_norm,
            inn_key=new_inn_key,
        )
        if conflict is not None:
            keep_id, drop_id = _pick_org_merge_ids(row, conflict)
            # выходим из соединения и сливаем отдельной транзакцией
        else:
            conn.execute(
                """
                UPDATE organizations SET
                    address = COALESCE(?, address),
                    inn = COALESCE(?, inn),
                    kpp = COALESCE(?, kpp),
                    org_type = CASE WHEN ? IS NULL OR ? = 'unknown' THEN org_type ELSE ? END,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    addr_val,
                    inn_val,
                    (kpp or "").strip() or None,
                    org_type,
                    org_type,
                    org_type,
                    now,
                    org_id,
                ),
            )
            return org_id

    surviving = merge_organizations(keep_id, drop_id, db_path=db_path)
    if addr_val or inn_val:
        with get_connection(db_path) as conn:
            conn.execute(
                """
                UPDATE organizations SET
                    address = COALESCE(?, address),
                    inn = COALESCE(?, inn),
                    updated_at = ?
                WHERE id = ?
                """,
                (addr_val, inn_val, now, surviving),
            )
    return surviving


def _pick_org_merge_ids(
    current: sqlite3.Row | dict[str, Any],
    conflict: sqlite3.Row | dict[str, Any],
) -> tuple[int, int]:
    """Оставляем карточку с ИНН, при равенстве — с меньшим id (старше)."""
    cur_id = int(current["id"])
    other_id = int(conflict["id"])
    cur_inn = (current["inn"] or "").strip()
    other_inn = (conflict["inn"] or "").strip()
    if cur_inn and not other_inn:
        return cur_id, other_id
    if other_inn and not cur_inn:
        return other_id, cur_id
    keep = min(cur_id, other_id)
    drop = max(cur_id, other_id)
    return keep, drop


def update_organization(
    org_id: int,
    *,
    name: str,
    address: str | None = None,
    postal_code: str | None = None,
    phone: str | None = None,
    email: str | None = None,
    inn: str | None = None,
    kpp: str | None = None,
    is_accredited: bool = False,
    fsa_registry_number: str | None = None,
    org_type: str = "unknown",
    db_path: str | Path = DB_PATH_DEFAULT,
) -> bool:
    """Обновляет организацию по id (ручное редактирование в GUI)."""
    now = datetime.now().isoformat()
    name_normalized = normalize_org_name(name)
    inn_key = (inn or "").strip()
    with get_connection(db_path) as conn:
        conflict = _find_org_dedup_conflict(
            conn,
            org_id=org_id,
            name_normalized=name_normalized,
            inn_key=inn_key,
        )
        if conflict is not None:
            current = conn.execute(
                "SELECT * FROM organizations WHERE id = ?", (org_id,)
            ).fetchone()
            if current is None:
                return False
            keep_id, drop_id = _pick_org_merge_ids(current, conflict)
        else:
            try:
                cursor = conn.execute(
                    """
                    UPDATE organizations SET
                        name = ?,
                        name_normalized = ?,
                        address = ?,
                        postal_code = ?,
                        phone = ?,
                        email = ?,
                        inn = ?,
                        kpp = ?,
                        is_accredited = ?,
                        fsa_registry_number = ?,
                        org_type = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        name.strip(),
                        name_normalized,
                        address,
                        postal_code,
                        phone,
                        email,
                        inn,
                        kpp,
                        int(is_accredited),
                        fsa_registry_number,
                        org_type,
                        now,
                        org_id,
                    ),
                )
            except sqlite3.IntegrityError:
                _log.warning(
                    "update_organization UNIQUE id=%s inn=%s — merge",
                    org_id,
                    inn,
                    extra={"tag": "Организации"},
                )
                current = conn.execute(
                    "SELECT * FROM organizations WHERE id = ?", (org_id,)
                ).fetchone()
                conflict = _find_org_dedup_conflict(
                    conn,
                    org_id=org_id,
                    name_normalized=name_normalized,
                    inn_key=inn_key,
                )
                if current is None or conflict is None:
                    raise
                keep_id, drop_id = _pick_org_merge_ids(current, conflict)
            else:
                return cursor.rowcount > 0

    merge_organizations(keep_id, drop_id, db_path=db_path)
    return True


def get_last_document_extraction(
    db_path: str | Path = DB_PATH_DEFAULT,
) -> dict[str, Any] | None:
    """Последняя обработанная заявка (для панели сводки в GUI)."""
    with get_connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT d.*,
                   c.name AS customer_name,
                   m.name AS manufacturer_name
            FROM document_extractions d
            LEFT JOIN organizations c ON c.id = d.customer_org_id
            LEFT JOIN organizations m ON m.id = d.manufacturer_org_id
            ORDER BY d.extracted_at DESC
            LIMIT 1
            """
        ).fetchone()
        return dict(row) if row else None


def find_organization_id_by_name(
    name: str,
    db_path: str | Path = DB_PATH_DEFAULT,
) -> int | None:
    if not name or not name.strip():
        return None
    normalized = normalize_org_name(name)
    with get_connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT id FROM organizations
            WHERE name_normalized = ? OR name = ?
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (normalized, name.strip()),
        ).fetchone()
        return int(row["id"]) if row else None


def delete_organization(
    org_id: int,
    db_path: str | Path = DB_PATH_DEFAULT,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Удаляет организацию. force: обнуляет FK в orders/order_marks/extractions."""
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT id, name FROM organizations WHERE id = ?", (org_id,)
        ).fetchone()
        if not row:
            return {"ok": False, "reason": "not_found"}
        o_refs = conn.execute(
            """
            SELECT COUNT(*) AS n FROM orders
            WHERE customer_org_id = ? OR manufacturer_org_id = ?
            """,
            (org_id, org_id),
        ).fetchone()["n"]
        m_refs = conn.execute(
            "SELECT COUNT(*) AS n FROM order_marks WHERE manufacturer_org_id = ?",
            (org_id,),
        ).fetchone()["n"]
        e_refs = conn.execute(
            """
            SELECT COUNT(*) AS n FROM document_extractions
            WHERE customer_org_id = ? OR manufacturer_org_id = ?
            """,
            (org_id, org_id),
        ).fetchone()["n"]
        total = int(o_refs) + int(m_refs) + int(e_refs)
        if total and not force:
            return {
                "ok": False,
                "reason": "in_use",
                "refs": total,
                "name": row["name"],
            }
        if force:
            conn.execute(
                "UPDATE orders SET customer_org_id = NULL WHERE customer_org_id = ?",
                (org_id,),
            )
            conn.execute(
                "UPDATE orders SET manufacturer_org_id = NULL WHERE manufacturer_org_id = ?",
                (org_id,),
            )
            conn.execute(
                "UPDATE order_marks SET manufacturer_org_id = NULL WHERE manufacturer_org_id = ?",
                (org_id,),
            )
            conn.execute(
                "UPDATE document_extractions SET customer_org_id = NULL WHERE customer_org_id = ?",
                (org_id,),
            )
            conn.execute(
                "UPDATE document_extractions SET manufacturer_org_id = NULL WHERE manufacturer_org_id = ?",
                (org_id,),
            )
        conn.execute("DELETE FROM organizations WHERE id = ?", (org_id,))
        return {"ok": True, "name": row["name"], "unlinked": total}
