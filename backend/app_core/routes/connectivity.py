from fastapi import APIRouter, Query
from typing import List, Dict, Any
import os, time, socket, httpx
from urllib.parse import urlparse
import builtins


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

