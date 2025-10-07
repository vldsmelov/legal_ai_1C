from typing import List, Dict, Any

from fastapi import APIRouter, HTTPException

from ..types import GenerateRequest, AnalyzeRequest, AnalyzeResponse, SectionScore, SourceItem
from ..config import settings
from ..llm.ollama import ollama_generate, ollama_chat_json
from ..prompts import get_prompt_template, render_prompt
from ..rag.store import rag_search_ru
from ..rerank import apply_rerank
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

router = APIRouter()

DEFAULT_LAW_SUMMARY = (
    "Автоматическая предварительная оценка соответствия законодательству; требуется проверка юристом."
)
DEFAULT_BUSINESS_SUMMARY = (
    "Автоматическая оценка бизнес-логики и рисков для компании; результаты стоит перепроверить специалистами."
)


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


async def _call_business_model(req: AnalyzeRequest, max_tokens: int) -> Dict[str, Any]:
    biz_sys = business_system_prompt(req)
    biz_usr = business_user_prompt(req)
    return await ollama_chat_json(biz_sys, biz_usr, req.model, max_tokens=max_tokens)


async def _generate_business_payload(req: AnalyzeRequest) -> Dict[str, Any]:
    attempts: List[int] = []
    base = req.max_tokens or settings.BUSINESS_MAX_TOKENS
    attempts.append(max(base, 512))
    # Добавляем запас, если модель урезала ответ
    attempts.append(max(base + settings.BUSINESS_RETRY_STEP, base))

    last_payload: Dict[str, Any] = {}
    for tokens in attempts:
        try:
            payload = await _call_business_model(req, tokens)
        except Exception:
            continue
        if _has_all_sections(payload):
            return payload
        last_payload = payload or {}
    return last_payload


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


@router.post("/generate")
async def generate(body: GenerateRequest):
    try:
        text = await ollama_generate(body.prompt, body.max_tokens or 512, body.model)
        return {"model": body.model or settings.OLLAMA_MODEL, "text": text}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Ollama error: {e}")


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze(req: AnalyzeRequest):
    # 1) RAG — проверка по законодательству
    try:
        ctx = rag_search_ru(req.contract_text, top_k=settings.RAG_TOP_K)
    except Exception:
        ctx = []
    ctx = dedup_sources_by_hash(ctx)
    # 1.1) rerank
    try:
        keep = min(settings.RERANK_KEEP, len(ctx))
        ctx = apply_rerank(req.contract_text, ctx, keep=keep)
        ctx = dedup_sources_by_hash(ctx)
    except Exception as e:
        print("[RERANK] failed:", e)

    # 2) LLM — юридическая оценка с контекстом RAG
    sys = law_system_prompt(req)
    usr = law_user_prompt(req, ctx)
    try:
        law_parsed = await ollama_chat_json(sys, usr, req.model, max_tokens=req.max_tokens or 1024)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Ollama error: {e}")

    law_report = build_report(law_parsed, DEFAULT_LAW_SUMMARY)

    # 3) LLM — бизнес-риски без RAG
    try:
        business_parsed = await _generate_business_payload(req)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Ollama error: {e}")

    business_report = build_report(business_parsed, DEFAULT_BUSINESS_SUMMARY)

    try:
        overview_raw = await ollama_chat_json(
            overview_system_prompt(req),
            overview_user_prompt(req),
            req.model,
            max_tokens=min(req.max_tokens or 600, 600),
        )
    except Exception:
        overview_raw = {}
    overview = build_document_overview(overview_raw)

    law_narrative = summarize_report_block(law_report, "Соответствие законодательству")
    business_narrative = summarize_report_block(business_report, "Бизнес-риски и логика сделки")

    return AnalyzeResponse(
        score_total=law_report["score_total"],
        score_text=law_report["score_text"],
        verdict=law_report["verdict"],
        risk_color=law_report["risk_color"],
        summary=law_report["summary"],
        focus_summary=law_report["focus_summary"],
        top_focus=law_report["top_focus"],
        jurisdiction=req.jurisdiction,
        issues=law_report["issues"],
        section_scores=law_report["section_scores"],
        sources=ctx,
        business_score_total=business_report["score_total"],
        business_score_text=business_report["score_text"],
        business_verdict=business_report["verdict"],
        business_risk_color=business_report["risk_color"],
        business_summary=business_report["summary"],
        business_focus_summary=business_report["focus_summary"],
        business_top_focus=business_report["top_focus"],
        business_issues=business_report["issues"],
        business_section_scores=business_report["section_scores"],
        overview=overview,
        law_narrative=law_narrative,
        business_narrative=business_narrative,
    )
