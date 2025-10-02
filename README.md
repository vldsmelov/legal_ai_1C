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
- 🌐 **Онлайн-загрузчик**: сетевые проверки (`/net/check`, `/net/fetch`), фоллбэк **HTTPS→HTTP**.
- 🗂 **Site-aware парсер публикаций**: распознавание структур `Статья/Часть/Пункт` и массовый ingest.
- ⚙️ Таймауты и производительность: увеличены таймауты на внутренние вызовы анализа (до 300s), reranker и эмбеддер работают на GPU
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
+│ ├─ rag/html_extract.py # общий HTML→текст парсер + чанкование
+│ ├─ rag/pub_pravo.py # site-aware парсер публикаций (Статья/Часть/Пункт)
│ └─ routes/
│ ├─ health.py # GET /health
│ ├─ ingest.py # POST /rag/ingest(_sample)
│ └─ analyze.py # POST /analyze, /generate
+│ └─ connectivity.py # GET /net/check, GET /net/fetch
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

# 6) Чистая сборка
docker compose down --remove-orphans
docker compose build backend
docker compose up -d
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
### Сеть / тесты доступа
#### `GET /net/check`
Проверка доступности URL (или дефолтного списка). Пример:
```
GET /net/check?url=http://publication.pravo.gov.ru/
GET /net/check?check_all=true
```
Ответ содержит `ok`, `status`, `error`, `elapsed_ms`, `final_url`.

#### `GET /net/fetch`
Стримовый fetch HTML/текста с лимитом байт и превью. Пример:
```
GET /net/fetch?url=http://publication.pravo.gov.ru/&max_bytes=500000
```
Возвращает `status`, `bytes`, `sha256`, `content_type`, `saved_path`, `preview_text`.

### `GET /health`
Краткий статус сервисов.

### `POST /rag/ingest`
Грузит переданный JSONL-массив записей.

### Онлайн-ингест (HTML → структурные записи)
#### `POST /rag/fetch_ingest`

Универсальный загрузчик: скачивает HTML, очищает, чанкит и грузит в Qdrant. Поля:
```json
{ "url": "<страница>", "max_bytes": 1500000, "timeout": 12, "allow_http_downgrade": true }
``

#### `POST /rag/fetch_ingest_publication`
Site-aware парсер страниц публикаций: пытается распознать `Статья/Часть/Пункт`, извлекает `title`, `revision_date`, формирует `local_ref` вида `...#artN/chM/ptK`.
```json
{ "url": "<страница акта>", "allow_http_downgrade": true, "max_bytes": 1800000, "timeout": 12 }
```

#### `POST /rag/fetch_ingest_publication_batch`
Пакетная версия с параллелизмом:
```json
{
  "urls": ["http://...","http://..."],
  "timeout": 12, "max_bytes": 1800000,
  "allow_http_downgrade": true, "concurrency": 4
}
```


## Смоук-примеры

- **Онлайн-ингест (пример):**
```bash
curl -s -X POST http://localhost:8000/rag/fetch_ingest_publication \
  -H "Content-Type: application/json" \
  -d '{"url":"http://publication.pravo.gov.ru/Document/View/<ID>?format=HTML","allow_http_downgrade":true}'
```
В ответе: `ingested`, `title`, `revision_date`, `items`, `final_url`.

---

## Лицензии / Примечания

- BGE (BAAI) — см. лицензию BAAI. Qdrant — Apache-2.0.

- Данный проект — пример для внутреннего использования. Проверяйте соответствие требованиям вашей организации.