"""
Словарь известных марок (из справочника 300 и дополнений).

Нужен, чтобы в письме/свободном тексте узнавать названия вроде «ВВГ», «КПС»,
«СПЕЦЛАН» даже без сечения «3х1,5».

Источник истины (в git и в сборке zip/pip)::

    src/request_processor/extraction/resources/mark_lexicon_v1.yaml

Опционально поверх (локально, не в git)::

    data/knowledge/mark_lexicon/mark_lexicon_v1.yaml

Порядок чтения: сначала встроенный файл пакета, затем локальный — если есть,
он **дополняет/перекрывает** (удобно для экспериментов на dev, не для «истины»).
Фактически: локальный, если есть, иначе пакетный (см. resolve_lexicon_path).
"""

from __future__ import annotations

import logging
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from ..config import DATA_DIR

_log = logging.getLogger(__name__)

_RESOURCES = Path(__file__).resolve().parent / "resources"
_LOCAL_DIR = DATA_DIR / "knowledge" / "mark_lexicon"
_LOCAL_YAML = _LOCAL_DIR / "mark_lexicon_v1.yaml"
_PACKAGED_YAML = _RESOURCES / "mark_lexicon_v1.yaml"

# Минимальная длина имени: 2 — «КГ», «ПВ»; короче не берём
_MIN_BRAND_LEN = 2


def lexicon_paths() -> list[Path]:
    """Пути к словарю: пакетный (git) — основной; локальный — запасной."""
    return [_PACKAGED_YAML, _LOCAL_YAML]


def resolve_lexicon_path() -> Path | None:
    """
    Какой файл реально читаем.

    1. Переменная окружения REQUEST_PROCESSOR_MARK_LEXICON (явный override)
    2. Встроенный yaml в пакете (git + zip) — **источник истины**
    3. data/knowledge/… — только если пакетного нет
    """
    env = (os.environ.get("REQUEST_PROCESSOR_MARK_LEXICON") or "").strip()
    if env:
        p = Path(env)
        if p.is_file():
            return p
    if _PACKAGED_YAML.is_file():
        return _PACKAGED_YAML
    # installed wheel: resources рядом с пакетом
    try:
        from importlib import resources

        ref = resources.files("request_processor.extraction").joinpath(
            "resources/mark_lexicon_v1.yaml"
        )
        with resources.as_file(ref) as fp:
            if fp.is_file():
                return Path(fp)
    except Exception:  # noqa: BLE001
        pass
    if _LOCAL_YAML.is_file():
        return _LOCAL_YAML
    return None


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Нужен PyYAML: pip install pyyaml") from exc
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        return {}
    return data


def _normalize_key(name: str) -> str:
    s = (name or "").strip().lower().replace("ё", "е")
    s = s.replace("×", "х").replace("x", "х")
    s = re.sub(r"\s+", "", s)
    return s


def _strip_fire_suffix(brand: str) -> str:
    """ВВГнг(А)-LS → ВВГ; СПЕЦЛАН UTP-3нг(А)-FRHF → СПЕЦЛАН UTP-3."""
    b = brand.strip()
    b = re.sub(r"нг\s*\([^)]*\).*$", "", b, flags=re.IGNORECASE)
    b = re.sub(
        r"-(?:LS|HF|FRLS|FRHF|LSLTx|LSLT|FR|ХЛ|УФ|УХЛ|Т)\b.*$",
        "",
        b,
        flags=re.IGNORECASE,
    )
    return b.strip("- ").strip()


