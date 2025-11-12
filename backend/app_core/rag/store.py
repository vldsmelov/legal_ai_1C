import json
from pathlib import Path
from typing import List, Dict, Any

import numpy as np

try:  # pragma: no cover - optional dependency
    from qdrant_client import QdrantClient  # type: ignore
    from qdrant_client.models import VectorParams, Distance, PointStruct, Filter, FieldCondition, MatchValue
except Exception:  # noqa: S110
    QdrantClient = None  # type: ignore
    VectorParams = Distance = PointStruct = Filter = FieldCondition = MatchValue = None  # type: ignore

from .embedder import get_embedder
from .pdf_loader import pdf_to_ingest_items, PdfLoaderUnavailable
from ..types import IngestItem, SourceItem
from ..config import settings
from ..utils import deterministic_point_id, text_hash

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

def ensure_collection():
    client = get_qdrant()
    names = [c.name for c in client.get_collections().collections]
    if settings.QDRANT_COLLECTION not in names:
        try:
            client.create_collection(
                collection_name=settings.QDRANT_COLLECTION,
                vectors=VectorParams(size=1024, distance=Distance.COSINE),
            )
        except AssertionError:
            client.create_collection(
                collection_name=settings.QDRANT_COLLECTION,
                vectors_config=VectorParams(size=1024, distance=Distance.COSINE),
            )

def ingest_items(items: List[IngestItem]):
    _require_qdrant()
    emb = get_embedder()
    client = get_qdrant()
    texts = [it.text for it in items]
    vecs = emb.encode(texts, normalize_embeddings=True)
    vectors = [np.asarray(v, dtype=np.float32).tolist() for v in vecs]
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
        ensure_collection()
    except RuntimeError:
        return []
    emb = get_embedder()
    client = get_qdrant()
    qv = emb.encode([query], normalize_embeddings=True)[0].astype(np.float32).tolist()
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

    path = Path("/workspace/corpus/ru_sample.jsonl")
    if not path.exists():
        raise FileNotFoundError("Файл corpus/ru_sample.jsonl не найден")

    items: List[IngestItem] = []
    jsonl_records = 0
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            items.append(IngestItem(**data))
            jsonl_records += 1

    pdf_dir = Path("/workspace/corpus/Законодательные акты")
    pdf_files = 0
    pdf_chunks = 0
    pdf_errors: List[Dict[str, Any]] = []
    if pdf_dir.exists():
        pdf_paths = sorted(pdf_dir.rglob("*.pdf"))
        for pdf_path in pdf_paths:
            try:
                pdf_items = pdf_to_ingest_items(pdf_path)
            except PdfLoaderUnavailable as exc:
                pdf_errors.append({"file": str(pdf_path), "error": str(exc)})
                break
            except Exception as exc:  # noqa: BLE001 - логируем и продолжаем
                pdf_errors.append({"file": str(pdf_path), "error": str(exc)})
                continue
            if not pdf_items:
                continue
            items.extend(pdf_items)
            pdf_files += 1
            pdf_chunks += len(pdf_items)

    res = ingest_items(items)
    res.update({
        "jsonl_records": jsonl_records,
        "pdf_files": pdf_files,
        "pdf_chunks": pdf_chunks,
    })
    if pdf_errors:
        res["pdf_errors"] = pdf_errors
    return res
