"""
Полуавтомат: кандидаты марок / испытаний / пунктов из raw_text ТУ.

Пишет JSONL в data/knowledge/manufacturer_v1/drafts/

  .venv\\Scripts\\python.exe scripts\\mine_tu_candidates.py
  .venv\\Scripts\\python.exe scripts\\mine_tu_candidates.py --pilots
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

RAW_DIR = ROOT / "data" / "knowledge" / "manufacturer_v1" / "raw_text"
DRAFT_DIR = ROOT / "data" / "knowledge" / "manufacturer_v1" / "drafts"
INDEX_PATH = ROOT / "data" / "knowledge" / "manufacturer_v1" / "tu_index.yaml"

# Пилотные ТУ (по частоте в заявках / разнообразию типов)
PILOT_TU_IDS = (
    "16.К99-058-2014",
    "16.К99-061-2013",
    "16.К99-037-2009",
    "27.32.13-099-47273194-2020",
    "16.К99-073-2015",
    "27.32.13-108-47273194-2022",
    "27.32.13-111-47273194-2022",
    "16.К99-014-2004",
    "16.К99-025-2005",
    "16.К99-010-2004",
    "16.К99-004-01",
    "16.К99-006-2001",
)

# Марка: буквы + опционально нг(А)-… + NхM
_MARK_RE = re.compile(
    r"\b("
    r"[А-ЯЁA-Z]{2,}[А-ЯЁA-Za-z0-9\-]{0,20}"
    r"(?:нг\s*\(\s*[АA]\s*\))?"
    r"(?:-[A-Za-zА-ЯЁ]{1,8})?"
    r"\s+\d+\s*[хx×]\s*[\d.,]+"
    r"(?:\s*[хx×]\s*[\d.,]+)?"
    r")\b",
    re.IGNORECASE,
)

_CLAUSE_RE = re.compile(
    r"(?m)^(\d+(?:\.\d+){1,4})\s+(.{10,200})$"
)

_TEST_HINT = re.compile(
    r"(?i)("
    r"испытан\w*|стойкость\w*|сопротивлен\w*|напряжен\w*|"
    r"огнестойк\w*|влажност\w*|температур\w*|изгиб\w*|"
    r"солнечн\w*|радиац\w*|затухан\w*|емкост\w*|герметичн\w*"
    r")"
)

_METHOD_HINT = re.compile(
    r"(?i)(ГОСТ\s*[\d.\-–]+|метод\s*[\d.\-–]+|IEC\s*[\d.\-–]+|по\s+методике)"
)

_BRAND_HINT = re.compile(
    r"\b(СПЕЦЛАН|КСБ|КПС|СКАБ|СКОР|КИПв|ПВС|ВВГ|FLEXICORE|CMEL|РК\s*\d)\w*",
    re.IGNORECASE,
)


def load_index() -> dict:
    import yaml

    if not INDEX_PATH.is_file():
        return {"documents": []}
    return yaml.safe_load(INDEX_PATH.read_text(encoding="utf-8")) or {"documents": []}


def iter_raw_files(pilots_only: bool) -> list[tuple[str, Path, dict]]:
    """(tu_id, path, meta)"""
    index = load_index()
    by_raw = {}
    for d in index.get("documents") or []:
        rt = d.get("raw_text")
        if rt:
            by_raw[Path(rt).name] = d

    out: list[tuple[str, Path, dict]] = []
    for path in sorted(RAW_DIR.glob("*.txt")):
        meta = by_raw.get(path.name) or {"tu_id": path.stem, "file_name": path.name}
        tu_id = meta.get("tu_id") or path.stem
        if pilots_only:
            if not any(p in str(tu_id) or p in path.stem for p in PILOT_TU_IDS):
                # also match shortened
                if not any(p.split("-")[0] in path.stem for p in PILOT_TU_IDS if "К99" in p):
                    ok = False
                    for p in PILOT_TU_IDS:
                        key = p.replace("16.К99-", "").replace("27.32.13-", "")[:7]
                        if key and key in path.stem:
                            ok = True
                            break
                    if not ok:
                        continue
        out.append((str(tu_id), path, meta))
    return out


def mine_text(tu_id: str, text: str, file_name: str) -> dict[str, list[dict]]:
    marks: list[dict] = []
    seen_m: set[str] = set()
    for m in _MARK_RE.finditer(text):
        mark = re.sub(r"\s+", " ", m.group(1)).strip()
        key = mark.lower()
        if key in seen_m or len(mark) < 8:
            continue
        # filter noise
        if re.match(r"^\d", mark):
            continue
        seen_m.add(key)
        brands = _BRAND_HINT.findall(mark)
        marks.append(
            {
                "tu_id": tu_id,
                "source_file": file_name,
                "mark": mark,
                "brand_hint": brands[0] if brands else None,
                "status": "candidate",
            }
        )

    requirements: list[dict] = []
    methods: list[dict] = []
    tests: list[dict] = []
    seen_c: set[str] = set()

    for m in _CLAUSE_RE.finditer(text):
        cid, body = m.group(1), m.group(2).strip()
        body = re.sub(r"\s+", " ", body)
        key = f"{cid}:{body[:40]}"
        if key in seen_c:
            continue
        seen_c.add(key)
        row = {
            "tu_id": tu_id,
            "source_file": file_name,
            "clause_id": cid,
            "text": body[:300],
            "status": "candidate",
        }
        if _METHOD_HINT.search(body):
            methods.append({**row, "kind": "method"})
        elif _TEST_HINT.search(body):
            requirements.append({**row, "kind": "requirement"})
            # also as test name candidate
            tests.append(
                {
                    "tu_id": tu_id,
                    "source_file": file_name,
                    "phrase": body[:200],
                    "clause_id": cid,
                    "status": "candidate",
                }
            )

    # free-standing test-like lines
    for line in text.splitlines():
        line = line.strip()
        if 15 < len(line) < 180 and _TEST_HINT.search(line) and not re.match(r"^\d+\.", line):
            tests.append(
                {
                    "tu_id": tu_id,
                    "source_file": file_name,
                    "phrase": re.sub(r"\s+", " ", line)[:200],
                    "clause_id": None,
                    "status": "candidate",
                }
            )

    # dedupe tests by phrase lower
    seen_t: set[str] = set()
    tests_u: list[dict] = []
    for t in tests:
        k = t["phrase"].lower()
        if k in seen_t:
            continue
        seen_t.add(k)
        tests_u.append(t)

    return {
        "marks": marks[:200],
        "requirements": requirements[:300],
        "methods": methods[:200],
        "tests": tests_u[:300],
    }


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilots", action="store_true", help="только пилотные ТУ")
    args = ap.parse_args()

    DRAFT_DIR.mkdir(parents=True, exist_ok=True)
    files = iter_raw_files(pilots_only=args.pilots)
    if not files:
        print("No raw_text files. Run extract_tu_text.py first.")
        sys.exit(1)

    all_marks: list[dict] = []
    all_req: list[dict] = []
    all_meth: list[dict] = []
    all_tests: list[dict] = []
    summary: list[dict] = []

    for tu_id, path, meta in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        mined = mine_text(tu_id, text, meta.get("file_name") or path.name)
        all_marks.extend(mined["marks"])
        all_req.extend(mined["requirements"])
        all_meth.extend(mined["methods"])
        all_tests.extend(mined["tests"])
        summary.append(
            {
                "tu_id": tu_id,
                "file": meta.get("file_name"),
                "raw": path.name,
                "marks": len(mined["marks"]),
                "requirements": len(mined["requirements"]),
                "methods": len(mined["methods"]),
                "tests": len(mined["tests"]),
                "chars": len(text),
            }
        )
        print(
            f"{tu_id}: marks={len(mined['marks'])} req={len(mined['requirements'])} "
            f"meth={len(mined['methods'])} tests={len(mined['tests'])}"
        )

    tag = "pilots" if args.pilots else "all"
    write_jsonl(DRAFT_DIR / f"marks_candidates_{tag}.jsonl", all_marks)
    write_jsonl(DRAFT_DIR / f"requirements_candidates_{tag}.jsonl", all_req)
    write_jsonl(DRAFT_DIR / f"methods_candidates_{tag}.jsonl", all_meth)
    write_jsonl(DRAFT_DIR / f"tests_candidates_{tag}.jsonl", all_tests)
    (DRAFT_DIR / f"summary_{tag}.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nWrote drafts to {DRAFT_DIR} ({tag})")
    print(
        f"Totals: marks={len(all_marks)} req={len(all_req)} "
        f"methods={len(all_meth)} tests={len(all_tests)}"
    )


if __name__ == "__main__":
    main()
