# backend/app_core/rag/gk_txt.py
from __future__ import annotations
import re
from typing import List, Optional, Tuple
from pathlib import Path
from ..types import IngestItem

# Заголовки
RX_CHAPTER = re.compile(r"^\s*Глава\s+(\d+)\.?\s*(.*)$", re.I)
RX_PARAGRAPH = re.compile(r"^\s*§\s*([0-9]+)\.?\s*(.*)$", re.I)
RX_ARTICLE = re.compile(r"^\s*Статья\s+([0-9]+(?:\.[0-9]+)?)\s*[:.\-–—]?\s*(.*)$", re.I)

# Нумерованные пункты (1., 1), 1.1., 2.3.4. и т.п.)
RX_POINT = re.compile(r"^\s*((?:\d+\.)+\d+|\d+)\s*[).]\s+(.*)$")
RX_POINT_DOT = re.compile(r"^\s*((?:\d+\.)+\d+|\d+)\.\s+(.*)$")

def _norm_text(s: str) -> str:
    # нормализуем переносы/пробелы
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    # убираем BOM, если вдруг
    s = s.lstrip("\ufeff")
    return s

def parse_gk_text(
    text: str,
    part_no: int,
    act_title: Optional[str] = None,
    revision_date: Optional[str] = None,
) -> List[IngestItem]:
    """
    Разбирает plain-text ГК РФ (одна часть) на записи:
      - article: '431.2' и т.п.
      - point: '1', '1.1', ...
      - local_ref: gkrf/p{part_no}/art{article}[/pt{point}]
    Если в статье есть «преамбула» до первого пункта — пишем отдельной записью без point.
    'Глава'/'§' сохраняем только в local_ref (как часть пути) для удобства ссылок.
    """
    text = _norm_text(text)
    lines = [ln.rstrip() for ln in text.split("\n")]

    act_id = f"gk_rf_p{part_no}"
    title = act_title or f"Гражданский кодекс РФ (Часть {part_no})"

    chapter_no: Optional[str] = None
    paragraph_no: Optional[str] = None
    article_no: Optional[str] = None
    point_no: Optional[str] = None

    buf: List[str] = []
    out: List[IngestItem] = []

    def local_ref() -> str:
        parts = [f"gkrf/p{part_no}"]
        if chapter_no: parts.append(f"gl{chapter_no}")
        if paragraph_no: parts.append(f"par{paragraph_no}")
        if article_no: parts.append(f"art{article_no}")
        if point_no: parts.append(f"pt{point_no}")
        return "/".join(parts)

    def flush():
        nonlocal buf, out
        if not buf: return
        body = "\n".join([b for b in (x.strip() for x in buf) if b]).strip()
        if not body:
            buf = []; return
        out.append(IngestItem(
            act_id=act_id,
            act_title=title,
            article=article_no,
            part=None,            # в ГК обычно "пункты", "часть" редко; оставим None
            point=point_no,
            revision_date=revision_date,
            jurisdiction="RU",
            text=body,
            local_ref=local_ref()
        ))
        buf = []

    for raw in lines:
        ln = raw.strip()

        # Пустые строки — как разделители (накапливаем один перенос)
        if not ln:
            if buf and buf[-1] != "":
                buf.append("")
            continue

        # Заголовки верхнего уровня
        m = RX_CHAPTER.match(ln)
        if m:
            flush()
            chapter_no = m.group(1)
            paragraph_no = None  # сбрасываем параграф при смене главы
            # сам заголовок главы не пишем в контент — метаданные хватит
            continue

        m = RX_PARAGRAPH.match(ln)
        if m:
            flush()
            paragraph_no = m.group(1)
            continue

        m = RX_ARTICLE.match(ln)
        if m:
            # новая статья → сбросить предыдущие
            flush()
            article_no = m.group(1)
            point_no = None
            # хвост после заголовка статьи — если есть, написать как текст
            tail = m.group(2).strip()
            if tail:
                buf.append(tail)
            continue

        # Пункты: 1., 1), 1.1., 2.3) и т.п.
        m = RX_POINT.match(ln) or RX_POINT_DOT.match(ln)
        if m and article_no:
            flush()
            point_no = m.group(1)
            tail = m.group(2).strip() if m.lastindex and m.lastindex >= 2 else ""
            if tail:
                buf.append(tail)
            continue

        # Иначе — обычный текст
        buf.append(ln)

    flush()
    return out

def parse_gk_file(path: Path, part_no: int, act_title: Optional[str], revision_date: Optional[str]) -> List[IngestItem]:
    encodings = ("utf-8", "cp1251")
    last_err = None
    for enc in encodings:
        try:
            text = path.read_text(encoding=enc)
            return parse_gk_text(text, part_no=part_no, act_title=act_title, revision_date=revision_date)
        except Exception as e:
            last_err = e
            continue
    raise RuntimeError(f"cannot read {path}: {last_err}")