@lru_cache(maxsize=4)
def load_mark_lexicon(*, force_reload: bool = False) -> dict[str, Any]:
    """
    Загружает словарь.

    Returns:
        {
          "source": str,
          "brands": list[str],          # канонические имена (как в справочнике)
          "by_key": dict[str, str],     # нормализованный ключ → канон
          "examples": dict[str, list[str]],
        }
    """
    if force_reload:
        load_mark_lexicon.cache_clear()

    path = resolve_lexicon_path()
    if path is None:
        _log.warning("mark lexicon: файл не найден, словарь пуст")
        return {"source": "", "brands": [], "by_key": {}, "examples": {}}

    data = _load_yaml(path)
    brands_raw = data.get("brands") or []
    by_key: dict[str, str] = {}
    examples: dict[str, list[str]] = {}
    brands: list[str] = []

    for item in brands_raw:
        if isinstance(item, str):
            name = item.strip()
            ex: list[str] = []
        elif isinstance(item, dict):
            name = str(item.get("name") or item.get("brand") or "").strip()
            ex = [str(x) for x in (item.get("examples") or []) if x]
        else:
            continue
        if len(name) < _MIN_BRAND_LEN:
            continue
        brands.append(name)
        examples[name] = ex

    brand_set = set(brands)
    # 1) полные имена как есть
    for name in brands:
        by_key[_normalize_key(name)] = name
        by_key[_normalize_key(name.replace(" ", ""))] = name
    # 2) «голая» база (ВВГ из ВВГнг(А)-LS): не подменять КГ → КГ-ХЛ
    for name in brands:
        base = _strip_fire_suffix(name)
        if len(base) < _MIN_BRAND_LEN or base == name:
            continue
        bk = _normalize_key(base)
        if bk not in by_key:
            by_key[bk] = base if base in brand_set else name
        elif base in brand_set:
            # предпочитаем точное короткое имя из словаря
            if by_key[bk] not in brand_set or len(base) < len(by_key[bk]):
                by_key[bk] = base

    # 3) короткие LAN-префиксы: «U/UTP» из «U/UTP Cat 5e PE»
    _lan_short = re.compile(
        r"^((?:[USF]/)?/?UTP|S/?FTP|SF/?TP)\b",
        re.IGNORECASE,
    )
    for name in brands:
        m = _lan_short.match(name.strip())
        if not m:
            continue
        short = m.group(1).upper().replace("У", "U")  # safety
        # канон: как в тексте справочника (U/UTP)
        canon_short = m.group(1)
        # нормализуем регистр: U/UTP
        parts = re.split(r"(/)", canon_short)
        canon_short = "".join(
            p.upper() if p != "/" else p for p in parts
        )
        sk = _normalize_key(canon_short)
        if sk not in by_key or len(by_key[sk]) > len(canon_short):
            by_key[sk] = canon_short
            if canon_short not in brands:
                brands.append(canon_short)
                examples.setdefault(canon_short, [name])

    # явные aliases из yaml + частые опечатки/перестановки
    default_aliases = {
        "КВПФэМ": "КВПЭфМ",
        "КВПФЭМ": "КВПЭфМ",
        "КВПФем": "КВПЭфМ",
        "KBPЭфМ": "КВПЭфМ",
        "U/UTQ": "U/UTP",
        "UТР": "U/UTP",
        "UТP": "U/UTP",
    }
    for alias, target in {**default_aliases, **(data.get("aliases") or {})}.items():
        a = _normalize_key(str(alias))
        t = str(target).strip()
        if a and t:
            by_key[a] = t

    _log.info(
        "mark lexicon loaded path=%s brands=%s keys=%s",
        path,
        len(brands),
        len(by_key),
    )
    return {
        "source": str(path),
        "brands": brands,
        "by_key": by_key,
        "examples": examples,
        "meta": {
            "version": data.get("version"),
            "title": data.get("title"),
            "source_note": data.get("source"),
        },
    }


def _fuzzy_lookup(name: str, brands: list[str], *, min_ratio: float = 0.82) -> str | None:
    """Близкое имя из словаря (КВПФэМ ≈ КВПЭфМ)."""
    from difflib import SequenceMatcher

    q = _normalize_key(name)
    if len(q) < 4:
        return None
    best: tuple[float, str] | None = None
    for b in brands:
        bk = _normalize_key(b)
        if abs(len(bk) - len(q)) > 3:
            continue
        # только «похожие» длины
        if not (bk[:2] == q[:2] or bk[:3] == q[:3]):
            # иначе слишком дорого и шумно
            if len(q) < 5:
                continue
        ratio = SequenceMatcher(None, q, bk).ratio()
        if ratio >= min_ratio and (best is None or ratio > best[0]):
            best = (ratio, b)
    return best[1] if best else None


