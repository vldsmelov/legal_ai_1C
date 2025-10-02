# backend/app_core/routes/doc.py
from __future__ import annotations
from fastapi import APIRouter, Body, Query
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import httpx, re, os

import anyio
import contextlib

from ..report.render import render_html, save_report_html


router = APIRouter(prefix="/doc", tags=["doc"])

# --- эвристики по заголовкам разделов (RU) ---
# порядок важен — таким и соберём компактный текст
SECTION_PATTERNS: List[Tuple[str, re.Pattern]] = [
    ("parties", re.compile(r"^\s*(стороны|реквизиты.*стор|реквизит[ы]|сторона[ы]?)\b", re.I)),
    ("scope", re.compile(r"^\s*(предмет\s+договора|предмет|объём|обьем|описание\s+(услуг|работ))\b", re.I)),
    ("timeline_acceptance", re.compile(r"^\s*(сроки|порядок\s+(оказания|выполнения)|приемк|приёмк|сдач[аи])\b", re.I)),
    ("payment", re.compile(r"^\s*(цена|стоимость|оплата|порядок\s+расч[её]тов|вознаграждени[ея])\b", re.I)),
    ("liability", re.compile(r"^\s*(ответственност[ьи]|штраф|неусто[йи]к)\b", re.I)),
    ("reps_warranties", re.compile(r"^\s*(гарант(ии|ии и заверения)|заверен[иия])\b", re.I)),
    ("ip", re.compile(r"^\s*(интеллектуальн|исключительн[ыеое]\s+прав[ао]|права\s+на\s+результат)\b", re.I)),
    ("confidentiality", re.compile(r"^\s*(конфиденциал|коммерческ(ая)?\s+тайн)\b", re.I)),
    ("personal_data", re.compile(r"^\s*(персональн(ые)?\s+данн|152[-\s]?фз|обработк[аи]\s+персональных)\b", re.I)),
    ("force_majeure", re.compile(r"^\s*(форс[-\s]?мажор|обстоятельств[аы]\s+непреодолимой\s+силы)\b", re.I)),
    ("change_termination", re.compile(r"^\s*(изменени[ея]|расторжен|односторонн(ий|ый)\s+отказ)\b", re.I)),
    ("law_venue", re.compile(r"^\s*(применим(ое)?\s+право|подсудност[ьи]|арбитраж|разрешени[ея]\s+споров)\b", re.I)),
    ("conflicts_priority", re.compile(r"^\s*(приоритет\s+документ|конфликт.*документ)\b", re.I)),
    ("signatures_form", re.compile(r"^\s*(подпис(и|ь)|электронн(ая|ые)\s+подпис|экземпляр|оформлени[ея])\b", re.I)),
]

ORDER = [k for k, _ in SECTION_PATTERNS]

def _read_text_file(path: Path) -> str:
    for enc in ("utf-8", "cp1251"):
        try:
            return path.read_text(encoding=enc)
        except Exception:
            continue
    # как крайний случай — без указания кодировки
    return path.read_text(errors="ignore")

def _normalize(s: str) -> str:
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = re.sub(r"[ \t]+\n", "\n", s)
    return s

def _split_paragraphs(s: str) -> List[str]:
    # делим по пустым строкам, убирая мусорные пробелы
    parts = [p.strip() for p in re.split(r"\n{2,}", s)]
    return [p for p in parts if p]

def extract_sections(raw_text: str) -> Dict[str, List[str]]:
    """
    Очень простая эвристика: ищем «шапки» разделов по заголовкам
    и накапливаем абзацы до следующего заголовка.
    """
    text = _normalize(raw_text)
    lines = text.split("\n")

    sections: Dict[str, List[str]] = {k: [] for k in ORDER}
    other: List[str] = []

    cur_key: Optional[str] = None
    buf: List[str] = []

    def flush():
        nonlocal buf, cur_key
        if not buf:
            return
        chunk = "\n".join(buf).strip()
        if chunk:
            if cur_key and cur_key in sections:
                sections[cur_key].append(chunk)
            else:
                other.append(chunk)
        buf = []

    for ln in lines:
        line = ln.strip()
        if not line:
            buf.append("")  # сохраняем пустую строку как разрыв
            continue
        # проверяем, не начинается ли новый раздел
        matched_key = None
        for key, rx in SECTION_PATTERNS:
            if rx.match(line):
                matched_key = key
                break
        if matched_key:
            flush()
            cur_key = matched_key
            # строку-заголовок в тело не кладём
            continue

        buf.append(line)

    flush()

    if other:
        sections.setdefault("other", []).extend(_split_paragraphs("\n".join(other)))

    return sections

def build_compact(sections: Dict[str, List[str]],
                  per_section_limit: int = 2000,
                  total_limit: int = 15000) -> str:
    """
    Собираем компактный текст в фиксированном порядке.
    На раздел — не более per_section_limit символов.
    Общий лимит — total_limit.
    """
    out_parts: List[str] = []
    remaining = total_limit

    def take(key: str):
        nonlocal remaining
        blocks = sections.get(key) or []
        if not blocks:
            return
        joined = "\n\n".join(blocks)
        snippet = joined[:min(per_section_limit, max(0, remaining))]
        if snippet:
            out_parts.append(f"=== {key} ===\n{snippet}")
            remaining -= len(snippet) + len(key) + 8  # грубое учёт заголовка/переносов

    for key in ORDER:
        if remaining <= 0:
            break
        take(key)

    if remaining > 0 and sections.get("other"):
        take("other")

    compact = "\n\n".join(out_parts).strip()
    # запасная страховка:
    if len(compact) > total_limit:
        compact = compact[:total_limit]
    return compact



