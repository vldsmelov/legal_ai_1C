from typing import List, Dict, Any, Tuple
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException

from ..types import AnalyzeRequest, AnalyzeResponse, SectionScore, SourceItem
from ..config import settings
from ..llm.ollama import ollama_chat_json
from ..prompts import get_prompt_template, render_prompt
from ..rag.store import rag_search_ru
from ..scoring import (
    build_focus,
    compute_total_and_color,
    get_section_defs,
    get_section_index,
    get_section_keys,
    sections_lines,
)
from ..utils import dedup_sources_by_hash
from ..report.summary import build_document_overview, summarize_report_block
from ..report.render import render_html, save_report_html

router = APIRouter()

DEFAULT_LAW_SUMMARY = (
    "Автоматическая предварительная оценка соответствия законодательству; требуется проверка юристом."
)
DEFAULT_BUSINESS_SUMMARY = (
    "Автоматическая оценка бизнес-логики и рисков для компании; результаты стоит перепроверить специалистами."
)


def _collect_report_meta(req: AnalyzeRequest) -> Dict[str, Any]:
    base = req.report_meta.dict() if req.report_meta else {}
    preview = base.get("compact_preview") or req.contract_text[:800]
    original_bytes = base.get("original_bytes") if base else None
    if original_bytes is None:
        original_bytes = len(req.contract_text.encode("utf-8", errors="ignore"))
    compact_bytes = base.get("compact_bytes") if base else None
    if compact_bytes is None:
        compact_bytes = original_bytes
    return {
        "source_path": base.get("source_path"),
        "source_url": base.get("source_url"),
        "compact_preview": preview,
        "original_bytes": original_bytes,
        "compact_bytes": compact_bytes,
    }


def _resolve_report_name(req: AnalyzeRequest, meta: Dict[str, Any]) -> str:
    if req.report_name:
        return req.report_name
    source_path = meta.get("source_path")
    if source_path:
        stem = Path(source_path).stem
        if stem:
            return stem
    source_url = meta.get("source_url")
    if source_url:
        parsed = urlparse(source_url)
        if parsed.path:
            stem = Path(parsed.path).stem
            if stem:
                return stem
        if parsed.netloc:
            return parsed.netloc.replace(":", "_")
    return "report"


def law_system_prompt(req: AnalyzeRequest) -> str:
    extra_rule = ""
    if settings.SCORING_MODE == "lenient":
        extra_rule = get_prompt_template("analyze_system_lenient_rule").strip()
        if extra_rule:
            extra_rule = f"{extra_rule}\n"
    return render_prompt(
        "analyze_system",
        jurisdiction=req.jurisdiction,
        contract_type=req.contract_type or "не указан",
        language=req.language,
        sections=sections_lines(),
        extra_rule=extra_rule,
    ).strip()


def law_user_prompt(req: AnalyzeRequest, ctx: List[SourceItem]) -> str:
    context_lines: List[str] = []
    if ctx:
        context_lines.append("=== КОНТЕКСТ НОРМ (РФ) — используй ТОЛЬКО это для ссылок ===")
        for i, s in enumerate(ctx, 1):
            cite = f"{s.act_title}, ст. {s.article}" if s.article else s.act_title
            rd = f" (ред. {s.revision_date})" if s.revision_date else ""
            context_lines.append(f"[{i}] {cite}{rd}: {s.text}")
        context_lines.append("=== КОНЕЦ КОНТЕКСТА ===")
        context_lines.append("")
    context_block = "\n".join(context_lines)
    if context_block:
        context_block = context_block + "\n"
    prompt_text = render_prompt(
        "analyze_user",
        context_block=context_block,
        contract_text=req.contract_text,
    )
    return prompt_text


def business_system_prompt(req: AnalyzeRequest) -> str:
    return render_prompt(
        "business_system",
        contract_type=req.contract_type or "не указан",
        language=req.language,
        sections=sections_lines(),
    ).strip()


def business_user_prompt(req: AnalyzeRequest) -> str:
    return render_prompt("business_user", contract_text=req.contract_text)


def overview_system_prompt(req: AnalyzeRequest) -> str:
    return render_prompt(
        "overview_system",
        jurisdiction=req.jurisdiction,
        contract_type=req.contract_type or "не указан",
        language=req.language,
    ).strip()


