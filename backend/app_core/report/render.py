# backend/app_core/report/render.py
from __future__ import annotations
from typing import Dict, Any, List
from datetime import datetime
from pathlib import Path
import re
import html

def _risk_badge(color: str) -> str:
    color = (color or "").lower()
    bg = {"green":"#16a34a","yellow":"#ca8a04","red":"#dc2626"}.get(color, "#64748b")
    return f'style="display:inline-block;padding:4px 10px;border-radius:999px;background:{bg};color:#fff;font-weight:600;font-size:12px"'

def _escape(s: Any) -> str:
    return html.escape(str(s) if s is not None else "")

def _section_rows(section_scores: List[Dict[str,Any]]) -> str:
    rows = []
    for s in section_scores or []:
        pct = 0
        try:
            pct = int(round(100 * float(s.get("score",0)) / float(s.get("of",1))))
        except Exception:
            pct = 0
        bar = f'''
          <div style="background:#e5e7eb;height:8px;border-radius:6px;overflow:hidden">
            <div style="width:{pct}%;height:8px;background:#3b82f6"></div>
          </div>'''
        rows.append(f"""
          <tr>
            <td style="padding:8px 12px;border-bottom:1px solid #eee">{_escape(s.get("title"))}</td>
            <td style="padding:8px 12px;border-bottom:1px solid #eee;white-space:nowrap">{_escape(s.get("score"))} / {_escape(s.get("of"))}</td>
            <td style="padding:8px 12px;border-bottom:1px solid #eee">{bar}</td>
            <td style="padding:8px 12px;border-bottom:1px solid #eee;color:#6b7280">{_escape(s.get("comment") or "")}</td>
          </tr>""")
    return "\n".join(rows)

def _issues_list(issues: List[Dict[str,Any]]) -> str:
    if not issues:
        return '<p style="color:#6b7280">Явных критичных замечаний не выявлено.</p>'
    items = []
    for it in issues:
        items.append(f"""
          <li style="margin-bottom:8px">
            <b>{_escape(it.get('section'))}</b>: {_escape(it.get('text'))}
            <div style="color:#6b7280"><i>Рекомендация:</i> {_escape(it.get('suggestion') or '')}</div>
          </li>""")
    return "<ul>" + "\n".join(items) + "</ul>"

def _sources_list(sources: List[Dict[str,Any]]) -> str:
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

def render_html(meta: Dict[str,Any], analysis: Dict[str,Any]) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    risk = (analysis or {}).get("risk_color", "")
    score_text = (analysis or {}).get("score_text", "")
    summary = (analysis or {}).get("summary", "")
    focus_summary = (analysis or {}).get("focus_summary", "")
    top_focus = (analysis or {}).get("top_focus") or []
    section_scores = (analysis or {}).get("section_scores") or []
    sources = (analysis or {}).get("sources") or []

    tf = []
    for f in top_focus[:5]:
        tf.append(f"<li><b>{_escape(f.get('title'))}</b> — {_escape(f.get('why'))} <i style='color:#6b7280'>({_escape(f.get('suggestion') or '')})</i></li>")
    top_focus_html = "<ul>" + "\n".join(tf) + "</ul>" if tf else '<p style="color:#6b7280">—</p>'

    compact_preview = meta.get("compact_preview") or ""
    compact_block = f"""
      <details>
        <summary style="cursor:pointer"><b>Показать компактный текст для анализа</b></summary>
        <pre style="white-space:pre-wrap;background:#f8fafc;border:1px solid #e5e7eb;border-radius:8px;padding:12px;margin-top:8px;max-height:420px;overflow:auto">{_escape(compact_preview)}</pre>
      </details>
    """ if compact_preview else ""

    src_info = ""
    if meta.get("source_path"):
        src_info = f"<div><b>Файл:</b> {_escape(meta['source_path'])}</div>"
    elif meta.get("source_url"):
        src_info = f"<div><b>URL:</b> {_escape(meta['source_url'])}</div>"

    html_doc = f"""<!DOCTYPE html>
<html lang="ru"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Отчёт по договору — { _escape(score_text) }</title>
<style>
  body {{ font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial, "Noto Sans", "Liberation Sans", "Helvetica Neue", sans-serif; color:#111827; }}
  .card {{ background:#fff; border:1px solid #e5e7eb; border-radius:12px; padding:18px; margin:12px 0; }}
  h1 {{ font-size:20px; margin:6px 0 0 0; }}
  h2 {{ font-size:18px; margin:0 0 8px 0; }}
  small {{ color:#6b7280; }}
</style>
</head><body style="max-width:980px;margin:24px auto;padding:0 16px;background:#f3f4f6">
  <div class="card" style="display:flex;align-items:center;gap:12px">
    <div { _risk_badge(risk) }>{ _escape(risk) or "n/a" }</div>
    <h1>Итоговый скор: { _escape(score_text) }</h1>
    <div style="margin-left:auto"><small>{now}</small></div>
  </div>

  <div class="card">
    <h2>Краткое резюме</h2>
    <p>{_escape(summary)}</p>
    <p style="color:#374151">{_escape(focus_summary)}</p>
    {compact_block}
  </div>

  <div class="card">
    <h2>Куда смотреть в первую очередь</h2>
    {top_focus_html}
  </div>

  <div class="card">
    <h2>Секции и баллы</h2>
    <table style="width:100%;border-collapse:collapse">
      <thead>
        <tr>
          <th style="text-align:left;padding:8px 12px;border-bottom:1px solid #ddd">Раздел</th>
          <th style="text-align:left;padding:8px 12px;border-bottom:1px solid #ddd">Баллы</th>
          <th style="text-align:left;padding:8px 12px;border-bottom:1px solid #ddd;width:240px">Уровень</th>
          <th style="text-align:left;padding:8px 12px;border-bottom:1px solid #ddd">Комментарий</th>
        </tr>
      </thead>
      <tbody>
        {_section_rows(section_scores)}
      </tbody>
    </table>
  </div>

  <div class="card">
    <h2>Замечания и рекомендации</h2>
    {_issues_list(analysis.get('issues') or [])}
  </div>

  <div class="card">
    <h2>Нормативные источники (локальная база)</h2>
    {_sources_list(sources)}
  </div>

  <div class="card" style="color:#374151">
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