def lookup_brand(name: str, *, fuzzy: bool = True) -> str | None:
    """Если name — известная марка (или близкая опечатка), вернуть канон."""
    lex = load_mark_lexicon()
    key = _normalize_key(name)
    if not key:
        return None
    if key in lex["by_key"]:
        return lex["by_key"][key]
    base = _normalize_key(_strip_fire_suffix(name))
    if base in lex["by_key"]:
        return lex["by_key"][base]
    if fuzzy:
        hit = _fuzzy_lookup(name, list(lex["brands"]))
        if hit:
            return hit
        # fuzzy по ключам коротких имён (U/UTP)
        hit = _fuzzy_lookup(name, list(lex["by_key"].values()))
        if hit:
            return hit
    return None


def find_lexicon_marks_in_text(text: str) -> list[tuple[str, int, int]]:
    """
    Ищет в тексте известные марки из словаря.

    Returns:
        список (каноническое_имя, start, end).
    """
    raw = (text or "").replace("\xa0", " ")
    if len(raw) < _MIN_BRAND_LEN:
        return []

    lex = load_mark_lexicon()
    brands: list[str] = list(lex["brands"])
    if not brands:
        return []

    # длинные имена первыми, чтобы «ВВГнг(А)-LS» победил «ВВГ»
    brands_sorted = sorted(set(brands), key=lambda s: (-len(s), s.lower()))

    found: list[tuple[str, int, int]] = []
    occupied: list[tuple[int, int]] = []

    def _overlaps(a: int, b: int) -> bool:
        for x, y in occupied:
            if a < y and b > x:
                return True
        return False

    def _add(canon: str, start: int, end: int) -> None:
        if _overlaps(start, end):
            return
        occupied.append((start, end))
        found.append((canon, start, end))

    # Текст для поиска: сохраняем регистр, но match case-insensitive
    for brand in brands_sorted:
        if len(brand) < _MIN_BRAND_LEN:
            continue
        pattern = re.compile(
            rf"(?<![А-ЯЁа-яёA-Za-z0-9])"
            rf"({re.escape(brand)})"
            rf"(?![А-ЯЁа-яёA-Za-z0-9\-])",
            re.IGNORECASE,
        )
        for m in pattern.finditer(raw):
            _add(brand, m.start(1), m.end(1))

    # Базы без нг(А)-… (ВВГ из ВВГнг…)
    bases_done: set[str] = set()
    for brand in brands_sorted:
        base = _strip_fire_suffix(brand)
        if len(base) < _MIN_BRAND_LEN:
            continue
        bk = _normalize_key(base)
        if bk in bases_done:
            continue
        bases_done.add(bk)
        if any(bk in _normalize_key(b) for b, _, _ in found):
            continue
        pattern = re.compile(
            rf"(?<![А-ЯЁа-яёA-Za-z0-9])"
            rf"({re.escape(base)})"
            rf"(?![А-ЯЁа-яёA-Za-z0-9\-])",
            re.IGNORECASE,
        )
        for m in pattern.finditer(raw):
            canon = lookup_brand(base, fuzzy=False) or base
            _add(canon, m.start(1), m.end(1))

    # Отдельные строки целиком — как в переписке:
    #   ВВГ
    #   U/UTP
    #   КВПФэМ
    line_pat = re.compile(
        r"(?m)^[ \t]*([А-ЯЁA-Za-z][А-ЯЁа-яёA-Za-z0-9/\-()]{1,48})[ \t]*$"
    )
    for m in line_pat.finditer(raw):
        token = m.group(1).strip()
        if len(token) < _MIN_BRAND_LEN:
            continue
        # не целые предложения
        if " " in token and not re.match(r"^(?:U|F|S|SF)/", token, re.I):
            if len(token.split()) > 3:
                continue
        canon = lookup_brand(token, fuzzy=True)
        if not canon:
            continue
        _add(canon, m.start(1), m.end(1))

    found.sort(key=lambda t: t[1])
    return found


