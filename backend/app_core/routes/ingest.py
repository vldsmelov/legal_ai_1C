from fastapi import APIRouter, Body, HTTPException
from typing import List
import httpx, socket, asyncio, time
from urllib.parse import urlparse, urlunparse

from ..types import IngestItem, IngestPayload  
from ..config import settings
from ..rag.store import ingest_items, ensure_collection

from ..rag.pub_pravo import parse_publication_html

router = APIRouter(prefix="/rag")

@router.post("/ingest_sample")
def rag_ingest_sample():
    """
    Загружает demo-корпус из corpus/ru_sample.jsonl
    """
    ensure_collection()
    import json, pathlib, hashlib
    p = pathlib.Path("/workspace/corpus/ru_sample.jsonl")
    if not p.exists():
        return {"error": f"not found: {p}"}
    items: List[IngestItem] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        items.append(IngestItem(**d))
    return ingest_items(items)


@router.post("/ingest")
def rag_ingest(payload: IngestPayload):
    ensure_collection()
    return ingest_items(payload.items)

@router.post("/fetch_ingest")
async def rag_fetch_ingest(
    url: str = Body(..., embed=True, description="URL страницы с НПА"),
    max_bytes: int = Body(1_500_000, embed=True),
    timeout: float = Body(12.0, embed=True),
    allow_http_downgrade: bool = Body(True, embed=True),
    max_chunk_chars: int = Body(1800, embed=True),
    chunk_overlap: int = Body(120, embed=True),
    act_title_override: str | None = Body(None, embed=True),
):
    """
    Тянет HTML, парсит в текст, режет на чанки и грузит как временные записи НПА.
    Мета:
      - act_id: <host> (можно уточнить позже)
      - act_title: <title из <title>> или override
      - local_ref: <url>#chunkN
      - jurisdiction: "RU"
    """
    try:
        from ..rag.html_extract import html_to_text, split_into_chunks
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"HTML parser not available: {e}")
  
    t0 = time.time()
    p = urlparse(url)
    if not p.scheme:
        return {"error": "URL должен включать схему http(s)://", "url": url}

    # DNS
    dns_ip = None
    try:
        dns_ip = socket.gethostbyname(p.hostname) if p.hostname else None
    except Exception as e:
        return {"error": f"dns: {e}", "url": url}

    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) LegalAI/0.5 fetch_ingest",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    async def _download(u: str):
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=min(timeout, 5.0), read=timeout)) as client:
            async with client.stream("GET", u, headers=headers, follow_redirects=True) as r:
                total = 0
                chunks = []
                async for c in r.aiter_bytes():
                    if not c: break
                    total += len(c)
                    if total > max_bytes:
                        c = c[: max(0, max_bytes - (total - len(c)))]
                        total = max_bytes
                    chunks.append(c)
                    if total >= max_bytes:
                        break
                body = b"".join(chunks)
                return r, body

    # 1) Пытаемся как есть
    final_url = url
    status = None
    body = b""
    try:
        r, body = await _download(url)
        status = r.status_code
        final_url = str(r.url)
    except httpx.RequestError as e:
        # 2) Если https не даётся — по желанию, пробуем http
        if allow_http_downgrade and p.scheme == "https":
            try:
                p_http = p._replace(scheme="http", netloc=p.netloc)
                url_http = urlunparse(p_http)
                r, body = await _download(url_http)
                status = r.status_code
                final_url = str(r.url)
            except Exception as e2:
                return {"error": f"download: {e} / http-downgrade: {e2}", "url": url}
        else:
            return {"error": f"download: {e}", "url": url}

    if not body or not (200 <= (status or 0) < 400):
        return {"error": f"bad status {status} or empty body", "url": url, "final_url": final_url}

    # 3) Парсим HTML → текст
    try:
        # попытка угадать кодировку по meta уже handled в selectolax достаточно надёжно
        title, plain = html_to_text(body.decode("utf-8", errors="replace"))
    except Exception:
        # fallback без decode — на всякий
        try:
            title, plain = html_to_text(body.decode("cp1251", errors="replace"))
        except Exception as e:
            return {"error": f"parse: {e}", "url": url, "final_url": final_url}

    if act_title_override:
        title = act_title_override

    # Быстрый sanity-check: на порталах часто пустые страницы при блоке/редиректе
    if len(plain) < 200:
        return {
            "warning": "Получен слишком короткий текст (<200 симв.). Возможно, авторизация/JS/редирект.",
            "url": url, "final_url": final_url, "title": title, "size": len(body)
        }

    # 4) Чанкование → IngestItem[]
    chunks = split_into_chunks(plain, max_chars=max_chunk_chars, overlap=chunk_overlap)
    host = (p.hostname or "source").lower()
    act_id = host
    act_title = title or host
    base_ref = final_url

    items: List[IngestItem] = []
    for i, ch in enumerate(chunks, 1):
        items.append(IngestItem(
            act_id=act_id,
            act_title=act_title,
            article=None, part=None, point=None,
            revision_date=None,
            jurisdiction="RU",
            text=ch,
            local_ref=f"{base_ref}#chunk{i}"
        ))

    # 5) Загрузка в Qdrant
    res = ingest_items(items)

    return {
        "ingested": res.get("ingested", len(items)),
        "collection": res.get("collection", settings.QDRANT_COLLECTION),
        "url": url,
        "final_url": final_url,
        "dns_ip": dns_ip,
        "title": act_title,
        "chunks": len(items),
        "size_bytes": len(body),
        "elapsed_ms": int((time.time() - t0)*1000)
    }

