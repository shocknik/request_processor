"""
Инвентаризация корпуса ТУ → data/knowledge/manufacturer_v1/tu_index.yaml

Не парсит содержимое .doc (это отдельный этап), только каталог и эвристика tu_id.

Запуск:
  .venv\\Scripts\\python.exe scripts\\inventory_tu_corpus.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("PyYAML required")
    sys.exit(1)

ROOT = Path(__file__).resolve().parents[1]
TU_DIR = ROOT / "data" / "training" / "rag_corpus" / "tu"
OUT = ROOT / "data" / "knowledge" / "manufacturer_v1" / "tu_index.yaml"

_TU_ID = re.compile(
    r"(?:ТУ|TU)\s*([0-9]{2}(?:\.[0-9]+)?[.\-А-ЯA-ZКк]{0,10}[0-9.\-–]+[0-9]{2,4})",
    re.IGNORECASE,
)
_TU_ALT = re.compile(r"(\d{2}\.К\d{2}-\d{3}-\d{4})", re.IGNORECASE)
_TU_ALT2 = re.compile(r"(27\.32\.\d+-\d+-\d{9,}-\d{4})", re.IGNORECASE)


def guess_tu_id(name: str) -> str | None:
    for pat in (_TU_ID, _TU_ALT, _TU_ALT2):
        m = pat.search(name)
        if m:
            return m.group(1).strip() if m.lastindex else m.group(0).strip()
    # «058ТУ», «096ТУ»
    m = re.search(r"(\d{2,3})\s*ТУ", name, re.I)
    if m:
        return f"{m.group(1)}ТУ"
    return None


def main() -> None:
    if not TU_DIR.is_dir():
        print(f"TU dir missing: {TU_DIR}")
        sys.exit(1)

    docs = []
    for path in sorted(TU_DIR.iterdir(), key=lambda p: p.name.lower()):
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".doc", ".docx", ".pdf", ".rtf"}:
            continue
        docs.append(
            {
                "file_name": path.name,
                "tu_id": guess_tu_id(path.name),
                "ext": path.suffix.lower(),
                "status": "pending",
                "brands_hint": [],
                "notes": "",
            }
        )

    payload = {
        "version": 1,
        "source_dir": "data/training/rag_corpus/tu",
        "manufacturer_hint": "основной производитель корпуса (см. client_profiles.local)",
        "count": len(docs),
        "documents": docs,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    with_id = sum(1 for d in docs if d["tu_id"])
    print(f"Wrote {OUT}")
    print(f"Documents: {len(docs)}, with guessed tu_id: {with_id}")


if __name__ == "__main__":
    main()