async def _call_analyze(compact_text: str,
                        jurisdiction: str, contract_type: str, language: str, max_tokens: int) -> dict:
    payload = {
        "contract_text": compact_text,
        "jurisdiction": jurisdiction,
        "contract_type": contract_type,
        "language": language,
        "max_tokens": max_tokens
    }
    # Большой таймаут на чтение/запись для больших документов
    timeout = httpx.Timeout(connect=5.0, read=300.0, write=300.0, pool=300.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post("http://127.0.0.1:8000/analyze", json=payload)
        r.raise_for_status()
        return r.json()


# ----------- эндпоинты ------------

@router.post("/analyze_file")
async def analyze_file(
    path: str = Body(..., embed=True, description="Относительно /workspace, напр. 'samples/my_contract.txt'"),
    jurisdiction: str = Body("RU", embed=True),
    contract_type: str = Body("услуги", embed=True),
    language: str = Body("ru", embed=True),
    max_tokens: int = Body(600, embed=True),
    per_section_limit: int = Body(2200, embed=True),
    total_limit: int = Body(20000, embed=True),
    report_format: str | None = Body(None, embed=True, description="html | null"),
    report_save: bool = Body(False, embed=True),
    report_inline: bool = Body(False, embed=True),
    report_name: str | None = Body(None, embed=True),
):
    base = Path("/workspace")
    p = Path(path) if Path(path).is_absolute() else base / path
    if not p.exists():
        return {"error": f"file not found: {p}"}
    raw = _read_text_file(p)
    sections = extract_sections(raw)
    compact = build_compact(sections, per_section_limit=per_section_limit, total_limit=total_limit)
    analysis = await _call_analyze(compact, jurisdiction, contract_type, language, max_tokens)

    resp = {
        "source_path": str(p),
        "original_bytes": len(raw.encode("utf-8", errors="ignore")),
        "compact_bytes": len(compact.encode("utf-8", errors="ignore")),
        "compact_preview": compact[:800],
        "analysis": analysis
    }

    if (report_format or "").lower() == "html":
        html_str = render_html(
            meta={"source_path": str(p), "compact_preview": compact, "original_bytes": resp["original_bytes"], "compact_bytes": resp["compact_bytes"]},
            analysis=analysis
        )
        if report_save:
            out = save_report_html(html_str, report_name or Path(path).stem)
            resp["report_path"] = out
        if report_inline:
            resp["report_html"] = html_str

    return resp 

@router.post("/analyze_url")
async def analyze_url(
    url: str = Body(..., embed=True),
    allow_http_downgrade: bool = Body(True, embed=True),
    timeout: float = Body(15.0, embed=True),
    max_bytes: int = Body(5_000_000, embed=True),
    jurisdiction: str = Body("RU", embed=True),
    contract_type: str = Body("услуги", embed=True),
    language: str = Body("ru", embed=True),
    max_tokens: int = Body(600, embed=True),
    per_section_limit: int = Body(2200, embed=True),
    total_limit: int = Body(20000, embed=True),
    report_format: str | None = Body(None, embed=True),
    report_save: bool = Body(False, embed=True),
    report_inline: bool = Body(False, embed=True),
    report_name: str | None = Body(None, embed=True),
):
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) LegalAI/0.6 docfetch",
        "Accept": "text/plain, text/*;q=0.9, */*;q=0.8",
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=min(5.0, timeout), read=timeout)) as client:
        async def get(u: str):
            async with client.stream("GET", u, headers=headers, follow_redirects=True) as r:
                total, chunks = 0, []
                async for c in r.aiter_bytes():
                    if not c: break
                    total += len(c)
                    if total > max_bytes:
                        c = c[: max(0, max_bytes - (total - len(c)))]
                        total = max_bytes
                    chunks.append(c)
                    if total >= max_bytes: break
                body = b"".join(chunks)
                return r, body
        try:
            r, body = await get(url)
        except httpx.RequestError as e:
            if allow_http_downgrade and url.startswith("https://"):
                r, body = await get("http://" + url[len("https://"):])
            else:
                return {"error": f"download: {e}", "url": url}

    if not body:
        return {"error": "empty body", "url": url}

    # Расчётно ожидаем text/plain; но если пришёл HTML — чуть подчистим теги
    text = body.decode("utf-8", errors="replace")
    if "<html" in text.lower():
        # очень простой «анти-HTML» — оставим только текст
        text = re.sub(r"(?s)<script.*?</script>", " ", text, flags=re.I)
        text = re.sub(r"(?s)<style.*?</style>", " ", text, flags=re.I)
        text = re.sub(r"(?s)<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()

    sections = extract_sections(text)
    compact = build_compact(sections, per_section_limit=per_section_limit, total_limit=total_limit)
    analysis = await _call_analyze(compact, jurisdiction, contract_type, language, max_tokens)

    resp = {
        "source_url": url,
        "http_status": getattr(r, "status_code", None),
        "final_url": str(getattr(r, "url", url)),
        "original_bytes": len(text.encode("utf-8", errors="ignore")),
        "compact_bytes": len(compact.encode("utf-8", errors="ignore")),
        "compact_preview": compact[:800],
        "analysis": analysis
    }

    if (report_format or "").lower() == "html":
        html_str = render_html(
            meta={"source_url": url, "compact_preview": compact, "original_bytes": resp["original_bytes"], "compact_bytes": resp["compact_bytes"]},
            analysis=analysis
        )
        if report_save:
            out = save_report_html(html_str, report_name or "document")
            resp["report_path"] = out
        if report_inline:
            resp["report_html"] = html_str

    return resp
