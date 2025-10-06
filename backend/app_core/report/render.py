# backend/app_core/report/render.py
from __future__ import annotations
from typing import Dict, Any, List
from datetime import datetime
from pathlib import Path
import re
import html


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


def _analysis_cards(
    title: str,
    data: Dict[str, Any],
    *,
    compact_block: str = "",
    include_sources: bool = False,
    sources: List[Dict[str, Any]] | None = None,
) -> str:
    summary = data.get("summary") or ""
    focus_summary = data.get("focus_summary") or ""
    top_focus = _normalize_items(data.get("top_focus") or [])
    tf = []
    for f in top_focus[:5]:
        tf.append(
            f"<li><b>{_escape(f.get('title'))}</b> — {_escape(f.get('why'))} <i style='color:#6b7280'>({_escape(f.get('suggestion') or '')})</i></li>"
        )
    top_focus_html = "<ul>" + "\n".join(tf) + "</ul>" if tf else '<p style="color:#6b7280">—</p>'
    section_scores = data.get("section_scores") or []
    issues = data.get("issues") or []

    blocks = [
        f"""
      <div class=\"card\">
        <h2>{_escape(title)} — краткое резюме</h2>
        <p>{_escape(summary)}</p>
        <p style=\"color:#374151\">{_escape(focus_summary)}</p>
        {compact_block}
      </div>""",
        f"""
      <div class=\"card\">
        <h2>{_escape(title)} — зоны внимания</h2>
        {top_focus_html}
      </div>""",
        f"""
      <div class=\"card\">
        <h2>{_escape(title)} — секции и баллы</h2>
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
            {_section_rows(section_scores)}
          </tbody>
        </table>
      </div>""",
        f"""
      <div class=\"card\">
        <h2>{_escape(title)} — замечания и рекомендации</h2>
        {_issues_list(issues)}
      </div>""",
    ]

    if include_sources:
        blocks.append(
            f"""
      <div class=\"card\">
        <h2>Нормативные источники (локальная база)</h2>
        {_sources_list(sources or [])}
      </div>"""
        )

    return "\n".join(blocks)


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

    law_present = any(
        [
            law_block["score_text"],
            law_block["summary"],
            law_block["section_scores"],
            law_block["issues"],
        ]
    )
    business_present = any(
        [
            business_block["score_text"],
            business_block["summary"],
            business_block["section_scores"],
            business_block["issues"],
        ]
    )

    chips: List[str] = []
    if law_present:
        chips.append(_score_chip("Соответствие законодательству", law_block["risk_color"], law_block["score_text"]))
    if business_present:
        chips.append(
            _score_chip(
                "Бизнес-риски и логика сделки",
                business_block["risk_color"],
                business_block["score_text"],
            )
        )
    if not chips:
        chips.append(_score_chip("Итоговая оценка", "", "—"))

    law_cards = (
        _analysis_cards(
            "Соответствие законодательству",
            law_block,
            compact_block=compact_block,
            include_sources=True,
            sources=sources,
        )
        if law_present
        else ""
    )

    business_cards = (
        _analysis_cards(
            "Бизнес-риски и логика сделки",
            business_block,
        )
        if business_present
        else ""
    )

    title_score = law_block["score_text"] or business_block["score_text"]

    html_doc = f"""<!DOCTYPE html>
<html lang=\"ru\"><head>
<meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
<title>Отчёт по договору — { _escape(title_score) }</title>
<style>
  body {{ font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial, \"Noto Sans\", \"Liberation Sans\", \"Helvetica Neue\", sans-serif; color:#111827; }}
  .card {{ background:#fff; border:1px solid #e5e7eb; border-radius:12px; padding:18px; margin:12px 0; }}
  h1 {{ font-size:20px; margin:6px 0 0 0; }}
  h2 {{ font-size:18px; margin:0 0 8px 0; }}
  small {{ color:#6b7280; }}
</style>
</head><body style=\"max-width:980px;margin:24px auto;padding:0 16px;background:#f3f4f6\">
  <div class=\"card\">
    <h1>Итоговые оценки договора</h1>
    <div style=\"display:flex;flex-wrap:wrap;gap:24px;margin-top:12px\">
      {''.join(chips)}
    </div>
    <div style=\"margin-top:12px;color:#6b7280\"><small>{now}</small></div>
  </div>

  {law_cards}

  {business_cards}

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
    outdir = Path("/workspace/reports")
    outdir.mkdir(parents=True, exist_ok=True)
    path = outdir / f"{ts}_{safe}.html"
    path.write_text(html_str, encoding="utf-8")
    return str(path)
