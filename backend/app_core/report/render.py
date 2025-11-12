# backend/app_core/report/render.py
from __future__ import annotations
from typing import Dict, Any, List
from datetime import datetime
import re
import html

from ..paths import REPORT_OUTPUT_DIR

def _risk_badge(color: str) -> str:
    color = (color or "").lower()
    bg = {"green": "#16a34a", "yellow": "#ca8a04", "red": "#dc2626"}.get(color, "#64748b")
    return f'style="display:inline-block;padding:4px 10px;border-radius:999px;background:{bg};color:#fff;font-weight:600;font-size:12px"'


def _escape(s: Any) -> str:
    return html.escape(str(s) if s is not None else "")


def _section_rows(section_scores: List[Dict[str, Any]]) -> str:
    rows = []
    for s in section_scores or []:
        pct = 0
        try:
            pct = int(round(100 * float(s.get("score", 0)) / float(s.get("of", 1))))
        except Exception:
            pct = 0
        bar = f"""
          <div style=\"background:#e5e7eb;height:8px;border-radius:6px;overflow:hidden\">
            <div style=\"width:{pct}%;height:8px;background:#3b82f6\"></div>
          </div>"""
        rows.append(
            f"""
          <tr>
            <td style=\"padding:8px 12px;border-bottom:1px solid #eee\">{_escape(s.get('title'))}</td>
            <td style=\"padding:8px 12px;border-bottom:1px solid #eee;white-space:nowrap\">{_escape(s.get('score'))} / {_escape(s.get('of'))}</td>
            <td style=\"padding:8px 12px;border-bottom:1px solid #eee\">{bar}</td>
            <td style=\"padding:8px 12px;border-bottom:1px solid #eee;color:#6b7280\">{_escape(s.get('comment') or '')}</td>
          </tr>"""
        )
    return "\n".join(rows)


def _issues_list(issues: List[Dict[str, Any]]) -> str:
    if not issues:
        return '<p style="color:#6b7280">Явных критичных замечаний не выявлено.</p>'
    items = []
    for it in issues:
        items.append(
            f"""
          <li style=\"margin-bottom:8px\">
            <b>{_escape(it.get('section'))}</b>: {_escape(it.get('text'))}
            <div style=\"color:#6b7280\"><i>Рекомендация:</i> {_escape(it.get('suggestion') or '')}</div>
          </li>"""
        )
    return "<ul>" + "\n".join(items) + "</ul>"


def _sources_list(sources: List[Dict[str, Any]]) -> str:
    if not sources:
        return '<p style="color:#6b7280">Источники не найдены.</p>'
    li = []
    for s in sources:
        where = "ст." + _escape(s.get("article")) if s.get("article") else ""
        if s.get("point"):
            where += f", п.{_escape(s.get('point'))}"
        ref = _escape(s.get("local_ref") or "")
        li.append(f"<li><b>{_escape(s.get('act_title'))}</b> {where} <span style='color:#6b7280'>({ref})</span></li>")
    return "<ol>" + "\n".join(li) + "</ol>"


def _score_chip(title: str, color: str, score_text: str) -> str:
    badge = f"<span {_risk_badge(color)}>{_escape(color or 'n/a')}</span>"
    return f"""
      <div style=\"flex:1;min-width:240px\">
        <div style=\"font-size:13px;color:#6b7280;margin-bottom:4px\">{_escape(title)}</div>
        <div style=\"display:flex;align-items:center;gap:12px\">
          {badge}
          <span style=\"font-size:20px;font-weight:600\">{_escape(score_text or '—')}</span>
        </div>
      </div>"""


def _normalize_items(items: List[Any]) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    for it in items or []:
        if hasattr(it, "dict"):
            try:
                result.append(it.dict())  # type: ignore[attr-defined]
                continue
            except Exception:
                pass
        if isinstance(it, dict):
            result.append(it)
    return result


def _normalize_dict(item: Any) -> Dict[str, Any]:
    if hasattr(item, "dict"):
        try:
            return item.dict()  # type: ignore[attr-defined]
        except Exception:
            pass
    if isinstance(item, dict):
        return item
    return {}


def _bullet_list(items: List[Any], empty_text: str) -> str:
    values: List[str] = []
    for raw in items or []:
        text = str(raw).strip()
        if text:
            values.append(text)
    if not values:
        return f'<p style="color:#6b7280">{_escape(empty_text)}</p>'
    lis = [f"<li>{_escape(text)}</li>" for text in values]
    return "<ul>" + "\n".join(lis) + "</ul>"


