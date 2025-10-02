from sentence_transformers import SentenceTransformer
from ..config import settings
from ..utils import pick_device_auto
import torch

_embedder = None

def get_embedder() -> SentenceTransformer:
    global _embedder
    if _embedder is None:
        dev = pick_device_auto(settings.EMBED_DEVICE)
        try:
            _embedder = SentenceTransformer(settings.EMBEDDING_MODEL, device=dev)
            print(f"[RAG] Embedding model on: {dev}")
        except Exception as e:
            print(f"[RAG] GPU init failed ({e}); fallback to CPU")
            _embedder = SentenceTransformer(settings.EMBEDDING_MODEL, device="cpu")
    return _embedder
