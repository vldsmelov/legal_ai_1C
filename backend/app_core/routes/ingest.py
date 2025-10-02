from fastapi import APIRouter, HTTPException
from ..types import IngestPayload
from ..rag.store import ingest_sample_from_file, ingest_items

router = APIRouter(prefix="/rag")

@router.post("/ingest_sample")
def rag_ingest_sample():
    try:
        return ingest_sample_from_file()
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/ingest")
def rag_ingest(payload: IngestPayload):
    return ingest_items(payload.items)
