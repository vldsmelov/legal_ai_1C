try:  # pragma: no cover - optional dependency
    from sentence_transformers import SentenceTransformer  # type: ignore
except Exception:  # noqa: S110
    SentenceTransformer = None  # type: ignore

from ..config import settings
from ..utils import pick_device_auto

try:  # pragma: no cover
    import torch  # type: ignore
except Exception:  # noqa: S110
    torch = None

_embedder = None

def get_embedder() -> SentenceTransformer:
    global _embedder
    if SentenceTransformer is None:
        raise RuntimeError("sentence-transformers is not installed")
    if _embedder is None:
        dev = pick_device_auto(settings.EMBED_DEVICE)
        try:
            _embedder = SentenceTransformer(settings.EMBEDDING_MODEL, device=dev)
            print(f"[RAG] Embedding model on: {dev}")
        except Exception as e:
            print(f"[RAG] GPU init failed ({e}); fallback to CPU")
            _embedder = SentenceTransformer(settings.EMBEDDING_MODEL, device="cpu")
    return _embedder
