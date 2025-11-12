from __future__ import annotations

import re
from pathlib import Path
from typing import List

try:  # pragma: no cover - optional dependency
    from pypdf import PdfReader  # type: ignore
except Exception:  # noqa: S110
    PdfReader = None  # type: ignore

from .html_extract import split_into_chunks
from ..types import IngestItem


class PdfLoaderUnavailable(RuntimeError):
    """Выбрасывается, если модуль pypdf недоступен."""


def _require_pdf_reader() -> None:
    if PdfReader is None:  # pragma: no cover - зависит от окружения
        raise PdfLoaderUnavailable("pypdf is not installed; cannot ingest PDF documents")


def _sanitize_title(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    return cleaned[:300]


def _derive_act_title(raw_text: str, fallback: str) -> str:
    for line in raw_text.splitlines():
        candidate = line.strip()
        if len(candidate) < 6:
            continue
        # отбрасываем номера страниц и одиночные цифры
        if re.fullmatch(r"\d+", candidate):
            continue
        return _sanitize_title(candidate)
    return fallback


def _slugify(name: str) -> str:
    slug = name.strip().lower()
    slug = re.sub(r"[\s\-/]+", "_", slug, flags=re.UNICODE)
    slug = re.sub(r"[^\w]+", "_", slug, flags=re.UNICODE)
    slug = re.sub(r"_+", "_", slug).strip("_")
    return slug or "document"


def pdf_to_ingest_items(path: Path, *, max_chars: int = 1800, overlap: int = 120) -> List[IngestItem]:
    """Читает PDF-файл и возвращает чанки текста для загрузки в RAG."""

    _require_pdf_reader()

    reader = PdfReader(str(path))
    pages: List[str] = []
    for page in reader.pages:
        try:
            text = page.extract_text() or ""
        except Exception as exc:  # noqa: BLE001 - продолжаем, но логируем
            raise RuntimeError(f"cannot extract text from {path}: {exc}")
        cleaned = text.replace("\r\n", "\n").replace("\r", "\n").strip()
        if cleaned:
            pages.append(cleaned)

    if not pages:
        return []

    full_text = "\n\n".join(pages)
    act_title = _derive_act_title(full_text, _sanitize_title(path.stem))
    act_id = _slugify(path.stem)
    base_ref = f"ru_law/{act_id}"

    chunks = split_into_chunks(full_text, max_chars=max_chars, overlap=overlap)
    items: List[IngestItem] = []
    for idx, chunk in enumerate(chunks, start=1):
        body = chunk.strip()
        if not body:
            continue
        items.append(
            IngestItem(
                act_id=act_id,
                act_title=act_title,
                article=None,
                part=None,
                point=None,
                revision_date=None,
                jurisdiction="RU",
                text=body,
                local_ref=f"{base_ref}/chunk{idx}",
            )
        )

    return items


def txt_to_ingest_items(path: Path, *, max_chars: int = 1800, overlap: int = 120) -> List[IngestItem]:
    """Читает обычный текстовый файл и делит его на чанки для загрузки."""

    raw_text = path.read_text(encoding="utf-8", errors="replace").strip()
    if not raw_text:
        return []

    lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
    if not lines:
        return []

    act_title = _derive_act_title("\n".join(lines), _sanitize_title(path.stem))
    act_id = _slugify(path.stem)
    base_ref = f"ru_text/{act_id}"

    chunks = split_into_chunks(raw_text, max_chars=max_chars, overlap=overlap)
    items: List[IngestItem] = []
    for idx, chunk in enumerate(chunks, start=1):
        body = chunk.strip()
        if not body:
            continue
        items.append(
            IngestItem(
                act_id=act_id,
                act_title=act_title,
                article=None,
                part=None,
                point=None,
                revision_date=None,
                jurisdiction="RU",
                text=body,
                local_ref=f"{base_ref}/chunk{idx}",
            )
        )

    return items
