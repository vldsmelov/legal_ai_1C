from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

import yaml


BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config" / "settings.yaml"


def _load_config() -> Dict[str, Any]:
    if CONFIG_PATH.exists():
        with CONFIG_PATH.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
            if not isinstance(data, dict):
                raise ValueError("settings.yaml должен содержать объект верхнего уровня")
            return data
    return {}


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return False


class Settings:
    def __init__(self) -> None:
        cfg = _load_config()

        ollama_cfg = cfg.get("ollama", {}) if isinstance(cfg.get("ollama"), dict) else {}
        rag_cfg = cfg.get("rag", {}) if isinstance(cfg.get("rag"), dict) else {}
        startup_cfg = cfg.get("startup", {}) if isinstance(cfg.get("startup"), dict) else {}
        scoring_cfg = cfg.get("scoring", {}) if isinstance(cfg.get("scoring"), dict) else {}
        prompts_cfg = cfg.get("prompts", {}) if isinstance(cfg.get("prompts"), dict) else {}

        # Ollama
        self.OLLAMA_URL = os.getenv("OLLAMA_BASE_URL") or ollama_cfg.get("url", "http://127.0.0.1:11434")
        self.OLLAMA_MODEL = os.getenv("OLLAMA_MODEL") or ollama_cfg.get("model", "krith/qwen2.5-32b-instruct:IQ4_XS")

        # RAG
        self.QDRANT_URL = os.getenv("QDRANT_URL") or rag_cfg.get("qdrant_url", "http://127.0.0.1:6333")
        self.QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION") or rag_cfg.get("collection", "docs")
        self.EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL") or rag_cfg.get("embedding_model", "BAAI/bge-m3")
        rag_top_k_env = os.getenv("RAG_TOP_K")
        self.RAG_TOP_K = int(rag_top_k_env) if rag_top_k_env is not None else int(rag_cfg.get("top_k", 8))

        # Startup flags
        startup_checks_env = os.getenv("STARTUP_CHECKS")
        self.STARTUP_CHECKS = _to_bool(startup_checks_env if startup_checks_env is not None else startup_cfg.get("checks", True))
        self_check_timeout_env = os.getenv("SELF_CHECK_TIMEOUT")
        self.SELF_CHECK_TIMEOUT = (
            int(self_check_timeout_env)
            if self_check_timeout_env is not None
            else int(startup_cfg.get("self_check_timeout", 5))
        )
        self_check_gen_env = os.getenv("SELF_CHECK_GEN")
        self.SELF_CHECK_GEN = _to_bool(
            self_check_gen_env if self_check_gen_env is not None else startup_cfg.get("self_check_gen", False)
        )

        # Scoring / UI
        self.SCORING_MODE = os.getenv("SCORING_MODE") or scoring_cfg.get("mode", "strict")
        score_green_env = os.getenv("SCORE_GREEN")
        self.SCORE_GREEN = int(score_green_env) if score_green_env is not None else int(scoring_cfg.get("score_green", 75))
        score_yellow_env = os.getenv("SCORE_YELLOW")
        self.SCORE_YELLOW = int(score_yellow_env) if score_yellow_env is not None else int(scoring_cfg.get("score_yellow", 51))
        business_max_tokens_env = os.getenv("BUSINESS_MAX_TOKENS")
        self.BUSINESS_MAX_TOKENS = (
            int(business_max_tokens_env)
            if business_max_tokens_env is not None
            else int(scoring_cfg.get("business_max_tokens", 1400))
        )
        business_retry_env = os.getenv("BUSINESS_RETRY_STEP")
        self.BUSINESS_RETRY_STEP = (
            int(business_retry_env)
            if business_retry_env is not None
            else int(scoring_cfg.get("business_retry_step", 400))
        )

        # Prompts configuration
        prompt_dir_env = os.getenv("PROMPTS_DIR")
        if prompt_dir_env:
            prompt_dir = Path(prompt_dir_env)
        else:
            dir_from_cfg = prompts_cfg.get("dir")
            prompt_dir = Path(dir_from_cfg) if dir_from_cfg else BASE_DIR / "prompts"
        if not prompt_dir.is_absolute():
            prompt_dir = (BASE_DIR / prompt_dir).resolve()
        self.PROMPTS_DIR = prompt_dir
        self.PROMPTS: Dict[str, str] = {
            "analyze_system": prompts_cfg.get("analyze_system", "analyze_system.txt"),
            "analyze_user": prompts_cfg.get("analyze_user", "analyze_user.txt"),
            "analyze_system_lenient_rule": prompts_cfg.get(
                "analyze_system_lenient_rule", "analyze_system_lenient_rule.txt"
            ),
            "business_system": prompts_cfg.get("business_system", "business_system.txt"),
            "business_user": prompts_cfg.get("business_user", "business_user.txt"),
            "overview_system": prompts_cfg.get("overview_system", "overview_system.txt"),
            "overview_user": prompts_cfg.get("overview_user", "overview_user.txt"),
        }


settings = Settings()
