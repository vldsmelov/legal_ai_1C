from __future__ import annotations
from selectolax.parser import HTMLParser
from typing import List, Tuple, Optional
import re, hashlib
from urllib.parse import urlparse

from ..types import IngestItem

RX_ART = re.compile(r"^\s*(Статья|Ст.\s*)\s*([0-9]+(?:\.[0-9]+)?)\s*\.?\s*(.*)$", re.I)
RX_PART = re.compile(r"^\s*(Часть|Ч\.)\s*([0-9]+)\s*\.?\s*(.*)$", re.I)
RX_POINT = re.compile(r"^\s*(Пункт|П\.)\s*([0-9]+)\s*\.?\s*(.*)$", re.I)

RX_DATE_META = re.compile(r"(\d{4}-\d{2}-\d{2})")
RX_DATE_DMY = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})")
RX_EDIT = re.compile(r"(редакц(ия|ии)\s*от\s*(\d{1,2}\.\d{1,2}\.\d{4}))", re.I)

BLOCK_SELECTOR = "h1,h2,h3,h4,h5,h6,p,li,blockquote,pre"

def _clean_tree(tree: HTMLParser) -> None:
    for css in ["script","style","noscript","template","iframe","svg"]:
        for n in tree.css(css): n.decompose()

def _text(node) -> str:
    t = node.text(separator=" ", strip=True)
    t = re.sub(r"\s+", " ", t).strip()
    return t

def _pick_main(tree: HTMLParser):
    # Пробуем несколько характерных контейнеров; fallback — <body>
    selectors = [
        "article", "main", '[role="main"]',
        ".content", ".content__inner", ".page-content",
        ".document", ".doc", ".law", ".publication",
        "#content", "body"
    ]
    cand = []
    for sel in selectors:
        for n in tree.css(sel):
            size = len(n.text(separator=" ", strip=True))
            cand.append((size, n))
    cand.sort(key=lambda x: x[0], reverse=True)
    return cand[0][1] if cand else (tree.body or tree)

def _title(tree: HTMLParser, main) -> str:
    # 1) <title>
    t = tree.css_first("title")
    if t:
        val = _text(t)
        if val: return val[:300]
    # 2) h1 в main
    h1 = main.css_first("h1")
    if h1:
        val = _text(h1)
        if val: return val[:300]
    return ""

def _extract_revision(tree: HTMLParser, main) -> Optional[str]:
    # meta[name=date] / meta[property=article:published_time]
    for name in ["date","last-modified","dcterms.date","revision-date"]:
        m = tree.css_first(f'meta[name="{name}"]')
        if m:
            c = m.attributes.get("content","")
            m2 = RX_DATE_META.search(c)
            if m2: return m2.group(1)
    m = tree.css_first('meta[property="article:published_time"]')
    if m:
        c = m.attributes.get("content","")
        m2 = RX_DATE_META.search(c)
        if m2: return m2.group(1)
    # поиск «редакция от DD.MM.YYYY» в тексте
    txt = main.text(separator=" ", strip=True)
    m3 = RX_EDIT.search(txt) or RX_DATE_DMY.search(txt)
    if m3:
        dd, mm, yyyy = None, None, None
        if len(m3.groups()) >= 3 and m3.re is RX_EDIT or m3.re is RX_DATE_DMY:
            # обе регулярки отдают dd.mm.yyyy где-то в группах
            g = m3.groups()[-3:]  # dd, mm, yyyy
            dd, mm, yyyy = g
            dd = dd.zfill(2); mm = mm.zfill(2)
            return f"{yyyy}-{mm}-{dd}"
    return None

def _act_id_from_url(base_url: str) -> str:
    # стабильный ID по URL (короткий sha1)
    h = hashlib.sha1(base_url.encode("utf-8")).hexdigest()[:12]
    return f"pravo_pub:{h}"

def _local_ref(base_url: str, art: Optional[str], part: Optional[str], point: Optional[str]) -> str:
    suffix = []
    if art: suffix.append(f"art{art}")
    if part: suffix.append(f"ch{part}")
    if point: suffix.append(f"pt{point}")
    if suffix:
        return f"{base_url}#" + "/".join(suffix)
    return base_url + "#chunk"

