# Развёртывание Legal AI Orchestrator

Документ описывает установку backend как оркестратора над внешними сервисами Ollama и Qdrant. Предполагается, что оба сервиса уже
запущены и доступны в сети.

## 1. Подготовка внешних сервисов

1. **Ollama**: установите и запустите Ollama на машине с GPU/CPU.
   ```bash
   ollama pull krith/qwen2.5-32b-instruct:IQ4_XS
   ollama pull bge-m3
   ollama serve --host 0.0.0.0 --port 11434
   ```
2. **Qdrant**: поднимите отдельный экземпляр (docker, binary, managed). Например, в Docker:
   ```bash
   docker run -d --name qdrant \
     -p 6333:6333 \
     -v qdrant_storage:/qdrant/storage \
     qdrant/qdrant:latest
   ```
3. Убедитесь, что сервисы отвечают:
   ```bash
   curl http://localhost:11434/api/tags
   curl http://localhost:6333/collections
   ```

## 2. Установка backend

```bash
sudo mkdir -p /opt/legal-ai
cd /opt/legal-ai
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r /path/to/legal_ai_1C/backend/requirements.txt
```

Скопируйте репозиторий в `/opt/legal-ai` или настройте переменную `LEGAL_AI_PROJECT_ROOT`, чтобы backend мог найти директории
`corpus/` и `reports/`.

Создайте файл окружения `/opt/legal-ai/backend/.env`:

```
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=krith/qwen2.5-32b-instruct:IQ4_XS
EMBEDDING_MODEL=BAAI/bge-m3
QDRANT_URL=http://127.0.0.1:6333
QDRANT_COLLECTION=ru_law_m3
LEGAL_AI_PROJECT_ROOT=/opt/legal-ai
LEGAL_AI_LOCAL_BASE=/opt/legal-ai
REPORT_OUTPUT_DIR=/opt/legal-ai/reports
```

При необходимости добавьте другие переменные из таблицы в README.

## 3. Запуск приложения

Вручную:

```bash
cd /opt/legal-ai/backend
source ../.venv/bin/activate
uvicorn app:app --host 0.0.0.0 --port 8087 --log-level info
```

### systemd unit

`/etc/systemd/system/legal-ai.service`:

```
[Unit]
Description=Legal AI Orchestrator
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/legal-ai/backend
EnvironmentFile=/opt/legal-ai/backend/.env
ExecStart=/opt/legal-ai/.venv/bin/uvicorn app:app --host 0.0.0.0 --port 8087 --log-level info
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now legal-ai.service
```

Проверка состояния: `systemctl status legal-ai.service`.

## 4. Контейнерный вариант

Если backend запускается внутри контейнера, а Ollama/Qdrant — на хосте, пробросьте `host.docker.internal`:

```bash
docker build -t legal-ai-backend -f backend/Dockerfile .
docker run --rm \
  --name legal-ai-backend \
  --add-host=host.docker.internal:host-gateway \
  -e OLLAMA_BASE_URL=http://host.docker.internal:11434 \
  -e QDRANT_URL=http://host.docker.internal:6333 \
  -e LEGAL_AI_PROJECT_ROOT=/app \
  -p 8087:8087 \
  legal-ai-backend
```

Примонтируйте директории с корпусом и отчётами при необходимости:

```bash
docker run --rm \
  -v $(pwd)/corpus:/app/corpus \
  -v $(pwd)/reports:/app/reports \
  ...
```

## 5. Эксплуатация

- Проверить готовность: `curl http://127.0.0.1:8087/health`.
- Основной анализ: `curl -X POST http://127.0.0.1:8087/analyze -H 'Content-Type: application/json' -d '{"contract_text":"..."}'`.
- HTML-отчёт: `curl -X POST http://127.0.0.1:8087/doc/analyze_file -d '{"path":"samples/demo.txt","report_format":"html"}'`.
- Индексацию корпуса выполняйте через внешние утилиты, напрямую обращаясь к Ollama за эмбеддингами и к Qdrant за операциями с коллекцией.

## 6. Обновление

```bash
cd /opt/legal-ai
git pull
source .venv/bin/activate
pip install -r backend/requirements.txt
sudo systemctl restart legal-ai.service
```

Регулярно создавайте snapshot'ы Qdrant (`/collections/{collection}/snapshots`) и резервные копии каталога `reports/`.
