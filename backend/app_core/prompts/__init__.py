"""Utility helpers for working with prompt templates."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from string import Template

_PROMPTS_DIR = Path(__file__).resolve().parent


@lru_cache(maxsize=None)
def _load_template(name: str) -> Template:
    """Load a prompt template from the prompts directory."""
    path = _PROMPTS_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Prompt template '{name}' not found at {path}")
    text = path.read_text(encoding="utf-8")
    return Template(text)


def render_prompt(name: str, **kwargs: str) -> str:
    """Render the named prompt template using ``string.Template`` substitution."""
    template = _load_template(name)
    return template.safe_substitute(**kwargs)


__all__ = ["render_prompt"]
