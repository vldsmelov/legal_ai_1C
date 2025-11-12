from __future__ import annotations

import math
from functools import lru_cache
from typing import Iterable, List

import httpx

from ..config import settings


class EmbeddingError(RuntimeError):
    """Raised when embedding service returns an unexpected payload."""


def _normalize(vector: Iterable[float]) -> List[float]:
    values = [float(v) for v in vector]
    norm = math.sqrt(sum(v * v for v in values))
    if norm == 0.0:
        return values
    return [v / norm for v in values]


def embed_texts(texts: List[str]) -> List[List[float]]:
    if not texts:
        return []
    url = f"{settings.OLLAMA_URL.rstrip('/')}/api/embeddings"
    payload_model = settings.EMBEDDING_MODEL
    vectors: List[List[float]] = []
    with httpx.Client(timeout=60.0) as client:
        for text in texts:
            response = client.post(url, json={"model": payload_model, "prompt": text})
            response.raise_for_status()
            data = response.json()
            embedding = data.get("embedding")
            if not isinstance(embedding, list):
                raise EmbeddingError("Ollama returned invalid embedding payload")
            vectors.append(_normalize(embedding))
    return vectors


@lru_cache(maxsize=1)
def get_vector_size() -> int:
    probe = embed_texts(["dimension probe"])
    if not probe or not probe[0]:
        raise EmbeddingError("Failed to determine embedding vector size")
    return len(probe[0])