def _focus_list(top_focus: List[Dict[str, Any]]) -> str:
    items = []
    for f in _normalize_items(top_focus)[:5]:
        title = f.get("title") or f.get("key")
        why = f.get("why") or ""
        suggestion = f.get("suggestion") or ""
        extra = f" <i style='color:#6b7280'>({_escape(suggestion)})</i>" if suggestion else ""
        items.append(
            f"<li><b>{_escape(title)}</b> — {_escape(why)}{extra}</li>"
        )
    if not items:
        return '<p style="color:#6b7280">—</p>'
    return "<ul>" + "\n".join(items) + "</ul>"


def render_html(meta: Dict[str, Any], analysis: Dict[str, Any]) -> str:
    analysis = analysis or {}
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _block(prefix: str = "") -> Dict[str, Any]:
        suffix = f"{prefix}_" if prefix else ""
        return {
            "score_text": analysis.get(f"{suffix}score_text") or "",
            "risk_color": analysis.get(f"{suffix}risk_color") or "",
            "summary": analysis.get(f"{suffix}summary") or "",
            "focus_summary": analysis.get(f"{suffix}focus_summary") or "",
            "top_focus": analysis.get(f"{suffix}top_focus") or [],
            "section_scores": analysis.get(f"{suffix}section_scores") or [],
            "issues": analysis.get(f"{suffix}issues") or [],
        }

    law_block = _block("")
    business_block = _block("business")
    sources = analysis.get("sources") or []

    overview_data = _normalize_dict(analysis.get("overview") or {})
    law_narrative = _normalize_dict(analysis.get("law_narrative") or {})
    business_narrative = _normalize_dict(analysis.get("business_narrative") or {})

    overview_summary = overview_data.get("summary") or analysis.get("overview_summary") or ""
    overview_parties = overview_data.get("parties") or analysis.get("overview_parties") or ""
    overview_subject = overview_data.get("subject") or analysis.get("overview_subject") or ""
    overview_highlights_raw = overview_data.get("highlights") or analysis.get("overview_highlights") or []

    compact_preview = meta.get("compact_preview") or ""
    compact_block = (
        f"""
      <details>
        <summary style=\"cursor:pointer\"><b>Показать компактный текст для анализа</b></summary>
        <pre style=\"white-space:pre-wrap;background:#f8fafc;border:1px solid #e5e7eb;border-radius:8px;padding:12px;margin-top:8px;max-height:420px;overflow:auto\">{_escape(compact_preview)}</pre>
      </details>"""
        if compact_preview
        else ""
    )

    src_info = ""
    if meta.get("source_path"):
        src_info = f"<div><b>Файл:</b> {_escape(meta['source_path'])}</div>"
    elif meta.get("source_url"):
        src_info = f"<div><b>URL:</b> {_escape(meta['source_url'])}</div>"

    overview_details: List[str] = []
    if overview_parties:
        overview_details.append(f"<div><b>Стороны:</b> {_escape(overview_parties)}</div>")
    if overview_subject:
        overview_details.append(f"<div><b>Предмет:</b> {_escape(overview_subject)}</div>")
    overview_details_html = "\n".join(overview_details) if overview_details else '<p style="color:#6b7280">Дополнительные сведения не выявлены.</p>'

    law_summary_text = law_narrative.get("summary") or law_block.get("summary") or ""
    law_analysis_points = law_narrative.get("analysis_points") or []
    law_recommendations = law_narrative.get("recommendations") or []

    business_summary_text = business_narrative.get("summary") or business_block.get("summary") or ""
    business_analysis_points = business_narrative.get("analysis_points") or []
    business_recommendations = business_narrative.get("recommendations") or []

    law_present = any([
        law_block["score_text"],
        law_summary_text,
        law_block["section_scores"],
        law_block["issues"],
    ])
    business_present = any([
        business_block["score_text"],
        business_summary_text,
        business_block["section_scores"],
        business_block["issues"],
    ])

    title_score = law_block["score_text"] or business_block["score_text"]

    law_block_html = ""
    if law_present:
        law_block_html = f"""
  <div class=\"card\">
    <h2>Соответствие законодательству</h2>
    <div style=\"display:flex;flex-wrap:wrap;gap:16px;margin-bottom:12px\">
      {_score_chip('Соответствие законодательству', law_block['risk_color'], law_block['score_text'])}
    </div>
    <p>{_escape(law_summary_text)}</p>
    <p style=\"color:#374151\">{_escape(law_block.get('focus_summary') or '')}</p>
    <h3>Ключевые зоны внимания</h3>
    {_focus_list(law_block.get('top_focus') or [])}
    <h3>Анализ по пунктам</h3>
    {_bullet_list(law_analysis_points, 'Анализ по пунктам не сформирован.')}
    <h3>Рекомендации</h3>
    {_bullet_list(law_recommendations, 'Рекомендации не сформированы.')}
    <h3>Детализация по разделам</h3>
    <table style=\"width:100%;border-collapse:collapse\">
      <thead>
        <tr>
          <th style=\"text-align:left;padding:8px 12px;border-bottom:1px solid #ddd\">Раздел</th>
          <th style=\"text-align:left;padding:8px 12px;border-bottom:1px solid #ddd\">Баллы</th>
          <th style=\"text-align:left;padding:8px 12px;border-bottom:1px solid #ddd;width:240px\">Уровень</th>
          <th style=\"text-align:left;padding:8px 12px;border-bottom:1px solid #ddd\">Комментарий</th>
        </tr>
      </thead>
      <tbody>
        {_section_rows(law_block.get('section_scores') or [])}
      </tbody>
    </table>
    <h3>Замечания и детали</h3>
    {_issues_list(law_block.get('issues') or [])}
    <h3>Источники</h3>
    {_sources_list(sources)}
  </div>"""

    business_block_html = ""
    if business_present:
        business_block_html = f"""
  <div class=\"card\">
    <h2>Бизнес-риски и логика сделки</h2>
    <div style=\"display:flex;flex-wrap:wrap;gap:16px;margin-bottom:12px\">
      {_score_chip('Бизнес-риски и логика сделки', business_block['risk_color'], business_block['score_text'])}
    </div>
    <p>{_escape(business_summary_text)}</p>
    <p style=\"color:#374151\">{_escape(business_block.get('focus_summary') or '')}</p>
    <h3>Ключевые зоны внимания</h3>
    {_focus_list(business_block.get('top_focus') or [])}
    <h3>Анализ по пунктам</h3>
    {_bullet_list(business_analysis_points, 'Анализ по пунктам не сформирован.')}
    <h3>Рекомендации</h3>
    {_bullet_list(business_recommendations, 'Рекомендации не сформированы.')}
    <h3>Детализация по разделам</h3>
    <table style=\"width:100%;border-collapse:collapse\">
      <thead>
        <tr>
          <th style=\"text-align:left;padding:8px 12px;border-bottom:1px solid #ddd\">Раздел</th>
          <th style=\"text-align:left;padding:8px 12px;border-bottom:1px solid #ddd\">Баллы</th>
          <th style=\"text-align:left;padding:8px 12px;border-bottom:1px solid #ddd;width:240px\">Уровень</th>
          <th style=\"text-align:left;padding:8px 12px;border-bottom:1px solid #ddd\">Комментарий</th>
        </tr>
      </thead>
      <tbody>
        {_section_rows(business_block.get('section_scores') or [])}
      </tbody>
    </table>
    <h3>Замечания и детали</h3>
    {_issues_list(business_block.get('issues') or [])}
  </div>"""

    html_doc = f"""<!DOCTYPE html>
<html lang=\"ru\"><head>
<meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
<title>Отчёт по договору — { _escape(title_score) }</title>
<style>
  body {{ font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial, \"Noto Sans\", \"Liberation Sans\", \"Helvetica Neue\", sans-serif; color:#111827; }}
  .card {{ background:#fff; border:1px solid #e5e7eb; border-radius:12px; padding:18px; margin:12px 0; }}
  h1 {{ font-size:20px; margin:6px 0 0 0; }}
  h2 {{ font-size:18px; margin:0 0 8px 0; }}
  h3 {{ font-size:16px; margin:12px 0 6px 0; }}
  small {{ color:#6b7280; }}
</style>
</head><body style=\"max-width:980px;margin:24px auto;padding:0 16px;background:#f3f4f6\">
  <div class=\"card\">
    <h1>Общая информация о документе</h1>
    <div style=\"margin-bottom:12px;color:#6b7280\"><small>Сформировано: {now}</small></div>
    <p>{_escape(overview_summary or 'Описание документа не сформировано.')}</p>
    {overview_details_html}
    <h3>Ключевые факты</h3>
    {_bullet_list(overview_highlights_raw, 'Ключевые факты не выделены.')}
    {compact_block}
  </div>

  {law_block_html}

  {business_block_html}

  <div class=\"card\" style=\"color:#374151\">
    <h2>Метаданные</h2>
    {src_info}
    <div><b>Оригинальный размер:</b> { _escape(meta.get('original_bytes')) } байт</div>
    <div><b>Аналитический фрагмент:</b> { _escape(meta.get('compact_bytes')) } байт</div>
  </div>
</body></html>"""
    return html_doc


def save_report_html(html_str: str, name: str | None = None) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_.-]+", "_", name or "report")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    outdir = REPORT_OUTPUT_DIR
    outdir.mkdir(parents=True, exist_ok=True)
    path = outdir / f"{ts}_{safe}.html"
    path.write_text(html_str, encoding="utf-8")
    return str(path)
