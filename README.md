# Legal AI Orchestrator

Минималистичный backend, который связывает уже запущенные сервисы Ollama и Qdrant. Приложение не содержит собственных моделей и
не управляет базой данных — оно только оркестрирует взаимодействие:

1. Получает текст договора от клиента.
2. Строит эмбеддинг через Ollama (`/api/embeddings`, модель `BAAI/bge-m3`).
3. Выполняет поиск релевантных норм в Qdrant и собирает контекст.
4. Формирует промпт и вызывает LLM Ollama (`krith/qwen2.5-32b-instruct:IQ4_XS`).
5. Возвращает структурированный JSON и/или HTML-отчёт с перечнем источников.

## Архитектура

```
клиент → FastAPI → Ollama (embeddings) → Qdrant (vector search)
                          ↘ Ollama (LLM chat)
```

- **Ollama** — внешний сервис по адресу `http://localhost:11434/`. Используется для генерации и эмбеддингов.
- **Qdrant** — внешний сервис по адресу `http://localhost:6333/`. Хранит коллекцию с нормами права.
- **Backend** — сервис FastAPI, который связывает оба источника и формирует итоговый отчёт.

## Предварительные требования

| Компонент | Версия | Примечания |
| --- | --- | --- |
| Python | 3.11+ | рекомендуем 3.12 |
| Ollama | ≥ 0.1.48 | модель `krith/qwen2.5-32b-instruct:IQ4_XS`, эмбеддинги `BAAI/bge-m3` |
| Qdrant | ≥ 1.9 | коллекция должна соответствовать размерности эмбеддингов |

Перед запуском backend убедитесь, что Ollama и Qdrant подняты и доступны по указанным адресам.

## Быстрый запуск (локально)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8087 --app-dir backend
```

Проверка:

```bash
curl -s http://127.0.0.1:8087/health | jq
```

## Запуск в Docker

Для контейнерного развёртывания используйте свежий образ Python 3.12.

```bash
docker build -t legal-ai-backend -f backend/Dockerfile .
docker run --rm \
  --name legal-ai-backend \
  --add-host=host.docker.internal:host-gateway \
  -e OLLAMA_BASE_URL=http://host.docker.internal:11434 \
  -e QDRANT_URL=http://host.docker.internal:6333 \
  -p 8087:8087 \
  legal-ai-backend
```

> На macOS/Windows параметр `--add-host` не требуется: `host.docker.internal` уже настроен Docker Desktop.

## Запуск через Docker Compose

`docker-compose.yml` запускает только backend и подключает его к уже работающим Ollama и Qdrant на машине-хосте.

```bash
docker compose up -d
```

Команда опубликует порт 8087 и примонтирует каталоги `./corpus` (только чтение) и `./reports`. Для Linux используется настройка
`extra_hosts`, чтобы внутри контейнера был доступен адрес `http://host.docker.internal`. На macOS/Windows дополнительная настройка
не нужна.

Остановка backend:

```bash
docker compose down
```

## Основные переменные окружения

| Переменная | Значение по умолчанию | Назначение |
| --- | --- | --- |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Базовый URL Ollama |
| `OLLAMA_MODEL` | `krith/qwen2.5-32b-instruct:IQ4_XS` | Модель LLM |
| `EMBEDDING_MODEL` | `BAAI/bge-m3` | Модель эмбеддингов (используется и для индексации, и для поиска) |
| `QDRANT_URL` | `http://127.0.0.1:6333` | Базовый URL Qdrant |
| `QDRANT_COLLECTION` | `docs` | Коллекция с нормами права |
| `RAG_TOP_K` | `8` | Количество контекстов, возвращаемых Qdrant |
| `STARTUP_CHECKS` | `true` | Включить лёгкие проверки Ollama/Qdrant при запуске |
| `SELF_CHECK_TIMEOUT` | `5` | Таймаут ожидания (секунды) при проверках |
| `SELF_CHECK_GEN` | `false` | Тестовая генерация на старте |
| `SCORE_GREEN` | `75` | Порог «зелёного» статуса |
| `SCORE_YELLOW` | `51` | Порог «жёлтого» статуса |
| `BUSINESS_MAX_TOKENS` | `1400` | Базовый лимит токенов бизнес-анализа |
| `BUSINESS_RETRY_STEP` | `400` | Шаг увеличения лимита при повторной попытке |
| `LEGAL_AI_PROJECT_ROOT` | `<корень репозитория>` | Базовый путь проекта (опционально) |
| `LEGAL_AI_LOCAL_BASE` | `<корень репозитория>` | Каталог, из которого разрешено читать локальные файлы |
| `LEGAL_AI_CORPUS_DIR` | `<корень>/corpus` | Каталог JSONL-корпусов для индексации |
| `REPORT_OUTPUT_DIR` | `<корень>/reports` | Директория для сохранения HTML-отчётов |

Все переменные можно задать через `.env` или напрямую в окружении.

## Как работает анализ

