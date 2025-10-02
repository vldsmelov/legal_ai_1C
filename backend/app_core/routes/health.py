from fastapi import APIRouter
import httpx
from ..config import settings
from ..rag.store import get_qdrant
router = APIRouter()

@router.get("/health")
async def health():
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(f"{settings.OLLAMA_URL}/api/tags")
            ollama_ok = (r.status_code == 200)
            installed = [m["name"] for m in r.json().get("models", [])] if ollama_ok else []
    except Exception:
        ollama_ok, installed = False, []

    try:
        client = get_qdrant()
        cols = client.get_collections().collections
        qdrant_ok = True
        has_ru = any(c.name == settings.QDRANT_COLLECTION for c in cols)
    except Exception:
        qdrant_ok, has_ru = False, False

    return {
        "status": "ok",
        "ollama": "up" if ollama_ok else "down",
        "ollama_url": settings.OLLAMA_URL,
        "installed_models": installed,
        "qdrant": "up" if qdrant_ok else "down",
        "qdrant_collection": settings.QDRANT_COLLECTION,
        "ru_collection_present": has_ru,
        "reranker": "on" if settings.RERANK_ENABLE else "off",
    }
