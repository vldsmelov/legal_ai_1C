from fastapi import FastAPI
import asyncio
import httpx

from .config import settings

def register_startup(app: FastAPI):
    @app.on_event("startup")
    async def startup_checks():
        if not settings.STARTUP_CHECKS:
            print("=== [startup] checks skipped by env ===")
            return
        print("=== [startup] checks begin (light) ===")

        # Ollama
        ok_ollama = False
        for _ in range(settings.SELF_CHECK_TIMEOUT):
            try:
                async with httpx.AsyncClient(timeout=2.0) as client:
                    r = await client.get(f"{settings.OLLAMA_URL}/api/tags")
                    if r.status_code == 200:
                        ok_ollama = True
                        models = [m["name"] for m in r.json().get("models", [])]
                        print(f"[startup] ollama UP, models: {models[:3]}{'...' if len(models)>3 else ''}")
                        break
            except Exception:
                pass
            await asyncio.sleep(1)
        if not ok_ollama:
            print("[startup] WARNING: ollama not reachable")

        # Qdrant
        ok_qdrant = False
        for _ in range(settings.SELF_CHECK_TIMEOUT):
            try:
                async with httpx.AsyncClient(timeout=2.0) as client:
                    r = await client.get(f"{settings.QDRANT_URL}/collections")
                    if r.status_code == 200:
                        ok_qdrant = True
                        names = [c["name"] for c in r.json().get("collections", [])]
                        print(f"[startup] qdrant UP, collections: {names}")
                        break
            except Exception:
                pass
            await asyncio.sleep(1)
        if not ok_qdrant:
            print("[startup] WARNING: qdrant not reachable")

        # Тест-генерация (по флагу)
        if ok_ollama and settings.SELF_CHECK_GEN:
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    payload = {"model": settings.OLLAMA_MODEL, "prompt": "ping", "stream": False, "options": {"num_predict": 4}}
                    r = await client.post(f"{settings.OLLAMA_URL}/api/generate", json=payload)
                    print("[startup] ollama test generate:", "OK" if r.status_code == 200 else f"FAIL {r.status_code}")
            except Exception as e:
                print(f"[startup] ollama test generate error: {e}")

        print("=== [startup] checks end ===")
