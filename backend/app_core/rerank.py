from typing import List
from .config import settings
from .types import SourceItem
from .utils import pick_device_auto
import torch

_reranker = None

def get_reranker():
    global _reranker
    if _reranker is None:
        from FlagEmbedding import FlagReranker
        device = pick_device_auto(settings.RERANK_DEVICE)
        try:
            _reranker = FlagReranker(settings.RERANKER_MODEL, use_fp16=(device=="cuda"), device=device)
            print(f"[RERANK] loaded on: {device}")
        except Exception as e:
            print(f"[RERANK] load failed on {device} ({e}); fallback CPU")
            _reranker = FlagReranker(settings.RERANKER_MODEL, use_fp16=False, device="cpu")
    return _reranker

def apply_rerank(query: str, sources: List[SourceItem], keep: int) -> List[SourceItem]:
    if not settings.RERANK_ENABLE or len(sources) <= keep:
        return sources[:keep]
    rr = get_reranker()
    pairs = [(query, s.text[:4000]) for s in sources]
    scores = rr.compute_score(pairs, batch_size=settings.RERANK_BATCH)
    ranked = sorted(zip(sources, scores), key=lambda x: x[1], reverse=True)
    if settings.RERANK_DEBUG:
        print("[RERANK] scores:", [round(sc,3) for _, sc in ranked])
    return [s for (s, sc) in ranked[:keep]]
