from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from ..config import settings


def _resolve_prompt_path(name: str) -> Path:
    base_dir = Path(settings.PROMPTS_DIR)
    filename = settings.PROMPTS.get(name, f"{name}.txt")
    path = base_dir / filename
    return path


@lru_cache(maxsize=None)
def get_prompt_template(name: str) -> str:
    path = _resolve_prompt_path(name)
    if not path.exists():
        raise FileNotFoundError(f"Prompt template '{name}' not found at {path}")
    return path.read_text(encoding="utf-8")


def render_prompt(name: str, **kwargs) -> str:
    template = get_prompt_template(name)
    return template.format(**kwargs)


__all__ = ["get_prompt_template", "render_prompt"]
