import json
from typing import List, Optional

try:  # pragma: no cover - optional dependency
    from qdrant_client import QdrantClient  # type: ignore
    from qdrant_client.models import VectorParams, Distance, PointStruct, Filter, FieldCondition, MatchValue
except Exception:  # noqa: S110
    QdrantClient = None  # type: ignore
    VectorParams = Distance = PointStruct = Filter = FieldCondition = MatchValue = None  # type: ignore

from .embedder import embed_texts, get_vector_size
from ..types import IngestItem, SourceItem
from ..config import settings
from ..utils import deterministic_point_id, text_hash
from ..paths import CORPUS_DIR

_qdrant = None

def _require_qdrant() -> None:
    if QdrantClient is None:
        raise RuntimeError("qdrant-client is not installed")


def get_qdrant() -> QdrantClient:
    _require_qdrant()
    global _qdrant
    if _qdrant is None:
        _qdrant = QdrantClient(url=settings.QDRANT_URL, timeout=2.0)
    return _qdrant

def _collection_vector_size(info) -> Optional[int]:  # pragma: no cover - qdrant schema helper
    try:
        params = getattr(info.config, "params", None)
        vectors = getattr(params, "vectors", None)
        if hasattr(vectors, "size"):
            return int(vectors.size)
        if isinstance(vectors, dict) and vectors:
            first = next(iter(vectors.values()))
            if hasattr(first, "size"):
                return int(first.size)
    except Exception:
        return None
    return None


def ensure_collection(expected_size: Optional[int] = None):
    client = get_qdrant()
    names = [c.name for c in client.get_collections().collections]
    if settings.QDRANT_COLLECTION not in names:
        dim = expected_size or get_vector_size()
        params = VectorParams(size=dim, distance=Distance.COSINE)
        try:
            client.create_collection(
                collection_name=settings.QDRANT_COLLECTION,
                vectors=params,
            )
        except AssertionError:
            client.create_collection(
                collection_name=settings.QDRANT_COLLECTION,
                vectors_config=params,
            )
        return

    if expected_size is None:
        return

    try:
        info = client.get_collection(settings.QDRANT_COLLECTION)
    except Exception:
        return
    current_size = _collection_vector_size(info)
    if current_size and current_size != expected_size:
        raise RuntimeError(
            f"Qdrant collection '{settings.QDRANT_COLLECTION}' expects vectors of size {current_size},"
            f" but got {expected_size}"
        )

def ingest_items(items: List[IngestItem]):
    _require_qdrant()
    client = get_qdrant()
    texts = [it.text for it in items]
    vectors = embed_texts(texts)
    if not vectors:
        return {"ingested": 0, "collection": settings.QDRANT_COLLECTION}
    ensure_collection(len(vectors[0]))
    points = []
    for i, it in enumerate(items):
        payload = it.dict()
        payload["source_hash"] = text_hash(it.text)
        key = it.local_ref or it.text
        pid = deterministic_point_id(key)
        points.append(PointStruct(id=pid, vector=vectors[i], payload=payload))
    client.upsert(collection_name=settings.QDRANT_COLLECTION, points=points)
    return {"ingested": len(points), "collection": settings.QDRANT_COLLECTION}

def rag_search_ru(query: str, top_k: int = 8) -> List[SourceItem]:
    try:
        query_vec = embed_texts([query])
    except RuntimeError:
        return []
    if not query_vec:
        return []
    try:
        ensure_collection(len(query_vec[0]))
    except RuntimeError:
        return []
    client = get_qdrant()
    qv = query_vec[0]
    flt = Filter(must=[FieldCondition(key="jurisdiction", match=MatchValue(value="RU"))])
    res = client.search(collection_name=settings.QDRANT_COLLECTION, query_vector=qv, limit=top_k, query_filter=flt)
    out: List[SourceItem] = []
    for r in res:
        p = r.payload or {}
        out.append(SourceItem(
            act_title=p.get("act_title", ""), article=p.get("article"), part=p.get("part"),
            point=p.get("point"), revision_date=p.get("revision_date"),
            jurisdiction=p.get("jurisdiction", "RU"), text=p.get("text", ""),
            local_ref=p.get("local_ref"), source_hash=p.get("source_hash",""),
        ))
    return out

def ingest_sample_from_file():
    ensure_collection()
    path = CORPUS_DIR / "ru_sample.jsonl"
    if not path.exists():
        raise FileNotFoundError("Файл corpus/ru_sample.jsonl не найден")
    items: List[IngestItem] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line: continue
            data = json.loads(line)
            items.append(IngestItem(**data))
    return ingest_items(items)
