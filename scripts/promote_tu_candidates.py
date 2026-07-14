"""
Полуавтоматический «промоут» кандидатов → brands + test_synonyms + mark_templates.

Не заменяет ревью: пишет:
  - brands.yaml
  - test_synonyms.yaml  (merge с существующим)
  - mark_templates.yaml
  - drafts/review_queue_tests.jsonl  (несматченные — для оператора)

Запуск:
  .venv\\Scripts\\python.exe scripts\\promote_tu_candidates.py
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

DRAFTS = ROOT / "data" / "knowledge" / "manufacturer_v1" / "drafts"
KB = ROOT / "data" / "knowledge" / "manufacturer_v1"
INDEX = KB / "tu_index.yaml"

# Ручные/эвристические паттерны phrase-substring → canonical code
_HEURISTIC_PHRASE_TO_CODE: list[tuple[str, str, float]] = [
    (r"солнечн\w*\s+(?:излучен|радиац)", "solar_radiation", 0.92),
    (r"ультрафиолет|уф[\-\s]", "solar_radiation", 0.78),
    (r"повышенн\w*\s+влажност", "humidity", 0.92),
    (r"влажност\w*\s+воздух", "humidity", 0.9),
    (r"пониженн\w*\s+температур", "temp_low", 0.92),
    (r"повышенн\w*\s+температур", "temp_high", 0.9),
    (r"изменен\w*\s+температур|циклическ\w*\s+температур", "temp_cycling", 0.88),
    (r"сопротивлен\w*\s+изоляц", "электрическое_сопротивление_изоляции_тпж", 0.9),
    (r"сопротивлен\w*\s+(?:тпж|жил|токопровод)", "электрическое_сопротивление_тпж", 0.9),
    (r"электрическ\w*\s+сопротивлен\w*\s+жил", "электрическое_сопротивление_тпж", 0.88),
    (r"испытан\w*\s+напряжен", "испытание_напряжением", 0.92),
    (r"напряжен\w*\s+\d", "испытание_напряжением", 0.75),
    (r"огнестойк", "огнестойкость", 0.9),
    (r"нераспространен\w*\s+горен", "огнестойкость", 0.72),
    (r"простому\s+изгибу|стойкост\w*\s+к\s+изгибу", "стойкость_к_простому_изгибу_100_циклов", 0.82),
    (r"затухан\w*\s+экранир", "измерение_затухания_экранирования", 0.88),
    (r"\bемкост|\bиндуктивн", "измерение_емкостииндуктивности", 0.8),
    (r"герметичн", "испытание_на_частичную_герметичность_воздух", 0.75),
    (r"гидростатическ", "испытание_на_гидростатическое_давление_продольное_24_ч", 0.8),
]


def _load_yaml(path: Path) -> dict:
    import yaml

    if not path.is_file():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _dump_yaml(path: Path, data: dict) -> None:
    import yaml

    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _norm_phrase(s: str) -> str:
    s = s.lower().replace("\xa0", " ")
    s = re.sub(r"\s+", " ", s).strip(" .;:")
    return s


def load_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def brand_from_mark(mark: str) -> str | None:
    m = re.match(
        r"^([А-ЯЁA-Z]{2,}[А-ЯЁA-Za-z0-9]*(?:нг)?)",
        mark.strip(),
        re.IGNORECASE,
    )
    if not m:
        return None
    b = m.group(1)
    # cut fire class start
    b = re.split(r"нг\s*\(", b, maxsplit=1)[0]
    b = re.sub(r"(нг|ls|hf|frls|frhf)$", "", b, flags=re.I)
    return b.strip("-") or None


def match_test_code(phrase: str, test_codes: set[str], test_names: dict[str, str]) -> tuple[str | None, float, str]:
    """Return (code, conf, how)."""
    low = _norm_phrase(phrase)
    if len(low) < 12:
        return None, 0.0, ""

    # 1) heuristics
    for pat, code, conf in _HEURISTIC_PHRASE_TO_CODE:
        if re.search(pat, low, re.I):
            return code, conf, "heuristic"

    # 2) substring of test_items.name
    best: tuple[str | None, float, str] = (None, 0.0, "")
    for code, name in test_names.items():
        n = _norm_phrase(name)
        if len(n) < 8:
            continue
        if n in low or (len(n) > 15 and low in n):
            conf = 0.85 if n in low else 0.7
            if conf > best[1]:
                best = (code, conf, "test_items_name")
    return best


def promote_marks(marks: list[dict]) -> tuple[list[dict], list[dict]]:
    brands_c: Counter[str] = Counter()
    templates: dict[str, dict] = {}
    for row in marks:
        mark = (row.get("mark") or "").strip()
        if len(mark) < 8:
            continue
        # noise filters
        if re.search(r"инв|дубл|таблиц|проверк|состав|определен", mark, re.I):
            continue
        brand = row.get("brand_hint") or brand_from_mark(mark)
        if brand:
            brands_c[brand] += 1
        key = mark.lower()
        if key not in templates:
            templates[key] = {
                "example_full": mark,
                "brand": brand,
                "tu_ids": [],
                "count": 0,
                "status": "candidate",
            }
        t = templates[key]
        t["count"] += 1
        tu = row.get("tu_id")
        if tu and tu not in t["tu_ids"]:
            t["tu_ids"].append(tu)

    _NOISE_BRANDS = {
        "pe", "pvc", "pur", "ls", "hf", "fr", "zh", "utp", "ftp", "sftp",
        "frlsltx", "frls", "frhf", "ng", "xlpe", "lszh", "ok", "tu", "gost",
        "более", "кабеля", "кабель", "провод", "марки", "типа", "см", "мм",
    }
    brands = [
        {"brand": b, "count": c, "status": "candidate"}
        for b, c in brands_c.most_common()
        if c >= 1
        and len(b) >= 3
        and b.lower() not in _NOISE_BRANDS
        and not b.isdigit()
        and not re.match(r"^[а-яё]+$", b)  # только кирилл. слово без цифр/латиницы — часто мусор
        or (len(b) >= 3 and any(ch.isupper() or ch.isdigit() for ch in b) and b.lower() not in _NOISE_BRANDS)
    ]
    # re-filter properly (the or above is messy) — rebuild cleanly
    brands = []
    for b, c in brands_c.most_common():
        if c < 1 or len(b) < 3 or b.isdigit():
            continue
        low = b.lower()
        if low in _NOISE_BRANDS:
            continue
        # reject pure lowercase russian dictionary words
        if re.fullmatch(r"[а-яё]{3,}", b):
            continue
        brands.append({"brand": b, "count": c, "status": "candidate"})
    mark_templates = sorted(templates.values(), key=lambda x: (-x["count"], x["example_full"]))
    return brands, mark_templates


def promote_tests(
    tests: list[dict],
    existing_syn: list[dict],
    test_codes: set[str],
    test_names: dict[str, str],
) -> tuple[list[dict], list[dict]]:
    existing_phrases = {_norm_phrase(s.get("phrase", "")) for s in existing_syn if s.get("phrase")}
    new_syn: list[dict] = list(existing_syn)
    review: list[dict] = []
    seen_new: set[str] = set(existing_phrases)

    # frequency of phrases
    phrase_freq: Counter[str] = Counter()
    phrase_ex: dict[str, dict] = {}
    for row in tests:
        ph = _norm_phrase(row.get("phrase") or "")
        if len(ph) < 15 or len(ph) > 180:
            continue
        if re.search(r"таблиц|состав\s+при|инв№|типовые\s+испытания\s*$", ph):
            continue
        phrase_freq[ph] += 1
        phrase_ex[ph] = row

    for ph, freq in phrase_freq.most_common(500):
        if ph in seen_new:
            continue
        code, conf, how = match_test_code(ph, test_codes, test_names)
        sample = phrase_ex[ph]
        if code and conf >= 0.75:
            new_syn.append(
                {
                    "phrase": sample.get("phrase", ph)[:200],
                    "canonical_code": code,
                    "confidence": round(conf, 2),
                    "source": f"auto_{how}",
                    "freq": freq,
                    "tu_id": sample.get("tu_id"),
                }
            )
            seen_new.add(ph)
        elif freq >= 2:
            review.append(
                {
                    "phrase": sample.get("phrase", ph)[:200],
                    "freq": freq,
                    "tu_id": sample.get("tu_id"),
                    "status": "needs_review",
                    "suggested_code": code,
                    "suggested_conf": conf,
                }
            )

    return new_syn, review


def update_index_status() -> dict:
    import yaml

    data = yaml.safe_load(INDEX.read_text(encoding="utf-8")) if INDEX.is_file() else {}
    docs = data.get("documents") or []
    raw_dir = KB / "raw_text"
    for d in docs:
        rt = d.get("raw_text")
        path = ROOT / rt if rt else None
        if path and path.is_file() and path.stat().st_size > 100:
            if d.get("status") in (None, "pending", "inventoried"):
                d["status"] = "clauses_extracted"
        # brands_hint from mark templates later optional
    data["documents"] = docs
    INDEX.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    counts = Counter(d.get("status") for d in docs)
    return dict(counts)


def main() -> None:
    from request_processor.persistence.sqlite_repo import init_db, list_test_items
    from request_processor.config import DB_PATH_DEFAULT

    init_db(DB_PATH_DEFAULT)
    items = list_test_items(limit=500, db_path=DB_PATH_DEFAULT)
    test_names = {str(i["code"]): str(i.get("name") or "") for i in items}
    test_codes = set(test_names)

    marks = load_jsonl(DRAFTS / "marks_candidates_all.jsonl")
    if not marks:
        marks = load_jsonl(DRAFTS / "marks_candidates_pilots.jsonl")
    tests = load_jsonl(DRAFTS / "tests_candidates_all.jsonl")
    if not tests:
        tests = load_jsonl(DRAFTS / "tests_candidates_pilots.jsonl")

    brands, mark_templates = promote_marks(marks)
    _dump_yaml(KB / "brands.yaml", {"version": 1, "brands": brands})
    _dump_yaml(
        KB / "mark_templates.yaml",
        {"version": 1, "templates": mark_templates[:500]},
    )

    existing = _load_yaml(KB / "test_synonyms.yaml")
    existing_syn = list(existing.get("synonyms") or [])
    code_aliases = existing.get("code_aliases") or {}
    new_syn, review = promote_tests(tests, existing_syn, test_codes, test_names)

    # dedupe by phrase lower, keep highest conf
    by_ph: dict[str, dict] = {}
    for s in new_syn:
        k = _norm_phrase(s.get("phrase") or "")
        if not k:
            continue
        prev = by_ph.get(k)
        if prev is None or float(s.get("confidence") or 0) > float(prev.get("confidence") or 0):
            by_ph[k] = s

    _dump_yaml(
        KB / "test_synonyms.yaml",
        {
            "version": 1,
            "synonyms": list(by_ph.values()),
            "code_aliases": code_aliases,
        },
    )

    DRAFTS.mkdir(parents=True, exist_ok=True)
    with (DRAFTS / "review_queue_tests.jsonl").open("w", encoding="utf-8") as f:
        for row in review[:400]:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    status_counts = update_index_status()

    # clear synonyms cache if used
    try:
        from request_processor.knowledge.synonyms import load_test_synonyms

        load_test_synonyms.cache_clear()
    except Exception:
        pass

    print(f"brands: {len(brands)}")
    print(f"mark_templates: {len(mark_templates)}")
    print(f"synonyms: {len(by_ph)} (was {len(existing_syn)})")
    print(f"review_queue tests: {len(review)}")
    print(f"tu_index status: {status_counts}")
    print(f"Wrote {KB / 'brands.yaml'}")
    print(f"Wrote {KB / 'mark_templates.yaml'}")
    print(f"Wrote {KB / 'test_synonyms.yaml'}")


if __name__ == "__main__":
    main()
