# backend/Dockerfile
# syntax=docker/dockerfile:1.7-labs
ARG BASE_IMAGE=legal-ai/backend-base:cu130
FROM ${BASE_IMAGE}

WORKDIR /workspace/backend

# Устанавливаем лёгкие зависимости, которые могут часто меняться
COPY requirements.txt /tmp/requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir -r /tmp/requirements.txt

COPY app.py /workspace/backend/app.py

EXPOSE 8000
# запуск задаёт compose: command: uvicorn ...
