import os

class Settings:
    # Ollama
    OLLAMA_URL = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")
    OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b-instruct")

    # RAG
    QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333")
    QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "ru_law_m3")
    EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")
    EMBED_DEVICE = os.getenv("EMBED_DEVICE", "auto")  # auto|cpu|cuda
    RAG_TOP_K = int(os.getenv("RAG_TOP_K", "8"))

    # Reranker
    RERANK_ENABLE = os.getenv("RERANK_ENABLE", "1") == "1"
    RERANKER_MODEL = os.getenv("RERANKER_MODEL", "BAAI/bge-reranker-v2-m3")
    RERANK_DEVICE = os.getenv("RERANK_DEVICE", "auto")
    RERANK_KEEP = int(os.getenv("RERANK_KEEP", "5"))
    RERANK_BATCH = int(os.getenv("RERANK_BATCH", "16"))
    RERANK_DEBUG = os.getenv("RERANK_DEBUG", "0") == "1"

    # Startup flags (лёгкие проверки)
    STARTUP_CHECKS = os.getenv("STARTUP_CHECKS", "1") == "1"
    SELF_CHECK_TIMEOUT = int(os.getenv("SELF_CHECK_TIMEOUT", "5"))
    SELF_CHECK_GEN = os.getenv("SELF_CHECK_GEN", "0") == "1"
    STARTUP_CUDA_NAME = os.getenv("STARTUP_CUDA_NAME", "0") == "1"

    # Scoring / UI
    SCORING_MODE = os.getenv("SCORING_MODE", "strict")  # strict|lenient
    SCORE_GREEN = int(os.getenv("SCORE_GREEN", "75"))
    SCORE_YELLOW = int(os.getenv("SCORE_YELLOW", "51"))

settings = Settings()
