import json, re, hashlib, torch
from typing import Any, Dict, List
from .types import SourceItem

def extract_json(text: str) -> Dict[str, Any]:
    if not text:
        return {}
    try:
        return json.loads(text)
    except Exception:
        pass
    text = re.sub(r"```(json)?", "", text).strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    start = text.find("{")
    last_good = None
    while start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{": depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    cand = text[start:i+1]
                    try: last_good = json.loads(cand)
                    except Exception: pass
                    break
        start = text.find("{", start + 1)
    return last_good or {}

def text_hash(t: str) -> str:
    return hashlib.sha256(t.encode("utf-8")).hexdigest()[:16]

def pick_device_auto(req: str) -> str:
    if req == "cuda": return "cuda"
    if req == "cpu": return "cpu"
    return "cuda" if torch.cuda.is_available() else "cpu"

def dedup_sources_by_hash(sources: List[SourceItem]) -> List[SourceItem]:
    seen, out = set(), []
    for s in sources:
        if s.source_hash in seen: continue
        seen.add(s.source_hash); out.append(s)
    return out

def deterministic_point_id(key: str) -> int:
    h = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
    return int(h, 16)
