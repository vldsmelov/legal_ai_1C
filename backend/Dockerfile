# syntax=docker/dockerfile:1.7

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LEGAL_AI_PROJECT_ROOT=/app \
    LEGAL_AI_LOCAL_BASE=/app \
    LEGAL_AI_CORPUS_DIR=/app/corpus \
    REPORT_OUTPUT_DIR=/app/reports

WORKDIR /app

RUN mkdir -p /app/reports /app/corpus

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY backend/ ./

EXPOSE 8087

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8087"]
