"""
Загрузка YAML-семейств документов (periodic, LAN, …).

См. data/families/*.yaml, Obsidian 35a §7–8.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from ...config import FAMILIES_DIR


@dataclass
class DocumentFamily:
    id: str
    display_name: str
    document_type: str
    config_path: Path
    priority: int = 100
    enabled: bool = True
    min_marks_threshold: int = 1
    confidence_threshold: float = 0.85
    sender_patterns: list[re.Pattern[str]] = field(default_factory=list)
    detection_markers: list[re.Pattern[str]] = field(default_factory=list)
    detection_table_hints: list[re.Pattern[str]] = field(default_factory=list)
    mark_patterns: list[tuple[str, re.Pattern[str]]] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    def match_score(self, text: str) -> float:
        """0..1 — насколько текст похож на это семейство."""
        if not text or not self.enabled:
            return 0.0
        head = text[:4000]
        score = 0.0
        hits = 0
        total = 0

        for pattern in self.detection_markers:
            total += 1
            if pattern.search(head):
                hits += 1
        for pattern in self.detection_table_hints:
            total += 1
            if pattern.search(head):
                hits += 1
        for pattern in self.sender_patterns:
            total += 1
            if pattern.search(head):
                hits += 1

        if total:
            score = hits / total

        if self.detection_table_hints:
            table_hits = sum(1 for pattern in self.detection_table_hints if pattern.search(head))
            if table_hits:
                table_ratio = table_hits / len(self.detection_table_hints)
                score = max(score, 0.25 + table_ratio * 0.65)

        brand_hints = self.raw.get("detection", {}).get("brand_hints") or []
        for hint in brand_hints:
            if hint.lower() in head.lower():
                score = min(1.0, score + 0.2)
                break

        return round(score, 2)

    def is_confident_match(self, text: str) -> bool:
        return self.match_score(text) >= self.confidence_threshold


def _compile_list(patterns: list[str]) -> list[re.Pattern[str]]:
    return [re.compile(p, re.IGNORECASE) for p in patterns if p]


def _load_family(path: Path) -> DocumentFamily:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    detection = data.get("detection") or {}
    mark_patterns: list[tuple[str, re.Pattern[str]]] = []
    for item in data.get("mark_patterns") or []:
        kind = str(item.get("kind") or "generic")
        pattern = item.get("pattern")
        if pattern:
            mark_patterns.append((kind, re.compile(pattern, re.IGNORECASE)))

    return DocumentFamily(
        id=str(data.get("id") or path.stem),
        display_name=str(data.get("display_name") or path.stem),
        document_type=str(data.get("document_type") or "unknown"),
        config_path=path,
        priority=int(data.get("priority", 100)),
        enabled=bool(data.get("enabled", True)),
        min_marks_threshold=int(data.get("min_marks_threshold", 1)),
        confidence_threshold=float(data.get("confidence_threshold", 0.85)),
        sender_patterns=_compile_list(data.get("sender_patterns") or []),
        detection_markers=_compile_list(detection.get("markers") or []),
        detection_table_hints=_compile_list(detection.get("table_hints") or []),
        mark_patterns=mark_patterns,
        raw=data,
    )


class FamilyRegistry:
    def __init__(self, families: list[DocumentFamily]) -> None:
        self._families = sorted(families, key=lambda f: f.priority)

    @classmethod
    def from_directory(cls, directory: Path | None = None) -> FamilyRegistry:
        root = directory or FAMILIES_DIR
        families: list[DocumentFamily] = []
        if root.is_dir():
            for path in sorted(root.glob("*.yaml")):
                families.append(_load_family(path))
        return cls(families)

    @property
    def families(self) -> list[DocumentFamily]:
        return list(self._families)

    def detect_best(self, text: str) -> DocumentFamily | None:
        best: DocumentFamily | None = None
        best_score = 0.0
        for family in self._families:
            if not family.enabled:
                continue
            score = family.match_score(text)
            if score > best_score:
                best_score = score
                best = family
        if best and best_score >= best.confidence_threshold:
            return best
        return None

    def get(self, family_id: str) -> DocumentFamily | None:
        for family in self._families:
            if family.id == family_id:
                return family
        return None


@lru_cache(maxsize=1)
def get_family_registry() -> FamilyRegistry:
    return FamilyRegistry.from_directory()