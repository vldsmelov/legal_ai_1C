# DEPLOY — развертывание и эксплуатация

## 1) Требования

- ОС: Ubuntu 22.04+ / Debian 12+ / аналогичный Linux.
- Docker Engine 27+, Docker Compose 2.39+.
- NVIDIA GPU (RTX 5090) + драйверы + nvidia-container-toolkit.
- CUDA userspace для PyTorch nightly cu130 (в образ уже встроено).
- Доступ к сети только для начальной загрузки весов (или прогретый кэш).

**Проверка GPU в Docker**:
```bash
nvidia-smi
docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi
```

**Установка nvidia-container-toolkit (если не установлен)**:
```
# см. оф. инструкцию NVIDIA для вашей ОС/дистрибутива
sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure
sudo systemctl restart docker
```

## 2) Сборка и запуск

**Модели Ollama**
```
ollama pull qwen2.5:7b-instruct
```

### Чистая сборка с базовым образом
Если используете разделённую сборку (`backend/Dockerfile.base` + `backend/Dockerfile`):
```bash
# базовый образ собираем из каталога backend
docker build --no-cache -f backend/Dockerfile.base -t legal-ai/backend-base:cu130 backend
# затем соберём только backend (использует BASE_IMAGE из compose)
docker compose build --no-cache backend
```

### Обновление зависимостей

- Лёгкие пакеты: добавьте/обновите в `backend/requirements.txt`, затем выполните `docker compose build backend` и `docker compose up -d backend`.
- Тяжёлые пакеты (PyTorch, HuggingFace и т.п.): меняем `backend/requirements.base.txt` и пересобираем базовый образ `backend/Dockerfile.base`, после чего пересобираем `backend`.

**Поднять стек**
```
export DOCKER_BUILDKIT=1
docker compose up -d --build
```

**Проверки**
```
curl -s http://localhost:8000/health | jq
docker logs -f backend
```

## 3) Кэширование весов (HF cache)

**Рекомендуется смонтировать и предварительно наполнить локальный кэш**:
```
# docker-compose.yml
services:
  backend:
    volumes:
      - ./.hf_cache:/root/.cache/huggingface
```
**Прогреть кэш реранкера до запуска:**
```
mkdir -p .hf_cache
docker run --rm -v "$PWD/.hf_cache:/root/.cache/huggingface" \
  legal-ai/backend:dev \
  python - <<'PY'
from FlagEmbedding import FlagReranker
FlagReranker("BAAI/bge-reranker-v2-m3", use_fp16=False, device="cpu")
print("reranker cached")
PY
```
Аналогично можно прогреть и эмбеддер (BGE-M3) — он подтянется при первом ingest/search.

## 3.1 Сеть и фоллбэк HTTPS→HTTP
В некоторых средах HTTPS из контейнера может быть недоступен. Для диагностики:
```bash 
curl -s "http://localhost:8000/net/check?url=https://publication.pravo.gov.ru/" | jq +curl -s "http://localhost:8000/net/check?url=http://publication.pravo.gov.ru/" | jq +``] 
```
Онлайн-ингест поддерживает автоматический даунгрейд: 
```bash
curl -s -X POST http://localhost:8000/rag/fetch_ingest_publication
```
## 4) Режимы старта

**Для быстрого и стабильного запуска используйте «лёгкие» проверки:**
```
STARTUP_CHECKS=1
SELF_CHECK_TIMEOUT=5
SELF_CHECK_GEN=0
EMBED_PRELOAD=0
RERANK_PRELOAD=0
STARTUP_CUDA_NAME=0
```

**Команда:**
```
uvicorn app:app --host 0.0.0.0 --port 8000 --log-level info
```
Не используйте `--reload` в проде: он порождает двойной процесс и усложняет диагностику.

## 5) Производительность

- Реранкер: RERANK_KEEP=5, RERANK_BATCH=16 достаточно для RTX 5090.
- Генерация: max_tokens 256–700 для быстрых ответов.
- Ингест большого корпуса: грузите батчами по 1–5 тыс. записей.
- Для онлайн-ингеста используйте /rag/fetch_ingest_publication_batch и concurrency.

## 6) Безопасность
- Запускать backend в частной сети Docker; наружу публиковать только 8000 (или за обратным прокси).
- По желанию: включить простую аутентификацию/токен в прокси (Nginx/Traefik).
- CORS — ограничить домены фронта.
- Логи — не сохранять текст договоров дольше необходимого.

## 7) Обновления без простоя

- Построить новый образ → docker compose up -d (Compose сам перезапустит контейнер).

- Qdrant хранит данные в volume — не теряются.

- При изменении схемы коллекции — создать новую коллекцию и переключить имя в ENV.

## 8) Мониторинг/Диагностика

- /health — быстрый статус.

- docker logs -f backend — трассировка старта и запросов.

- Если «висит» первый /analyze — проверьте прогрев HF-кэша реранкера.

- Если /net/check возвращает ConnectTimeout для HTTPS, проверьте сетевые политики Docker/файрволл и используйте allow_http_downgrade: true на время загрузки источников.

## 9) Оффлайн-развёртывание

- Прогрейте HF-кэш и образ заранее на машине с интернетом:
  
  - .hf_cache (BGE-M3, bge-reranker-v2-m3)
  - ollama pull qwen2.5:7b-instruct + экспорт образа ollama (или локальный реестр)

- Перенесите на целевую машину, смонтируйте .hf_cache, импортируйте модели Ollama.