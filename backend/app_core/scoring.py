from pathlib import Path
from typing import List, Tuple, Dict, Any

import yaml

from .types import SectionScore, FocusItem
from .config import settings


def _load_analyze_sections() -> Dict[str, Any]:
    config_path = Path(__file__).resolve().parent / "config" / "analyze_sections.yaml"
    with open(config_path, "r", encoding="utf-8") as fp:
        data = yaml.safe_load(fp) or {}
    sections = data.get("sections", [])
    defaults = data.get("defaults", {})
    return {
        "sections": sections,
        "default_why": defaults.get(
            "why", "Низкая оценка раздела может привести к юридическим рискам."
        ),
        "default_suggestion": defaults.get("suggestion"),
    }


ANALYZE_SECTIONS = _load_analyze_sections()

SECTION_DEFS = [
    {"key": s["key"], "title": s["title"], "weight": s["weight"]}
    for s in ANALYZE_SECTIONS["sections"]
]
SECTION_INDEX = {s["key"]: s for s in SECTION_DEFS}
SECTION_KEYS = set(SECTION_INDEX.keys())

WHY_MAP = {
    section["key"]: section.get("why")
    for section in ANALYZE_SECTIONS["sections"]
    if section.get("why")
}
SUGGEST_MAP = {
    section["key"]: section.get("suggestion")
    for section in ANALYZE_SECTIONS["sections"]
    if section.get("suggestion")
}
DEFAULT_WHY = ANALYZE_SECTIONS["default_why"]
DEFAULT_SUGGESTION = ANALYZE_SECTIONS["default_suggestion"]

def sections_lines() -> str:
    return "\n".join([f'- "{s["key"]}" — {s["title"]}' for s in SECTION_DEFS])

def compute_total_and_color(section_scores: List[SectionScore]) -> Tuple[int, str, List[Dict[str, Any]]]:
    items, total = [], 0.0
    for s in section_scores:
        meta = SECTION_INDEX.get(s.key)
        if not meta:
            continue
        weight = meta["weight"]
        weighted = (max(0, min(5, s.raw)) / 5.0) * weight
        total += weighted
        items.append({
            "key": s.key, "title": meta["title"], "weight": weight,
            "raw": s.raw, "score": round(weighted, 2), "of": weight,
            "comment": s.comment or ""
        })
    score_total = int(round(total))
    if score_total >= settings.SCORE_GREEN:
        color = "green"
    elif score_total >= settings.SCORE_YELLOW:
        color = "yellow"
    else:
        color = "red"
    return score_total, color, items

def build_focus(section_table: List[Dict[str, Any]], issues: List[Dict[str, Any]]) -> Tuple[str, List[FocusItem]]:
    sorted_sections = sorted(section_table, key=lambda x: (x["raw"], -x["weight"]))
    top: List[FocusItem] = []
    for row in sorted_sections[:3]:
        key = row["key"]
        why = WHY_MAP.get(key, DEFAULT_WHY)
        sugg = next((it.get("suggestion") for it in issues if it.get("section") == key and it.get("suggestion")), None)
        top.append(FocusItem(
            key=key, title=row["title"], raw=row["raw"], score=row["score"],
            why=why, suggestion=sugg or SUGGEST_MAP.get(key) or DEFAULT_SUGGESTION
        ))
    if not top:
        return "Серьёзных проблем не выявлено.", []
    focus_summary = "Обратить внимание: " + "; ".join([f"{t.title.lower()} — {t.why}" for t in top]) + "."
    return focus_summary, top