async def _download_with_downgrade(url: str, timeout: float, max_bytes: int, allow_http_downgrade: bool):
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) LegalAI/0.6 pravoparser",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=min(timeout,5.0), read=timeout)) as client:
        async def do(u: str):
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
            r, body = await do(url)
            return str(r.url), r.status_code, body, None
        except httpx.RequestError as e:
            p = urlparse(url)
            if allow_http_downgrade and p.scheme == "https":
                try:
                    alt = urlunparse(p._replace(scheme="http"))
                    r, body = await do(alt)
                    return str(r.url), r.status_code, body, None
                except Exception as e2:
                    return None, None, b"", f"download: {e} / http-downgrade: {e2}"
            return None, None, b"", f"download: {e}"

@router.post("/fetch_ingest_publication")
async def rag_fetch_ingest_publication(
    url: str = Body(..., embed=True),
    timeout: float = Body(12.0, embed=True),
    max_bytes: int = Body(1_800_000, embed=True),
    allow_http_downgrade: bool = Body(True, embed=True),
):
    t0 = time.time()
    p = urlparse(url)
    if not p.scheme:
        return {"error": "URL должен быть со схемой http(s)://", "url": url}

    # DNS (для явного репорта)
    try:
        dns_ip = socket.gethostbyname(p.hostname) if p.hostname else None
    except Exception as e:
        return {"error": f"dns: {e}", "url": url}

    final_url, status, body, err = await _download_with_downgrade(url, timeout, max_bytes, allow_http_downgrade)
    if err:
        return {"error": err, "url": url}
    if not body or not status or not (200 <= status < 400):
        return {"error": f"bad status {status} or empty body", "url": url, "final_url": final_url}

    # Декодируем как utf-8 with replace — selectolax сам справится
    html = body.decode("utf-8", errors="replace")

    act_title, revision_date, items = parse_publication_html(html, final_url or url)
    if not items:
        return {"warning": "no-items", "url": url, "final_url": final_url, "title": act_title, "revision_date": revision_date}

    res = ingest_items(items)

    return {
        "ingested": res.get("ingested", len(items)),
        "collection": res.get("collection", settings.QDRANT_COLLECTION),
        "url": url,
        "final_url": final_url,
        "dns_ip": dns_ip,
        "title": act_title,
        "revision_date": revision_date,
        "items": len(items),
        "elapsed_ms": int((time.time() - t0)*1000)
    }

@router.post("/fetch_ingest_publication_batch")
async def rag_fetch_ingest_publication_batch(
    urls: List[str] = Body(..., embed=True),
    timeout: float = Body(12.0, embed=True),
    max_bytes: int = Body(1_800_000, embed=True),
    allow_http_downgrade: bool = Body(True, embed=True),
    concurrency: int = Body(4, embed=True),
):
    sem = asyncio.Semaphore(concurrency)
    out = []
    async def worker(u: str):
        async with sem:
            try:
                res = await rag_fetch_ingest_publication(u, timeout, max_bytes, allow_http_downgrade)  # type: ignore
                out.append({"url": u, "ok": "error" not in res, "result": res})
            except Exception as e:
                out.append({"url": u, "ok": False, "result": {"error": str(e)}})

    await asyncio.gather(*(worker(u) for u in urls))
    ok = sum(1 for r in out if r["ok"])
    return {"total": len(urls), "ok": ok, "items": out}
