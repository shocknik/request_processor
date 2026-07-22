"""
Сопоставление позиций программы испытаний с кодами прайса (S4 polish).

Порядок:
1. Явные phrase-rules (ПМИ-формулировки → code)
2. test_aliases (S5)
3. Точное / подстрочное имя прайса
4. Token-overlap fuzzy по именам прайса
5. map_requirements_to_tests (fallback)

Контекст программы (название, марка) помогает дизамбигуации
(«затухание ОК» ≠ «затухание экранирования»).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

# Стоп-слова и шум в названиях ПМИ/прайса
_STOP = frozenset(
    {
        "к",
        "и",
        "на",
        "в",
        "по",
        "при",
        "с",
        "от",
        "до",
        "для",
        "или",
        "из",
        "ок",
        "ов",
        "кабеля",
        "кабелей",
        "образцов",
        "образца",
        "воздействию",
        "воздействие",
        "испытание",
        "испытания",
        "проверка",
        "проверки",
        "определение",
        "измерение",
        "прочность",
        "стойкость",
        "угол",
        "время",
        "условиях",
        "условия",
        "окружающей",
        "среды",
        "воздуха",
        "температуре",
        "температур",
        "температуры",
    }
)

# (regex, code, note) — более специфичные выше
_PHRASE_RULES: tuple[tuple[str, str, str], ...] = (
    (
        r"коэффициент\w*\s+затухан|затухан\w*.*\bок\b|затухания\s+опт|"
        r"затухания\s+оптическ|оптическ\w*\s+волокн.*затух|"
        r"затухания\s+оптического",
        "измерение_затухания_оптического_волокнаодного",
        "оптическое затухание / коэффициент",
    ),
    (
        r"затухан\w*\s+экранирован|экранирован\w*\s+затух",
        "измерение_затухания_экранирования",
        "затухание экранирования",
    ),
    (
        r"затухан\w*\s+излучен",
        "измерение_затухания_излучения",
        "затухание излучения",
    ),
    (
        r"осево\w*\s+кручен|кручен\w*.*осев",
        "стойкость_к_осевому_кручению_100_циклов",
        "осевое кручение",
    ),
    (
        r"многократн\w*\s+изгиб|изгиб\w*\s+на\s+угол|простому\s+изгиб",
        "стойкость_к_простому_изгибу_100_циклов",
        "многократный / простой изгиб",
    ),
    (
        r"перегиб",
        "стойкость_к_перегибам_30000_циклов",
        "перегибы",
    ),
    (
        r"односторонн\w*\s+изгиб",
        "стойкость_к_односторонним_изгибам_2000",
        "односторонние изгибы",
    ),
    (
        r"одиночн\w*\s+удар|удар\w*\s+при\s+отрицательн",
        "стойкость_к_удару_при_отрицательной_температуре",
        "удар",
    ),
    (
        r"изгиб\w*\s+при\s+отрицательн",
        "стойкость_к_изгибу_при_отрицательной_температуре",
        "изгиб при −t°",
    ),
    (
        r"огнестойк\w*.*(?:опт|ов\b|волокн)|(?:опт|волокн).{0,40}огнестойк",
        "огнестойкость_оптического_кабеля",
        "огнестойкость оптического",
    ),
    (
        r"огнестойк|сохранени\w*\s+работоспособност\w*.*пламен",
        "огнестойкость",
        "огнестойкость",
    ),
    (
        r"повышенн\w*\s+влажност|влажност\w*\s+воздух",
        "стойкость_к_повышенной_влажности_воздуха",
        "влажность",
    ),
    (
        r"циклическ\w*\s+смен\w*\s+температур|изменен\w*\s+температур|"
        r"резк\w*.*температур",
        "стойкость_к_изменению_температуррезкоеплавное",
        "цикл / смена температур",
    ),
    (
        r"пониженн\w*\s+температур",
        "стойкость_к_пониженной_температуре",
        "пониженная t°",
    ),
    (
        r"повышенн\w*\s+температур",
        "стойкость_к_повышенной_температуре",
        "повышенная t°",
    ),
    (
        r"солнечн\w*\s+(?:радиац|излучен)|ультрафиолет",
        "стойкость_к_солнечной_радиации",
        "солнечная радиация",
    ),
    (
        r"электрическ\w*\s+сопротивлен\w*\s+изоляц|сопротивлен\w*\s+изоляц",
        "электрическое_сопротивление_изоляции_тпж",
        "R изоляции",
    ),
    (
        r"электрическ\w*\s+сопротивлен\w*\s+(?:тпж|жил)|сопротивлен\w*\s+(?:тпж|жил)",
        "электрическое_сопротивление_тпж",
        "R жилы",
    ),
    (
        r"испытани\w*\s+напряжен|напряжени\w*\s+(?:переменн|постоянн|перем)",
        "испытание_напряжением",
        "U-испытание",
    ),
    (
        r"конструкц\w*\s+размер|конструктивн\w*\s+размер|диаметр\w*\s+тпж|"
        r"толщин\w*\s+изоляц|толщин\w*\s+оболоч",
        "измерение_диаметрасечения_тпж",
        "конструкция / размеры (эвристика → диаметр ТПЖ)",
    ),
    (
        r"емкост|индуктивн",
        "измерение_емкостииндуктивности",
        "C/L",
    ),
    (
        r"герметичн",
        "испытание_на_частичную_герметичность_воздух",
        "герметичность",
    ),
    (
        r"водопоглощ|водопоглащ",
        "водопоглащение",
        "водопоглощение",
    ),
)

# Seed-aliases: (alias, canonical, code)
PROGRAM_ALIAS_SEED: tuple[tuple[str, str, str], ...] = (
    ("коэффициент затухания", "Затухание ОВ", "измерение_затухания_оптического_волокнаодного"),
    ("затухания ок", "Затухание ОВ", "измерение_затухания_оптического_волокнаодного"),
    ("осевого кручения", "Осевое кручение", "стойкость_к_осевому_кручению_100_циклов"),
    ("многократным изгибам", "Простой изгиб", "стойкость_к_простому_изгибу_100_циклов"),
    ("одиночного удара", "Удар", "стойкость_к_удару_при_отрицательной_температуре"),
    ("огнестойкость оптического", "Огнестойкость ОК", "огнестойкость_оптического_кабеля"),
    ("сопротивление жил", "Электрическое сопротивление ТПЖ", "электрическое_сопротивление_тпж"),
    ("r жилы", "Электрическое сопротивление ТПЖ", "электрическое_сопротивление_тпж"),
    ("испытание u", "Испытание напряжением", "испытание_напряжением"),
    ("циклической смене температур", "Смена температур", "стойкость_к_изменению_температуррезкоеплавное"),
    ("повышенной влажности", "Влажность", "стойкость_к_повышенной_влажности_воздуха"),
)


@dataclass(frozen=True)
class MatchHit:
    code: str
    method: str
    note: str | None = None
    score: float = 1.0


def normalize_test_phrase(text: str) -> str:
    t = (text or "").replace("\xa0", " ").lower()
    t = t.replace("ё", "е")
    t = re.sub(r"[±+\-–—]", " ", t)
    t = re.sub(r"[^\wа-яa-z0-9\s/%°]", " ", t, flags=re.IGNORECASE)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def token_set(text: str) -> set[str]:
    return {
        tok
        for tok in normalize_test_phrase(text).split()
        if len(tok) > 2 and tok not in _STOP
    }


def token_jaccard(a: str, b: str) -> float:
    ta, tb = token_set(a), token_set(b)
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    if inter == 0:
        return 0.0
    return inter / len(ta | tb)


def _phrase_rule_hit(name: str) -> MatchHit | None:
    """Только по названию пункта — контекст программы сюда не подмешиваем
    (иначе «кабели … огнестойкие» в шапке ловит все 14 строк)."""
    name_n = normalize_test_phrase(name)
    if not name_n:
        return None
    for pattern, code, note in _PHRASE_RULES:
        if re.search(pattern, name_n, re.IGNORECASE):
            return MatchHit(code=code, method="phrase_rule", note=note, score=0.95)
    return None


def _prefer_optical_fire(hit: MatchHit, context: str, name: str) -> MatchHit:
    """Для оптических программ «огнестойкость» → code оптического кабеля."""
    if hit.code != "огнестойкость":
        return hit
    name_n = normalize_test_phrase(name)
    ctx = normalize_test_phrase(context)
    # В названии пункта уже есть «оптич…» — правило выше; иначе смотрим шапку ПМИ
    if re.search(r"оптическ|волокн", name_n):
        code = "огнестойкость_оптического_кабеля"
    elif re.search(r"оптическ|волокн", ctx) and re.search(r"огнестойк", name_n):
        code = "огнестойкость_оптического_кабеля"
    else:
        return hit
    return MatchHit(
        code=code,
        method="phrase_rule+context",
        note="огнестойкость ОК (контекст программы)",
        score=0.93,
    )


def _fuzzy_price_name(
    name: str,
    price_names: dict[str, str],
    *,
    min_score: float = 0.42,
    min_shared: int = 2,
) -> MatchHit | None:
    best: MatchHit | None = None
    nl = normalize_test_phrase(name)
    ntoks = token_set(name)
    if len(ntoks) < 1:
        return None
    for pname, pcode in price_names.items():
        # substring (уже покрыто снаружи, но для fuzzy — jaccard)
        score = token_jaccard(name, pname)
        shared = len(ntoks & token_set(pname))
        if score < min_score:
            continue
        if shared < min_shared and score < 0.55:
            continue
        # короткие «общие» слова не должны выигрывать
        if best is None or score > best.score:
            best = MatchHit(
                code=pcode,
                method="token_fuzzy",
                note=f"≈ {pname[:60]}",
                score=score,
            )
    return best


def resolve_program_item_price_code(
    name: str,
    *,
    price_items: Sequence[dict[str, Any]] | None = None,
    db_path: str | Path | None = None,
    program_context: str = "",
) -> MatchHit | None:
    """Подбирает price_test_code для одной позиции программы."""
    from ..persistence.sqlite_repo import list_test_items, resolve_test_alias
    from .requirement_mapper import map_requirements_to_tests, resolve_test_code

    name = (name or "").strip()
    if not name:
        return None

    if price_items is None and db_path is not None:
        price_items = list_test_items(limit=500, db_path=db_path)
    price_items = list(price_items or [])
    price_names = {
        (r.get("name") or "").strip().lower(): r["code"]
        for r in price_items
        if r.get("code")
    }
    known_codes = {r["code"] for r in price_items if r.get("code")}

    def _ok(code: str | None) -> str | None:
        if not code:
            return None
        resolved = resolve_test_code(code, db_path) if db_path else code
        if known_codes and resolved not in known_codes and code not in known_codes:
            # accept if resolve found something in DB even if list stale
            if db_path is not None:
                from ..persistence.sqlite_repo import get_test_item_by_code

                if get_test_item_by_code(resolved, db_path):
                    return resolved
            return None
        return resolved

    # 1) phrase rules по имени пункта (+ optical disambiguation из контекста)
    hit = _phrase_rule_hit(name)
    if hit:
        hit = _prefer_optical_fire(hit, program_context, name)
        code = _ok(hit.code)
        if code:
            return MatchHit(code=code, method=hit.method, note=hit.note, score=hit.score)

    # 2) aliases
    if db_path is not None:
        alias_hit = resolve_test_alias(name, db_path=db_path)
        if alias_hit and alias_hit.get("price_test_code"):
            code = _ok(str(alias_hit["price_test_code"]))
            if code:
                return MatchHit(
                    code=code,
                    method="alias",
                    note=str(alias_hit.get("alias_norm") or "")[:80],
                    score=0.91,
                )

    # 3) exact / substring name
    nl = name.lower().strip()
    if nl in price_names:
        code = _ok(price_names[nl])
        if code:
            return MatchHit(code=code, method="exact_name", score=1.0)
    for pname, pcode in price_names.items():
        if nl and len(nl) >= 8 and (nl in pname or pname in nl):
            code = _ok(pcode)
            if code:
                return MatchHit(
                    code=code,
                    method="substring_name",
                    note=pname[:60],
                    score=0.88,
                )

    # 4) token fuzzy
    fuzzy = _fuzzy_price_name(name, price_names)
    if fuzzy:
        code = _ok(fuzzy.code)
        if code:
            return MatchHit(
                code=code, method=fuzzy.method, note=fuzzy.note, score=fuzzy.score
            )

    # 5) requirement mapper fallback (осторожно: «затухан» → экран)
    # Для оптического контекста не берём shielding attenuation
    suggestions = map_requirements_to_tests(name, db_path=db_path)
    ctx = normalize_test_phrase(f"{name} {program_context}")
    for sug in suggestions:
        code = _ok(sug.code)
        if not code:
            continue
        if code == "измерение_затухания_экранирования" and re.search(
            r"коэффициент|оптическ|волокн|\bок\b", ctx
        ):
            opt = _ok("измерение_затухания_оптического_волокнаодного")
            if opt:
                return MatchHit(
                    code=opt,
                    method="mapper+optical_fix",
                    note="исправлено: не экранирование",
                    score=0.9,
                )
            continue
        return MatchHit(
            code=code,
            method="mapper",
            note=sug.matched_pattern,
            score=float(sug.confidence or 0.75),
        )
    return None


def match_rate_summary(matched: int, total: int) -> str:
    if total <= 0:
        return "сопоставлено 0/0"
    pct = 100.0 * matched / total
    return f"сопоставлено {matched}/{total} ({pct:.0f}%)"
