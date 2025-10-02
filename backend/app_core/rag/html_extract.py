from selectolax.parser import HTMLParser
from typing import List, Tuple, Optional
import re

def _clean_tree(tree: HTMLParser) -> None:
    for css in ["script", "style", "noscript", "template", "iframe", "svg"]:
        for n in tree.css(css):
            n.decompose()

def _get_title(tree: HTMLParser) -> str:
    t = tree.css_first("title")
    if not t:
        return ""
    title = t.text(strip=True)
    title = re.sub(r"\s+", " ", title).strip()
    return title[:300]

def _pick_main(tree: HTMLParser):
    # эвристика: берём самый “текстонасыщенный” контейнер
    candidates = []
    for sel in ["article", "main", '[role="main"]',
                ".content", ".content__inner", ".page-content",
                ".document", ".doc", ".law", "body"]:
        for n in tree.css(sel):
            txt = n.text(separator="\n", strip=True)
            candidates.append((len(txt), n))
    if not candidates:
        return tree.body or tree
    return sorted(candidates, key=lambda x: x[0], reverse=True)[0][1]

def _node_to_text(n) -> str:
    # собираем параграфы/списки/заголовки с перевodами строк
    parts: List[str] = []
    for el in n.css("h1,h2,h3,h4,h5,h6,p,li,pre,blockquote"):
        t = el.text(separator=" ", strip=True)
        t = re.sub(r"\s+", " ", t)
        if not t:
            continue
        # лёгкая заметка заголовков
        if el.tag in ("h1","h2","h3","h4","h5","h6"):
            t = f"\n{t}\n"
        parts.append(t)
    text = "\n".join(parts)
    # общее подчистить
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text

def html_to_text(html: str) -> Tuple[str, str]:
    tree = HTMLParser(html)
    _clean_tree(tree)
    title = _get_title(tree)
    main = _pick_main(tree)
    text = _node_to_text(main)
    return title, text

def split_into_chunks(text: str, max_chars: int = 1800, overlap: int = 120) -> List[str]:
    if len(text) <= max_chars:
        return [text]
    # режем по абзацам/пустым строкам
    paras = re.split(r"\n{2,}", text)
    chunks: List[str] = []
    cur: List[str] = []
    cur_len = 0
    for p in paras:
        p = p.strip()
        if not p:
            continue
        if cur_len + len(p) + 2 > max_chars and cur:
            chunks.append("\n\n".join(cur))
            # оверлап — берём хвост прошлого чанка
            tail = chunks[-1]
            tail_tail = tail[-overlap:]
            cur = [tail_tail, p] if overlap > 0 else [p]
            cur_len = sum(len(x) for x in cur) + 2
        else:
            cur.append(p)
            cur_len += len(p) + 2
    if cur:
        chunks.append("\n\n".join(cur))
    return chunks
