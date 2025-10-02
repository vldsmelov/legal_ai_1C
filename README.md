# Legal AI (RU) — локальный ИИ-юрист

**Назначение:** проверка договоров по российскому праву локально, без выхода в сеть.

**Стек:** FastAPI · Ollama (LLM: `qwen2.5:7b-instruct`) · Qdrant (вектора) · BGE-M3 (эмбеддер) · **bge-reranker-v2-m3** (GPU-реранкер).

---

## Возможности

- 🔒 **Полностью локально**: без интернета (с прогретыми весами).
- 🧠 **RAG** по базе НПА РФ (статьи/части/пункты).
- 🎯 **Точный контекст**: кросс-энкодер **bge-reranker-v2-m3** на GPU.
- ✅ **Скоринг 1–100** + вердикт (`green`/`yellow`/`red`) и краткий фокус-свод.
- 🧩 Чёткий JSON-ответ с **issues**, **section_scores** и **sources** (цитаты НПА).

---

## Структура
```
backend/
├─ app.py
├─ app_core/
│ ├─ main.py # сборка приложения
│ ├─ config.py # ENV/настройки
│ ├─ types.py # Pydantic-схемы
│ ├─ scoring.py # разделы, расчёт баллов, focus
│ ├─ utils.py # утилиты (JSON, кэш, dedup, id)
│ ├─ startup.py # лёгкие startup-проверки
│ ├─ llm/ollama.py # вызовы Ollama
│ ├─ rag/embedder.py # BGE-M3 (GPU/CPU auto)
│ ├─ rag/store.py # Qdrant: ingest/search
│ ├─ rerank.py # bge-reranker-v2-m3 (GPU)
│ └─ routes/
│ ├─ health.py # GET /health
│ ├─ ingest.py # POST /rag/ingest(_sample)
│ └─ analyze.py # POST /analyze, /generate
corpus/
└─ ru_sample.jsonl # демо-НПА
```

---

## Быстрый старт

```bash
# 1) Модель для Ollama
ollama pull qwen2.5:7b-instruct

# 2) Поднять стек
docker compose up -d --build

# 3) Проверить здоровье
curl -s http://localhost:8000/health | jq

# 4) Загрузить демо-НПА
mkdir -p corpus
curl -s -X POST http://localhost:8000/rag/ingest_sample | jq

# 5) Пробный анализ
curl -s -X POST http://localhost:8000/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "contract_text": "ДОГОВОР УСЛУГ ... (см. примеры ниже)",
    "jurisdiction": "RU",
    "contract_type": "услуги",
    "language": "ru",
    "max_tokens": 512
  }' | jq
```

---


## Конфигурация (ENV)
| Ключ                 | Значение (по умолч.)      | Описание                 |
| -------------------- | ------------------------- | ------------------------ |
| `OLLAMA_BASE_URL`    | `http://ollama:11434`     | адрес Ollama             |
| `OLLAMA_MODEL`       | `qwen2.5:7b-instruct`     | LLM                      |
| `QDRANT_URL`         | `http://qdrant:6333`      | адрес Qdrant             |
| `QDRANT_COLLECTION`  | `ru_law_m3`               | коллекция                |
| `EMBEDDING_MODEL`    | `BAAI/bge-m3`             | эмбеддер                 |
| `EMBED_DEVICE`       | `auto` | `cuda` | `cpu`   | устройство для эмбеддера |
| `RAG_TOP_K`          | `8`                       | кандидаты до rerank      |
| `RERANK_ENABLE`      | `1`                       | включить реранкер        |
| `RERANKER_MODEL`     | `BAAI/bge-reranker-v2-m3` | модель реранка           |
| `RERANK_DEVICE`      | `auto`                    | устройство для реранка   |
| `RERANK_KEEP`        | `5`                       | оставить после rerank    |
| `RERANK_BATCH`       | `16`                      | батч скоринга            |
| `RERANK_DEBUG`       | `0`                       | лог скорингов            |
| `STARTUP_CHECKS`     | `1`                       | лёгкие стартап-чеки      |
| `SELF_CHECK_TIMEOUT` | `5`                       | таймаут пингов           |
| `SELF_CHECK_GEN`     | `0`                       | тест-генерация на старте |
| `STARTUP_CUDA_NAME`  | `0`                       | печатать имя GPU         |
| `SCORING_MODE`       | `strict` | `lenient`      | «мягкий» скоринг         |
| `SCORE_GREEN`        | `75`                      | порог зелёного           |
| `SCORE_YELLOW`       | `51`                      | порог жёлтого            |

Рекомендуется смонтировать HF-кэш: .`/.hf_cache:/root/.cache/huggingface` (см. DEPLOY).

---

## API
`GET /health`

Краткий статус сервисов (Ollama, Qdrant, коллекция, реранкер).

`POST /rag/ingest_sample`

Грузит corpus/ru_sample.jsonl в Qdrant (детерминированные ID, без дублей).

`POST /rag/ingest`

Ингест переданного массива НПА:

```
{ "items": [ { "act_id": "...", "article": "...", "text": "...", "local_ref": "..." }, ... ] }
```

---

## Смоук-примеры

- Висит `/analyze` при первом вызове — не прогрет реранкер. Прогрейте HF-кэш (см. DEPLOY) или временно `RERANK_ENABLE=0`.

- Ошибка `vectors|vectors_config` — несовместимость клиентов Qdrant, в коде есть try/except. При смене размерности дропните коллекцию и перезагрузите.

- Дубли в **sources** — в ответе есть **dedup**; при ingest ID детерминированные → апсерт.

---
## Лицензии / Примечания

- BGE (BAAI) — см. лицензию BAAI. Qdrant — Apache-2.0.

- Данный проект — пример для внутреннего использования. Проверяйте соответствие требованиям вашей организации.