def overview_user_prompt(req: AnalyzeRequest) -> str:
    return render_prompt("overview_user", contract_text=req.contract_text)


def _has_all_sections(payload: Dict[str, Any]) -> bool:
    sections = payload.get("sections")
    if not isinstance(sections, list):
        return False
    keys = {item.get("key") for item in sections if isinstance(item, dict) and item.get("key")}
    return get_section_keys().issubset(keys)


async def _call_business_model(
    req: AnalyzeRequest, max_tokens: int
) -> Tuple[Dict[str, Any], str, Dict[str, Any], str, str]:
    biz_sys = business_system_prompt(req)
    biz_usr = business_user_prompt(req)
    payload, raw_text, call_meta = await ollama_chat_json(
        biz_sys, biz_usr, req.model, max_tokens=max_tokens
    )
    return payload, raw_text, call_meta, biz_sys, biz_usr


def _ensure_section_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Ensure that business payload contains all sections with sane defaults."""

    payload = dict(payload or {})

    raw_sections = payload.get("sections") if isinstance(payload.get("sections"), list) else []
    prepared: Dict[str, Dict[str, Any]] = {}
    for item in raw_sections:
        if not isinstance(item, dict):
            continue
        key = item.get("key")
        if not key:
            continue
        try:
            raw_val = int(item.get("raw", 0))
        except (TypeError, ValueError):
            raw_val = 0
        raw_val = max(0, min(5, raw_val))
        comment = item.get("comment")
        if not isinstance(comment, str):
            comment = ""
        prepared[str(key)] = {
            "key": str(key),
            "raw": raw_val,
            "comment": comment.strip(),
        }

    sections: List[Dict[str, Any]] = []
    for section in get_section_defs():
        entry = prepared.get(section["key"])
        if entry is None:
            entry = {
                "key": section["key"],
                "raw": 0,
                "comment": "модель не сформировала оценку по этому разделу.",
            }
        sections.append(entry)

    payload["sections"] = sections

    issues = payload.get("issues")
    if not isinstance(issues, list):
        payload["issues"] = []

    summary = payload.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        payload["summary"] = (
            "Автоматическое резюме не сформировано моделью; разделы оценены с минимальными значениями."
        )

    return payload


async def _generate_business_payload(
    req: AnalyzeRequest,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    attempts: List[int] = []
    base = req.max_tokens or settings.BUSINESS_MAX_TOKENS
    attempts.append(max(base, 512))
    # Добавляем запас, если модель урезала ответ
    attempts.append(max(base + settings.BUSINESS_RETRY_STEP, base))

    last_payload: Dict[str, Any] = {}
    debug_calls: List[Dict[str, Any]] = []
    for attempt_idx, tokens in enumerate(attempts, start=1):
        try:
            payload, raw_text, call_meta, biz_sys, biz_usr = await _call_business_model(
                req, tokens
            )
        except Exception:
            continue
        debug_calls.append(
            {
                "kind": "business",
                "attempt": attempt_idx,
                "max_tokens": tokens,
                "parsed_response": payload,
                "system_prompt": biz_sys,
                "user_prompt": biz_usr,
                "raw_response": raw_text,
                "endpoint": call_meta.get("endpoint"),
                "endpoint_url": call_meta.get("url")
                or f"{settings.OLLAMA_URL}/api/{call_meta.get('endpoint', 'chat')}",
                "model": req.model or settings.OLLAMA_MODEL,
            }
        )
        if _has_all_sections(payload):
            return _ensure_section_payload(payload), debug_calls
        last_payload = payload or {}
    return _ensure_section_payload(last_payload), debug_calls


def build_report(parsed: Dict[str, Any], default_summary: str) -> Dict[str, Any]:
    sections_in: List[SectionScore] = []
    missing_keys: List[str] = []
    section_defs = get_section_defs()
    section_index = get_section_index()
    for sdef in section_defs:
        raw_item = next((c for c in (parsed.get("sections") or []) if c.get("key") == sdef["key"]), None)
        if raw_item is None:
            sections_in.append(SectionScore(key=sdef["key"], raw=0, comment="не найдено"))
            missing_keys.append(sdef["key"])
        else:
            try:
                raw_val = int(raw_item.get("raw", 0))
            except Exception:
                raw_val = 0
            raw_val = max(0, min(5, raw_val))
            sections_in.append(
                SectionScore(
                    key=sdef["key"],
                    raw=raw_val,
                    comment=(raw_item.get("comment") or "")[:2000],
                )
            )

    score_total, color, section_table = compute_total_and_color(sections_in)
    verdict = (
        "ok"
        if score_total >= settings.SCORE_GREEN
        else "needs_review"
        if score_total >= settings.SCORE_YELLOW
        else "high_risk"
    )
    score_text = f"{score_total}/100 ({color})"

    issues_raw = parsed.get("issues") or []
    issues: List[Dict[str, Any]] = []
    for it in issues_raw:
        section_key = it.get("section", "")
        if section_key not in section_index:
            section_key = "scope"
        sev = it.get("severity", "medium")
        if sev not in ("high", "medium", "low"):
            sev = "medium"
        text = (it.get("text") or "").strip()
        suggestion = (it.get("suggestion") or "").strip() or None
        if text:
            issues.append(
                {
                    "section": section_key,
                    "severity": sev,
                    "text": text,
                    "suggestion": suggestion,
                }
            )

    focus_summary, top_focus_models = build_focus(section_table, issues)
    top_focus = [item.dict() for item in top_focus_models]
    summary = (parsed.get("summary") or "").strip() or default_summary
    if section_defs and len(missing_keys) == len(section_defs):
        summary = (
            "Модель не смогла сформировать оценки по бизнес-рискам; повторите анализ или обновите промпт."
        )
        focus_summary = "Бизнес-анализ не сформирован из-за ошибки генерации."
        top_focus = []

    return {
        "score_total": score_total,
        "score_text": score_text,
        "verdict": verdict,
        "risk_color": color,
        "summary": summary,
        "focus_summary": focus_summary,
        "top_focus": top_focus,
        "issues": issues,
        "section_scores": section_table,
    }


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze(req: AnalyzeRequest):
    # 1) RAG — проверка по законодательству
    rag_error: Dict[str, Any] | None = None
    try:
        ctx = rag_search_ru(req.contract_text, top_k=settings.RAG_TOP_K)
    except Exception as exc:
        ctx = []
        rag_error = {"error": str(exc)}
    ctx = dedup_sources_by_hash(ctx)
    llm_calls: List[Dict[str, Any]] = []
    pipeline: List[Dict[str, Any]] = []
    step_counter = 1

    pipeline.append(
        {
            "step": step_counter,
            "name": "rag_vector_search",
            "description": "Поиск нормативных актов в Qdrant по вектору запроса",
            "target_url": f"{settings.QDRANT_URL}/collections/{settings.QDRANT_COLLECTION}/points/search",
            "method": "POST",
            "status": "error" if rag_error else ("ok" if ctx else "no_matches"),
            "details": {
                "top_k": settings.RAG_TOP_K,
                "hits": len(ctx),
                "collection": settings.QDRANT_COLLECTION,
                "embedding_model": settings.EMBEDDING_MODEL,
            },
        }
    )
    if rag_error:
        pipeline[-1]["details"].update(rag_error)
    step_counter += 1
    # 2) LLM — юридическая оценка с контекстом RAG
    sys = law_system_prompt(req)
    usr = law_user_prompt(req, ctx)
    law_tokens = req.max_tokens or 1024
    try:
        law_parsed, law_raw, law_meta = await ollama_chat_json(
            sys, usr, req.model, max_tokens=law_tokens
        )
        llm_calls.append(
            {
                "kind": "law",
                "system_prompt": sys,
                "user_prompt": usr,
                "raw_response": law_raw,
                "parsed_response": law_parsed,
                "endpoint": law_meta.get("endpoint"),
                "endpoint_url": law_meta.get("url")
                or f"{settings.OLLAMA_URL}/api/{law_meta.get('endpoint', 'chat')}",
                "max_tokens": law_tokens,
                "model": req.model or settings.OLLAMA_MODEL,
            }
        )
        pipeline.append(
            {
                "step": step_counter,
                "name": "law_llm_analysis",
                "description": "Юридический анализ договора через Ollama",
                "target_url": llm_calls[-1]["endpoint_url"],
                "method": "POST",
                "status": "ok",
                "details": {
                    "model": llm_calls[-1]["model"],
                    "max_tokens": law_tokens,
                    "endpoint": llm_calls[-1]["endpoint"],
                },
            }
        )
        step_counter += 1
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Ollama error: {e}")

    law_report = build_report(law_parsed, DEFAULT_LAW_SUMMARY)

    # 3) LLM — бизнес-риски без RAG
    try:
        business_parsed, business_debug = await _generate_business_payload(req)
        llm_calls.extend(business_debug)
        for call in business_debug:
            pipeline.append(
                {
                    "step": step_counter,
                    "name": "business_llm_analysis",
                    "description": "Оценка бизнес-рисков через Ollama",
                    "target_url": call.get("endpoint_url")
                    or f"{settings.OLLAMA_URL}/api/{call.get('endpoint', 'chat')}",
                    "method": "POST",
                    "status": "ok" if call.get("parsed_response") else "empty",
                    "details": {
                        "model": call.get("model"),
                        "max_tokens": call.get("max_tokens"),
                        "attempt": call.get("attempt"),
                        "endpoint": call.get("endpoint"),
                    },
                }
            )
            step_counter += 1
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Ollama error: {e}")

    business_report = build_report(business_parsed, DEFAULT_BUSINESS_SUMMARY)

    overview_sys = overview_system_prompt(req)
    overview_usr = overview_user_prompt(req)
    overview_tokens = min(req.max_tokens or 600, 600)
    try:
        overview_raw, overview_raw_text, overview_meta = await ollama_chat_json(
            overview_sys,
            overview_usr,
            req.model,
            max_tokens=overview_tokens,
        )
        llm_calls.append(
            {
                "kind": "overview",
                "system_prompt": overview_sys,
                "user_prompt": overview_usr,
                "raw_response": overview_raw_text,
                "parsed_response": overview_raw,
                "endpoint": overview_meta.get("endpoint"),
                "endpoint_url": overview_meta.get("url")
                or f"{settings.OLLAMA_URL}/api/{overview_meta.get('endpoint', 'chat')}",
                "max_tokens": overview_tokens,
                "model": req.model or settings.OLLAMA_MODEL,
            }
        )
        pipeline.append(
            {
                "step": step_counter,
                "name": "overview_llm_summary",
                "description": "Генерация обзорного резюме документа через Ollama",
                "target_url": llm_calls[-1]["endpoint_url"],
                "method": "POST",
                "status": "ok",
                "details": {
                    "model": llm_calls[-1]["model"],
                    "max_tokens": overview_tokens,
                    "endpoint": llm_calls[-1]["endpoint"],
                },
            }
        )
        step_counter += 1
    except Exception:
        overview_raw = {}
    overview = build_document_overview(overview_raw)

    law_narrative = summarize_report_block(law_report, "Соответствие законодательству")
    business_narrative = summarize_report_block(business_report, "Бизнес-риски и логика сделки")

    payload: Dict[str, Any] = {
        "score_total": law_report["score_total"],
        "score_text": law_report["score_text"],
        "verdict": law_report["verdict"],
        "risk_color": law_report["risk_color"],
        "summary": law_report["summary"],
        "focus_summary": law_report["focus_summary"],
        "top_focus": law_report["top_focus"],
        "jurisdiction": req.jurisdiction,
        "issues": law_report["issues"],
        "section_scores": law_report["section_scores"],
        "sources": ctx,
        "business_score_total": business_report["score_total"],
        "business_score_text": business_report["score_text"],
        "business_verdict": business_report["verdict"],
        "business_risk_color": business_report["risk_color"],
        "business_summary": business_report["summary"],
        "business_focus_summary": business_report["focus_summary"],
        "business_top_focus": business_report["top_focus"],
        "business_issues": business_report["issues"],
        "business_section_scores": business_report["section_scores"],
        "overview": overview,
        "law_narrative": law_narrative,
        "business_narrative": business_narrative,
        "llm_calls": llm_calls,
        "pipeline": pipeline,
    }

    if (req.report_format or "").lower() == "html":
        meta = _collect_report_meta(req)
        html_str = render_html(meta=meta, analysis=payload)
        report_name = _resolve_report_name(req, meta)
        payload["report_path"] = save_report_html(html_str, report_name)

    return AnalyzeResponse(**payload)