def parse_publication_html(html: str, base_url: str) -> Tuple[str, Optional[str], List[IngestItem]]:
    """
    Возвращает (act_title, revision_date, items[])
    items: IngestItem с заполненными article/part/point и локальной ссылкой.
    Fallback: если структура не найдена — один-два больших чанка без article/part/point.
    """
    tree = HTMLParser(html)
    _clean_tree(tree)
    main = _pick_main(tree)

    act_title = _title(tree, main)
    revision_date = _extract_revision(tree, main)
    act_id = _act_id_from_url(base_url)

    cur_art: Optional[str] = None
    cur_part: Optional[str] = None
    cur_point: Optional[str] = None

    buf: List[str] = []
    items: List[IngestItem] = []

    def flush():
        nonlocal buf, items, cur_art, cur_part, cur_point
        if not buf: return
        text = "\n".join(buf).strip()
        if not text: 
            buf = []; return
        items.append(IngestItem(
            act_id=act_id,
            act_title=act_title or urlparse(base_url).hostname or "Публикация",
            article=cur_art, part=cur_part, point=cur_point,
            revision_date=revision_date,
            jurisdiction="RU",
            text=text,
            local_ref=_local_ref(base_url, cur_art, cur_part, cur_point)
        ))
        buf = []

    for el in main.css(BLOCK_SELECTOR):
        t = _text(el)
        if not t:
            continue

        # Заголовки могут переключать уровни
        if el.tag in ("h1","h2","h3","h4","h5","h6"):
            m = RX_ART.match(t)
            if m:
                flush()
                cur_art = m.group(2)
                # при смене статьи — сбрасываем часть/пункт
                cur_part = None; cur_point = None
                # можно сохранить название статьи (m.group(3)), но пока не используем
                continue
            m = RX_PART.match(t)
            if m:
                flush()
                cur_part = m.group(2)
                # при смене части — сбрасываем пункт
                cur_point = None
                continue
            m = RX_POINT.match(t)
            if m:
                flush()
                cur_point = m.group(2)
                continue
            # иначе — это произвольный заголовок, считаем его частью контента
            buf.append(t)
            continue

        # Обычный текстовый блок — проверим, не начинается ли он с маркера
        m = RX_ART.match(t)
        if m:
            flush()
            cur_art = m.group(2); cur_part = None; cur_point = None
            # остальную строку (после заголовка) можно добавить как текст
            tail = m.group(3).strip() if m.group(3) else ""
            if tail: buf.append(tail)
            continue

        m = RX_PART.match(t)
        if m:
            flush()
            cur_part = m.group(2); cur_point = None
            tail = m.group(3).strip() if m.group(3) else ""
            if tail: buf.append(tail)
            continue

        m = RX_POINT.match(t)
        if m:
            flush()
            cur_point = m.group(2)
            tail = m.group(3).strip() if m.group(3) else ""
            if tail: buf.append(tail)
            continue

        # Обычный параграф
        buf.append(t)

    flush()

    # Fallback: если распознать структуру не вышло, но текст есть — нарежем крупно
    if not items and buf:
        full = "\n".join(buf)
        chunks = _chunks_fallback(full, max_chars=1800, overlap=120)
        for i, ch in enumerate(chunks, 1):
            items.append(IngestItem(
                act_id=act_id,
                act_title=act_title or urlparse(base_url).hostname or "Публикация",
                article=None, part=None, point=None,
                revision_date=revision_date,
                jurisdiction="RU",
                text=ch,
                local_ref=f"{base_url}#chunk{i}"
            ))

    return act_title, revision_date, items

def _chunks_fallback(text: str, max_chars: int = 1800, overlap: int = 120) -> List[str]:
    if len(text) <= max_chars:
        return [text]
    paras = re.split(r"\n{2,}", text)
    out, cur = [], []
    cur_len = 0
    for p in paras:
        p = p.strip()
        if not p: continue
        if cur_len + len(p) + 2 > max_chars and cur:
            out.append("\n\n".join(cur))
            tail = out[-1][-overlap:] if overlap > 0 else ""
            cur = [tail, p] if tail else [p]
            cur_len = sum(len(x) for x in cur) + 2
        else:
            cur.append(p)
            cur_len += len(p) + 2
    if cur: out.append("\n\n".join(cur))
    return out