1. `POST /analyze` получает текст договора и параметры.
2. Текст кодируется в эмбеддинг через Ollama.
3. Эмбеддинг используется для поиска релевантных норм в Qdrant (`jurisdiction="RU"`).
4. Собранный контекст + исходный текст передаются в LLM.
5. Возвращается структурированный JSON, включающий оценки, замечания, источники и краткие выводы. HTML-вёрстка формируется через модуль `report/render.py` и доступна в эндпоинтах `doc`.

## Загрузка базы знаний

Индексация корпуса теперь выполняется вне backend. Используйте собственные пайплайны, чтобы:

1. Считать документы, разбить их на минимальные фрагменты.
2. Получить эмбеддинги через Ollama (`/api/embeddings`, модель должна совпадать с `EMBEDDING_MODEL`).
3. Добавить точки в Qdrant через его HTTP API или клиентские SDK.

Backend предполагает, что коллекция уже создана и содержит актуальные данные. Размерность эмбеддингов при индексации и поиске должна совпадать.

## HTML-отчёт

Эндпоинт `POST /analyze` поддерживает генерацию HTML напрямую. Передайте дополнительные поля:

```json
{
  "contract_text": "...",
  "report_format": "html",
  "report_name": "sample-report",
  "report_meta": {
    "source_path": "contracts/sample.txt",
    "compact_preview": "первые 800 символов",
    "original_bytes": 12345,
    "compact_bytes": 6789
  }
}
```

- `report_format: "html"` включает рендеринг и сохраняет файл в `REPORT_OUTPUT_DIR` (`./reports` по умолчанию).
- Ответ содержит поле `report_path` с абсолютным путём до созданного HTML.
- `report_name` задаёт базовое имя файла; по умолчанию берётся из `source_path`/`source_url`.
- `report_meta` позволяет передать служебные данные для заголовков отчёта.

Для получения готовой вёрстки через вспомогательные маршруты используйте:

- `POST /doc/analyze_file` — читает локальный txt/rtf/docx (через предварительную конвертацию в текст) из каталога `LEGAL_AI_LOCAL_BASE`, вызывает `/analyze` и при необходимости сохраняет HTML.

Функция `save_report_html` сохраняет готовый документ в `REPORT_OUTPUT_DIR`. Путь возвращается в ответе.

### Пример запроса к `/doc/analyze_file`

```bash
curl -X POST http://localhost:8087/doc/analyze_file \
  -H 'Content-Type: application/json' \
  -d '{
    "path": "corpus/contracts/sample.txt",
    "jurisdiction": "RU",
    "contract_type": "услуги",
    "language": "ru",
    "max_tokens": 600,
    "per_section_limit": 2200,
    "total_limit": 20000,
    "report_format": "html",
    "report_name": "sample-report"
  }'
```

- `path` — путь к файлу внутри каталога, указанного в `LEGAL_AI_LOCAL_BASE` (по умолчанию — корень репозитория). Если нужно обрабатывать документ из любой другой директории, задайте переменную окружения `LEGAL_AI_LOCAL_BASE=/путь/к/папке` и передайте относительный путь от неё: `"path": "contract.docx"`.
- При запуске через Docker Compose добавьте монтирование нужной папки и значение переменной:

  ```yaml
  volumes:
    - /home/user/contracts:/data/contracts:ro
  environment:
    LEGAL_AI_LOCAL_BASE: /data/contracts
  ```

  После этого запрос с `"path": "contract.docx"` найдёт файл внутри контейнера.
- Параметры `max_tokens`, `per_section_limit`, `total_limit` управляют объёмом текста, передаваемого в `/analyze`.
- Укажите `report_format: "html"`, чтобы получить путь к сохранённому HTML. Файлы всегда записываются в `REPORT_OUTPUT_DIR`.

### Пример запроса с загрузкой файла (`/doc/analyze_upload`)

Если файл нельзя поместить в каталог, указанный `LEGAL_AI_LOCAL_BASE`, загрузите его напрямую в запросе:

```bash
curl -X POST http://localhost:8087/doc/analyze_upload \
  -F 'file=@samples/doc_sample.txt' \
  -F 'jurisdiction=RU' \
  -F 'contract_type=услуги' \
  -F 'language=ru' \
  -F 'max_tokens=600' \
  -F 'report_format=html'
```

- Формы `per_section_limit`, `total_limit`, `report_name` также можно передавать через `-F`.
- Ответ содержит те же поля, что и `analyze_file`, включая `report_path` с адресом HTML-файла.

## Обзор API

| Метод | Путь | Назначение |
| --- | --- | --- |
| `GET` | `/health` | Проверка доступности Ollama и Qdrant, текущие настройки |
| `POST` | `/analyze` | Основной анализ договора (JSON-ответ) |
| `POST` | `/doc/analyze_file` | Анализ файла по пути внутри `LEGAL_AI_LOCAL_BASE` |
| `POST` | `/doc/analyze_upload` | Анализ загруженного файла (multipart/form-data) |

Дополнительные детали формата данных и best practices см. в `docs/DEPLOY.md` и `docs/RAG_FORMAT.md`.
