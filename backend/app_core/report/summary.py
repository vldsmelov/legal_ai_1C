from __future__ import annotations

from typing import Any, Dict, List

from ..scoring import SECTION_INDEX, SUGGEST_MAP


_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}
_DEFAULT_OVERVIEW_SUMMARY = (
    "Автоматическое резюме по документу; проверьте корректность выводов вручную."
)
_DEFAULT_ANALYSIS_POINT = "Детализированный анализ по разделам не сформирован."
_DEFAULT_RECOMMENDATION = "Рекомендации не определены — требуется экспертная проверка."


def build_document_overview(payload: Dict[str, Any]) -> Dict[str, Any]:
    payload = payload or {}
    summary = (payload.get("document_summary") or payload.get("summary") or "").strip()
    parties = (payload.get("parties") or "").strip() or None
    subject = (payload.get("subject") or "").strip() or None
    highlights_raw = payload.get("highlights") or []
    highlights: List[str] = []
    if isinstance(highlights_raw, list):
        for item in highlights_raw:
            text = str(item).strip()
            if text:
                highlights.append(text)
    if not summary:
        summary = _DEFAULT_OVERVIEW_SUMMARY
    return {
        "summary": summary,
        "parties": parties,
        "subject": subject,
        "highlights": highlights,
    }


def _format_section_row(row: Dict[str, Any]) -> str:
    title = row.get("title") or SECTION_INDEX.get(row.get("key"), {}).get("title")
    title_text = title or row.get("key") or "Раздел"
    raw = row.get("raw")
    comment = (row.get("comment") or "").strip()
    if comment:
        comment_text = comment
    else:
        comment_text = "Комментарий не предоставлен." if raw is not None else ""
    if raw is None:
        return f"{title_text}: {comment_text}".strip()
    return f"{title_text}: оценка {raw}/5. {comment_text}".strip()


def summarize_report_block(report: Dict[str, Any], block_title: str) -> Dict[str, Any]:
    report = report or {}
    score_text = report.get("score_text") or ""
    risk_color = report.get("risk_color") or ""
    top_focus = report.get("top_focus") or []
    issues = report.get("issues") or []
    section_scores = report.get("section_scores") or []

    summary_parts: List[str] = []
    if score_text:
        summary_parts.append(f"Итоговая оценка блока — {score_text}.")
    if risk_color:
        risk_map = {"green": "низкий уровень риска", "yellow": "повышенный риск", "red": "высокий риск"}
        label = risk_map.get(risk_color.lower())
        if label:
            summary_parts.append(label.capitalize() + ".")
    focus_lines: List[str] = []
    for focus in top_focus[:3]:
        title = focus.get("title") or SECTION_INDEX.get(focus.get("key"), {}).get("title")
        why = focus.get("why") or ""
        if title:
            line = f"{title}: {why}".strip().rstrip(".")
            focus_lines.append(line)
    if focus_lines:
        summary_parts.append(
            "Ключевые зоны внимания — " + "; ".join(focus_lines) + "."
        )
    if not summary_parts:
        summary_parts.append(
            f"Сводка по блоку «{block_title}» недоступна; требуется проверка специалиста."
        )

    analysis_points: List[str] = []
    for row in sorted(section_scores, key=lambda x: (x.get("raw", 6), -float(x.get("weight", 0)))):
        formatted = _format_section_row(row)
        if formatted:
            analysis_points.append(formatted)
    if not analysis_points:
        analysis_points.append(_DEFAULT_ANALYSIS_POINT)

    recommendations: List[str] = []
    for issue in sorted(issues, key=lambda i: _SEVERITY_ORDER.get(str(i.get("severity")).lower(), 3)):
        section_key = issue.get("section")
        title = SECTION_INDEX.get(section_key, {}).get("title") or section_key or "Блок"
        suggestion = (issue.get("suggestion") or "").strip() or SUGGEST_MAP.get(section_key)
        if suggestion:
            recommendations.append(f"{title}: {suggestion}")
        else:
            text = (issue.get("text") or "").strip()
            if text:
                recommendations.append(f"{title}: {text}")
    if not recommendations:
        recommendations.append(_DEFAULT_RECOMMENDATION)

    return {
        "summary": " ".join(summary_parts).strip(),
        "analysis_points": analysis_points,
        "recommendations": recommendations,
    }
