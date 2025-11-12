"""Common filesystem locations for the backend."""
from __future__ import annotations

import os
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT_DEFAULT = _BACKEND_DIR.parent

PROJECT_ROOT = Path(
    os.getenv("LEGAL_AI_PROJECT_ROOT", str(_PROJECT_ROOT_DEFAULT))
).resolve()
"""Root directory of the Legal AI project (defaults to repository root)."""

CORPUS_DIR = Path(
    os.getenv("LEGAL_AI_CORPUS_DIR", str(PROJECT_ROOT / "corpus"))
).resolve()
"""Directory that stores JSONL corpora used for ingest operations."""

LOCAL_FILES_BASE = Path(
    os.getenv("LEGAL_AI_LOCAL_BASE", str(PROJECT_ROOT))
).resolve()
"""Base directory that local file operations are allowed to access."""

REPORT_OUTPUT_DIR = Path(
    os.getenv("REPORT_OUTPUT_DIR", str(PROJECT_ROOT / "reports"))
).resolve()
"""Destination directory where generated HTML reports are stored."""


def resolve_under(base: Path, candidate: str | Path) -> Path:
    """Return an absolute path for *candidate* ensuring it stays within *base*."""
    base_resolved = base.resolve()
    candidate_path = Path(candidate)
    combined = (
        candidate_path if candidate_path.is_absolute() else base_resolved / candidate_path
    ).resolve()
    try:
        combined.relative_to(base_resolved)
    except ValueError as exc:  # pragma: no cover - defensive guard
        raise ValueError(f"Path '{combined}' escapes base '{base_resolved}'") from exc
    return combined
