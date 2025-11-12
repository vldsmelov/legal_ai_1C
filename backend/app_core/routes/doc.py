# backend/app_core/routes/doc.py
from __future__ import annotations
from fastapi import APIRouter, Body, UploadFile, File, Form, HTTPException
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any
import httpx, re

from ..paths import LOCAL_FILES_BASE, resolve_under


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

def _decode_bytes(data: bytes) -> str:
    for enc in ("utf-8", "cp1251"):
        try:
            return data.decode(enc)
        except Exception:
            continue
    return data.decode(errors="ignore")


def _read_text_file(path: Path) -> str:
    for enc in ("utf-8", "cp1251"):
        try:
            return path.read_text(encoding=enc)
        except Exception:
            continue
    # как крайний случай — без указания кодировки
    return path.read_text(errors="ignore")


async def _analyze_raw_text(
    raw: str,
    source_label: str,
    jurisdiction: str,
    contract_type: str,
    language: str,
    max_tokens: int,
    per_section_limit: int,
    total_limit: int,
    report_format: str | None,
    report_save: bool,
    report_inline: bool,
    report_name: str | None,
):
    sections = extract_sections(raw)
    compact = build_compact(
        sections,
        per_section_limit=per_section_limit,
        total_limit=total_limit,
    )
    analysis = await _call_analyze(
        compact,
        jurisdiction,
        contract_type,
        language,
        max_tokens,
        report_format,
        report_save,
        report_inline,
        report_name,
        {
            "source_path": source_label,
            "compact_preview": compact,
            "original_bytes": len(raw.encode("utf-8", errors="ignore")),
            "compact_bytes": len(compact.encode("utf-8", errors="ignore")),
        },
    )

    resp = {
        "source_path": source_label,
        "original_bytes": len(raw.encode("utf-8", errors="ignore")),
        "compact_bytes": len(compact.encode("utf-8", errors="ignore")),
        "compact_preview": compact[:800],
        "analysis": analysis,
    }

    if analysis.get("report_path"):
        resp["report_path"] = analysis["report_path"]

    return resp

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



async def _call_analyze(
    compact_text: str,
    jurisdiction: str,
    contract_type: str,
    language: str,
    max_tokens: int,
    report_format: str | None,
    report_save: bool,
    report_inline: bool,
    report_name: str | None,
    report_meta: Optional[Dict[str, Any]] = None,
) -> dict:
    payload: Dict[str, Any] = {
        "contract_text": compact_text,
        "jurisdiction": jurisdiction,
        "contract_type": contract_type,
        "language": language,
        "max_tokens": max_tokens,
    }
    if report_format:
        payload["report_format"] = report_format
    if report_name:
        payload["report_name"] = report_name
    if report_meta:
        payload["report_meta"] = report_meta
    # Большой таймаут на чтение/запись для больших документов
    timeout = httpx.Timeout(connect=5.0, read=300.0, write=300.0, pool=300.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post("http://127.0.0.1:8087/analyze", json=payload)
        r.raise_for_status()
        return r.json()


# ----------- эндпоинты ------------

@router.post("/analyze_file")
async def analyze_file(
    path: str = Body(
        ...,
        embed=True,
        description="Путь к файлу относительно LEGAL_AI_LOCAL_BASE (по умолчанию корень проекта)",
    ),
    jurisdiction: str = Body("RU", embed=True),
    contract_type: str = Body("услуги", embed=True),
    language: str = Body("ru", embed=True),
    max_tokens: int = Body(600, embed=True),
    per_section_limit: int = Body(2200, embed=True),
    total_limit: int = Body(20000, embed=True),
    report_format: str | None = Body(None, embed=True, description="html | null"),
    report_save: bool = Body(
        True, embed=True, description="[устарело] HTML всегда сохраняется"
    ),
    report_inline: bool = Body(
        False,
        embed=True,
        description="[устарело] HTML возвращается только ссылкой",
    ),
    report_name: str | None = Body(None, embed=True),
):
    try:
        p = resolve_under(LOCAL_FILES_BASE, path)
    except ValueError as exc:
        return {"error": str(exc)}
    if not p.exists():
        return {"error": f"file not found: {p}"}
    raw = _read_text_file(p)
    return await _analyze_raw_text(
        raw,
        str(p),
        jurisdiction,
        contract_type,
        language,
        max_tokens,
        per_section_limit,
        total_limit,
        report_format,
        report_save,
        report_inline,
        report_name or Path(path).stem,
    )


@router.post("/analyze_upload")
async def analyze_upload(
    file: UploadFile = File(..., description="Документ для анализа"),
    jurisdiction: str = Form("RU"),
    contract_type: str = Form("услуги"),
    language: str = Form("ru"),
    max_tokens: int = Form(600),
    per_section_limit: int = Form(2200),
    total_limit: int = Form(20000),
    report_format: str | None = Form(None, description="html | null"),
    report_save: bool = Form(True, description="[устарело] HTML всегда сохраняется"),
    report_inline: bool = Form(
        False, description="[устарело] HTML возвращается только ссылкой"
    ),
    report_name: str | None = Form(None),
):
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="empty upload")

    raw = _decode_bytes(data)
    source_label = file.filename or "uploaded"

    return await _analyze_raw_text(
        raw,
        source_label,
        jurisdiction,
        contract_type,
        language,
        max_tokens,
        per_section_limit,
        total_limit,
        report_format,
        report_save,
        report_inline,
        report_name or Path(source_label).stem,
    )

