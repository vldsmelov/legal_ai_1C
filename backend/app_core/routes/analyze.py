from fastapi import APIRouter, HTTPException
from typing import List, Dict, Any
from ..types import GenerateRequest, AnalyzeRequest, AnalyzeResponse, SectionScore, SourceItem
from ..config import settings
from ..llm.ollama import ollama_generate, ollama_chat_json
from ..prompts import render_prompt
from ..rag.store import rag_search_ru
from ..rerank import apply_rerank
from ..scoring import SECTION_DEFS, SECTION_INDEX, compute_total_and_color, build_focus, sections_lines
from ..utils import dedup_sources_by_hash

router = APIRouter()

def system_prompt(req: AnalyzeRequest) -> str:
    extra_rule = ""
    if settings.SCORING_MODE == "lenient":
        extra_rule = "- Если раздел упомянут, но не детализирован — ставь 2–3 (а не 0).\n"
    return render_prompt(
        "analysis_system.j2",
        jurisdiction=req.jurisdiction,
        contract_type=req.contract_type or "не указан",
        language=req.language,
        sections=sections_lines(),
        extra_rule=extra_rule,
    ).strip()

def user_prompt(req: AnalyzeRequest, ctx: List[SourceItem]) -> str:
    context_lines = []
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
        context_block = f"{context_block}\n"
    return render_prompt(
        "analysis_user.j2",
        context_block=context_block,
        contract_text=req.contract_text,
    ).strip()

@router.post("/generate")
async def generate(body: GenerateRequest):
    try:
        text = await ollama_generate(body.prompt, body.max_tokens or 512, body.model)
        return {"model": body.model or settings.OLLAMA_MODEL, "text": text}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Ollama error: {e}")

@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze(req: AnalyzeRequest):
    # 1) RAG
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

    # 2) LLM
    sys = system_prompt(req)
    usr = user_prompt(req, ctx)
    try:
        parsed = await ollama_chat_json(sys, usr, req.model, max_tokens=req.max_tokens or 1024)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Ollama error: {e}")

    # 3) Нормализация
    sections_in: List[SectionScore] = []
    for sdef in SECTION_DEFS:
        raw_item = next((c for c in (parsed.get("sections") or []) if c.get("key") == sdef["key"]), None)
        if raw_item is None:
            sections_in.append(SectionScore(key=sdef["key"], raw=0, comment="не найдено"))
        else:
            try: raw_val = int(raw_item.get("raw", 0))
            except Exception: raw_val = 0
            raw_val = max(0, min(5, raw_val))
            sections_in.append(SectionScore(key=sdef["key"], raw=raw_val, comment=(raw_item.get("comment") or "")[:2000]))

    score_total, color, section_table = compute_total_and_color(sections_in)
    verdict = "ok" if score_total >= settings.SCORE_GREEN else "needs_review" if score_total >= settings.SCORE_YELLOW else "high_risk"
    score_text = f"{score_total}/100 ({color})"

    issues_raw = parsed.get("issues") or []
    issues: List[Dict[str, Any]] = []
    for it in issues_raw:
        section_key = it.get("section", "")
        if section_key not in SECTION_INDEX:
            section_key = "scope"
        sev = it.get("severity", "medium")
        if sev not in ("high","medium","low"):
            sev = "medium"
        text = (it.get("text") or "").strip()
        suggestion = (it.get("suggestion") or "").strip() or None
        if text:
            issues.append({"section": section_key, "severity": sev, "text": text, "suggestion": suggestion})

    focus_summary, top_focus = build_focus(section_table, issues)
    summary = (parsed.get("summary") or "").strip() or "Автоматическая предварительная оценка; источники из локальной базы РФ (если найдены)."

    return AnalyzeResponse(
        score_total=score_total, score_text=score_text, verdict=verdict,
        risk_color=color, summary=summary, focus_summary=focus_summary,
        top_focus=top_focus, jurisdiction=req.jurisdiction, issues=issues,
        section_scores=section_table, sources=ctx
    )
