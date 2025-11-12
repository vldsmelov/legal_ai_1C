from typing import Any, Dict, Tuple

import httpx

from ..config import settings
from ..utils import extract_json

async def ollama_chat_json(
    system_msg: str,
    user_msg: str,
    model: str | None,
    max_tokens: int = 1024,
) -> Tuple[Dict[str, Any], str, Dict[str, Any]]:
    payload = {
        "model": model or settings.OLLAMA_MODEL,
        "messages": [{"role": "system", "content": system_msg},
                     {"role": "user", "content": user_msg}],
        "stream": False,
        "options": {"temperature": 0.2, "num_predict": max_tokens},
        "format": "json",
    }
    chat_url = f"{settings.OLLAMA_URL}/api/chat"
    async with httpx.AsyncClient(timeout=180.0) as client:
        r = await client.post(chat_url, json=payload)
        r.raise_for_status()
        data = r.json()
    txt = (data.get("message") or {}).get("content") or data.get("response") or ""
    parsed = extract_json(txt) or {}
    if parsed:
        return parsed, txt, {"endpoint": "chat", "url": chat_url}
    # fallback
    g_payload = {
        "model": model or settings.OLLAMA_MODEL,
        "prompt": f"{system_msg}\n\n{user_msg}",
        "stream": False,
        "options": {"temperature": 0.2, "num_predict": max_tokens},
        "format": "json",
    }
    generate_url = f"{settings.OLLAMA_URL}/api/generate"
    async with httpx.AsyncClient(timeout=180.0) as client:
        r = await client.post(generate_url, json=g_payload)
        r.raise_for_status()
        g_data = r.json()
    raw = g_data.get("response", "")
    return extract_json(raw) or {}, raw, {"endpoint": "generate", "url": generate_url}

async def ollama_generate(prompt: str, max_tokens: int = 512, model: str | None = None):
    payload = {
        "model": model or settings.OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.2, "num_predict": max_tokens},
    }
    async with httpx.AsyncClient(timeout=180.0) as client:
        r = await client.post(f"{settings.OLLAMA_URL}/api/generate", json=payload)
        r.raise_for_status()
        return r.json().get("response", "")
