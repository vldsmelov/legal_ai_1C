from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

import yaml

from .config import settings
from .types import FocusItem, SectionScore

_CONFIG_FALLBACK_WHY = "Низкая оценка раздела может привести к юридическим рискам."


class _AnalyzeConfigCache:
    """Lazy loader for analyze section configuration with mtime-based invalidation."""

    def __init__(self) -> None:
        self._config_path = Path(__file__).resolve().parent / "config" / "analyze_sections.yaml"
        self._cache: Dict[str, Any] | None = None
        self._mtime: float | None = None

    def _load_from_disk(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {}
        try:
            with open(self._config_path, "r", encoding="utf-8") as fp:
                raw = yaml.safe_load(fp) or {}
                if isinstance(raw, dict):
                    data = raw
        except FileNotFoundError:
            data = {}
        except yaml.YAMLError:
            # Invalid YAML should not break analysis. Preserve previous cache if available.
            if self._cache is not None:
                return self._cache
            data = {}

        defaults = data.get("defaults") or {}
        sections: List[Dict[str, Any]] = []
        for item in data.get("sections") or []:
            if not isinstance(item, dict):
                continue
            key = item.get("key")
            title = item.get("title")
            weight = item.get("weight")
            if not key or not title:
                continue
            try:
                weight_value = int(weight)
            except (TypeError, ValueError):
                continue

            record: Dict[str, Any] = {
                "key": str(key),
                "title": str(title),
                "weight": weight_value,
            }
            if item.get("why"):
                record["why"] = str(item["why"])
            if item.get("suggestion"):
                record["suggestion"] = str(item["suggestion"])
            sections.append(record)

        section_defs = [
            {"key": s["key"], "title": s["title"], "weight": s["weight"]}
            for s in sections
        ]
        section_index = {s["key"]: s for s in section_defs}
        why_map = {s["key"]: s.get("why") for s in sections if s.get("why")}
        suggest_map = {
            s["key"]: s.get("suggestion") for s in sections if s.get("suggestion")
        }

        return {
            "sections": sections,
            "section_defs": section_defs,
            "section_index": section_index,
            "section_keys": set(section_index.keys()),
            "why_map": why_map,
            "suggest_map": suggest_map,
            "default_why": defaults.get("why") or _CONFIG_FALLBACK_WHY,
            "default_suggestion": defaults.get("suggestion"),
            "sections_lines": "\n".join(
                [f'- "{s["key"]}" — {s["title"]}' for s in section_defs]
            ),
        }

    def get(self) -> Dict[str, Any]:
        try:
            mtime = self._config_path.stat().st_mtime
        except FileNotFoundError:
            mtime = None

        if self._cache is not None and self._mtime == mtime:
            return self._cache

        config = self._load_from_disk()
        self._cache = config
        self._mtime = mtime
        return config


_ANALYZE_CONFIG = _AnalyzeConfigCache()


def _config() -> Dict[str, Any]:
    return _ANALYZE_CONFIG.get()


def get_section_defs() -> List[Dict[str, Any]]:
    return _config()["section_defs"]


def get_section_index() -> Dict[str, Dict[str, Any]]:
    return _config()["section_index"]


def get_section_keys() -> set[str]:
    return _config()["section_keys"]


def get_why_map() -> Dict[str, str]:
    return _config()["why_map"]


def get_suggest_map() -> Dict[str, str]:
    return _config()["suggest_map"]


def get_default_why() -> str:
    return _config()["default_why"]


def get_default_suggestion() -> str | None:
    return _config()["default_suggestion"]


def sections_lines() -> str:
    return _config()["sections_lines"]


def compute_total_and_color(
    section_scores: List[SectionScore],
) -> Tuple[int, str, List[Dict[str, Any]]]:
    cfg = _config()
    section_index = cfg["section_index"]
    items: List[Dict[str, Any]] = []
    total = 0.0
    for s in section_scores:
        meta = section_index.get(s.key)
        if not meta:
            continue
        weight = meta["weight"]
        weighted = (max(0, min(5, s.raw)) / 5.0) * weight
        total += weighted
        items.append(
            {
                "key": s.key,
                "title": meta["title"],
                "weight": weight,
                "raw": s.raw,
                "score": round(weighted, 2),
                "of": weight,
                "comment": s.comment or "",
            }
        )
    score_total = int(round(total))
    if score_total >= settings.SCORE_GREEN:
        color = "green"
    elif score_total >= settings.SCORE_YELLOW:
        color = "yellow"
    else:
        color = "red"
    return score_total, color, items


def build_focus(
    section_table: List[Dict[str, Any]],
    issues: List[Dict[str, Any]],
) -> Tuple[str, List[FocusItem]]:
    cfg = _config()
    why_map = cfg["why_map"]
    default_why = cfg["default_why"]
    suggest_map = cfg["suggest_map"]
    default_suggestion = cfg["default_suggestion"]

    sorted_sections = sorted(section_table, key=lambda x: (x["raw"], -x["weight"]))
    top: List[FocusItem] = []
    for row in sorted_sections[:3]:
        key = row["key"]
        why = why_map.get(key, default_why)
        sugg = next(
            (
                it.get("suggestion")
                for it in issues
                if it.get("section") == key and it.get("suggestion")
            ),
            None,
        )
        top.append(
            FocusItem(
                key=key,
                title=row["title"],
                raw=row["raw"],
                score=row["score"],
                why=why,
                suggestion=sugg or suggest_map.get(key) or default_suggestion,
            )
        )
    if not top:
        return "Серьёзных проблем не выявлено.", []
    focus_summary = (
        "Обратить внимание: "
        + "; ".join([f"{t.title.lower()} — {t.why}" for t in top])
        + "."
    )
    return focus_summary, top

