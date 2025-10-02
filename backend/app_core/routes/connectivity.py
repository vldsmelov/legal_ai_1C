from fastapi import APIRouter, Query
from typing import List, Dict, Any
import os, time, socket, httpx, builtins, re, secrets
from urllib.parse import urlparse
from pathlib import Path
from hashlib import sha256

router = APIRouter(prefix="/net")

def _default_urls() -> List[str]:
    # Можно переопределить через ENV: NET_TEST_URLS="https://publication.pravo.gov.ru/,https://pravo.gov.ru/"
    env = os.getenv("NET_TEST_URLS", "").strip()
    if env:
        return [u.strip() for u in env.split(",") if u.strip()]
    # Дефолтный набор для РФ (только для сетевой проверки; контент может требовать подписку)
    return [
        "https://publication.pravo.gov.ru/",  # Официальный интернет-портал правовой информации
        "https://pravo.gov.ru/",
        "https://base.garant.ru/",
        "https://www.consultant.ru/"
    ]

async def _probe_one(url: str) -> Dict[str, Any]:
    t0 = time.time()
    host = urlparse(url).hostname or ""
    out: Dict[str, Any] = {"url": url, "host": host, "dns_ip": None, "ok": False}

    # DNS
    try:
        out["dns_ip"] = socket.gethostbyname(host) if host else None
    except Exception as e:
        out["error"] = f"dns: {e}"
        out["elapsed_ms"] = int((time.time() - t0) * 1000)
        return out

    # HTTP HEAD → fallback GET (Range: 0-0) с короткими таймаутами и UA
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) LegalAI/0.5 netcheck",
            "Accept": "*/*",
        }
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=3.0, read=5.0)) as client:
            # Пробуем HEAD
            r = await client.head(url, headers=headers, follow_redirects=True)
            out.update({
                "status": r.status_code,
                "final_url": str(r.url),
                "http_method": "HEAD",
                "ok": (200 <= r.status_code < 400),
            })
            # Если HEAD не прошёл/запрещён — пробуем лёгкий GET с Range
            if r.status_code in (403, 405) or not out["ok"]:
                r = await client.get(url, headers={**headers, "Range": "bytes=0-0"}, follow_redirects=True)
                out.update({
                    "status": r.status_code,
                    "final_url": str(r.url),
                    "http_method": "GET",
                    "ok": (200 <= r.status_code < 400),
                })
    except httpx.RequestError as e:
        out["error"] = f"{e.__class__.__name__}: {e}"
    except Exception as e:
        out["error"] = f"unexpected: {e}"

    out["elapsed_ms"] = int((time.time() - t0) * 1000)
    return out

@router.get("/check")
async def net_check(
    url: str | None = Query(default=None, description="Одноразовая проверка конкретного URL"),
    check_all: bool = Query(default=False, alias="all", description="Проверить дефолтный список")
    ):
    urls = [url] if url else (_default_urls() if check_all or url is None else [])
    if not urls:
        urls = _default_urls()

    results = [await _probe_one(u) for u in urls]

    overall_ok = builtins.all(r.get("ok", False) for r in results) if results else False
    summary = {
        "ok": overall_ok,
        "checked": len(results),
        "reachable": sum(1 for r in results if r.get("ok")),
    }
    return {"summary": summary, "results": results}

# ===== /net/fetch — стримим HTML/текст и сохраняем в кэш =====

def _detect_charset(content_type: str | None) -> str | None:
    if not content_type:
        return None
    m = re.search(r"charset=([\w\-]+)", content_type, re.I)
    return (m.group(1) if m else None)

def _safe_path_for(url: str) -> Path:
    p = urlparse(url)
    host = (p.hostname or "unknown").lower()
    base = f"{int(time.time())}_{secrets.token_hex(4)}"
    ext = ".bin"
    if (p.path or "").lower().endswith((".html", ".htm")):
        ext = ".html"
    out_dir = Path("/workspace/.net_cache") / host
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / f"{base}{ext}"

@router.get("/fetch")
async def net_fetch(
    url: str = Query(..., description="URL для скачивания"),
    max_bytes: int = Query(1_500_000, ge=1024, le=50_000_000, description="Ограничение размера (байт)"),
    timeout: float = Query(10.0, ge=1.0, le=60.0),
    save: bool = Query(True, description="Сохранить сырой ответ в .net_cache")
):
    t0 = time.time()
    p = urlparse(url)
    host = p.hostname or ""
    result: Dict[str, Any] = {
        "url": url,
        "host": host,
        "final_url": None,
        "status": None,
        "ok": False,
        "sha256": None,
        "bytes": 0,
        "content_type": None,
        "charset": None,
        "server": None,
        "saved_path": None,
        "preview_text": None,
    }

    # DNS
    try:
        dns_ip = socket.gethostbyname(host) if host else None
        result["dns_ip"] = dns_ip
    except Exception as e:
        result["error"] = f"dns: {e}"
        result["elapsed_ms"] = int((time.time() - t0) * 1000)
        return result

    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) LegalAI/0.5 fetch",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=min(5.0, timeout), read=timeout)) as client:
            # Стримовый GET с ограничением размера
            async with client.stream("GET", url, headers=headers, follow_redirects=True) as r:
                result["status"] = r.status_code
                result["final_url"] = str(r.url)
                result["content_type"] = r.headers.get("content-type")
                result["server"] = r.headers.get("server")
                result["charset"] = _detect_charset(result["content_type"])

                hasher = sha256()
                total = 0
                chunks: list[bytes] = []
                async for chunk in r.aiter_bytes():
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_bytes:
                        # Обрезаем, но сохраняем уже скачанное
                        chunk = chunk[: max(0, max_bytes - (total - len(chunk)))]
                        total = max_bytes
                    hasher.update(chunk)
                    chunks.append(chunk)
                    if total >= max_bytes:
                        break

                body = b"".join(chunks)
                result["bytes"] = len(body)
                result["sha256"] = hasher.hexdigest()
                result["ok"] = (200 <= r.status_code < 400) and result["bytes"] > 0

                # Превью текста (если HTML/текст)
                ct = (result["content_type"] or "").lower()
                if "text/html" in ct or ct.startswith("text/"):
                    enc = result["charset"] or "utf-8"
                    try:
                        text = body.decode(enc, errors="replace")
                    except Exception:
                        text = body.decode("utf-8", errors="replace")
                    # вырежем кусочек для превью
                    result["preview_text"] = re.sub(r"\s+", " ", text)[:2000]  # 2K символов

                # Сохранить в кэш (для отладки)
                if save and result["bytes"] > 0:
                    path = _safe_path_for(url)
                    path.write_bytes(body)
                    result["saved_path"] = str(path)

    except httpx.RequestError as e:
        result["error"] = f"{e.__class__.__name__}: {e}"
    except Exception as e:
        result["error"] = f"unexpected: {e}"

    result["elapsed_ms"] = int((time.time() - t0) * 1000)
    return result