def build_lexicon_from_handbook_pdf(
    pdf_path: Path | str,
    *,
    out_yaml: Path | None = None,
    out_jsonl: Path | None = None,
) -> dict[str, Any]:
    """
    Вытянуть словарь из PDF «Справочник 300…» и записать yaml (+ опционально jsonl).

    PDF остаётся локально; в репозиторий кладём только yaml со списком имён.
    """
    try:
        import pdfplumber
    except ImportError as exc:
        raise RuntimeError("Нужен pdfplumber") from exc
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("Нужен PyYAML") from exc

    path = Path(pdf_path)
    if not path.is_file():
        raise FileNotFoundError(f"PDF не найден: {path}")

    with pdfplumber.open(path) as pdf:
        text = "\n".join((pg.extract_text() or "") for pg in pdf.pages)

    current_group = ""
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if (
            not re.match(r"^\d{1,3}\s+", line)
            and re.search(
                r"кабел|провод|LAN|шнур|монтаж|контрол|телефон|сигнал|оптич|охран",
                line,
                re.I,
            )
            and len(line) < 90
            and "ГОСТ" not in line
            and "Справочник" not in line
        ):
            current_group = re.sub(
                r"\s+\d+\s+пример.*$", "", line, flags=re.I
            ).strip()
            continue

        m = re.match(r"^(\d{1,3})\s+(.+)$", line)
        if not m:
            continue
        num = int(m.group(1))
        if num < 1 or num > 320:
            continue
        rest = m.group(2)
        sm = re.search(
            r"(\d+\s*[×xх]\s*[\d.,/]+(?:\s*[×xх+]\s*[\d.,/]+)*)", rest
        )
        if not sm:
            continue
        mark_left = rest[: sm.start()].strip()
        size_part = rest[sm.start() :]
        full = f"{mark_left} {size_part}".strip()
        full = re.split(
            r"\s+(?=Силовые|Гибкие|Контрольные|Кабели|Провода|Монтажные|"
            r"Симметричные|Охран|Установоч|Коаксиал|СПЕЦ|Цифров|число |"
            r"для |ГОСТ|ТУ |профильные)",
            full,
            maxsplit=1,
        )[0].strip()
        full = full.replace("×", "х").replace("x", "х")
        full = re.sub(r"\s+", " ", full)
        brand = re.sub(r"\s+", " ", mark_left)
        if len(brand) < 2:
            continue
        rows.append(
            {
                "n": num,
                "brand": brand,
                "example": full[:140],
                "group": current_group[:100],
            }
        )

    # aggregate brands
    agg: dict[str, dict[str, Any]] = {}
    for r in rows:
        b = r["brand"]
        if b not in agg:
            agg[b] = {
                "name": b,
                "examples": [],
                "groups": [],
                "count": 0,
            }
        agg[b]["count"] += 1
        if r["example"] not in agg[b]["examples"] and len(agg[b]["examples"]) < 5:
            agg[b]["examples"].append(r["example"])
        g = r.get("group") or ""
        if g and g not in agg[b]["groups"]:
            agg[b]["groups"].append(g)

    brands_list = sorted(agg.values(), key=lambda x: (-x["count"], x["name"]))
    payload = {
        "version": 1,
        "title": "Словарь марок (справочник 300 маркоразмеров)",
        "source": f"{path.name}",
        "source_note": (
            "Практический справочник кабельных марок РФ, 300 примеров "
            "(общепром + Спецкабель). PDF не в git — только этот список имён."
        ),
        "stats": {
            "rows_parsed": len(rows),
            "unique_brands": len(brands_list),
        },
        "brands": brands_list,
        "aliases": {
            # частые OCR / латиница (можно расширять)
            "BBG": "ВВГ",
            "BBGнг": "ВВГнг(А)",
            "KCBur": "КСБнг(А)",
        },
    }

    out_yaml = out_yaml or _PACKAGED_YAML
    out_yaml.parent.mkdir(parents=True, exist_ok=True)
    with out_yaml.open("w", encoding="utf-8") as f:
        yaml.safe_dump(
            payload,
            f,
            allow_unicode=True,
            sort_keys=False,
            width=100,
        )

    if out_jsonl is not None:
        out_jsonl.parent.mkdir(parents=True, exist_ok=True)
        with out_jsonl.open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json_line(r) + "\n")

    load_mark_lexicon.cache_clear()
    return payload


def json_line(obj: dict[str, Any]) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False)
