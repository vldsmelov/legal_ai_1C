# backend/Dockerfile
# syntax=docker/dockerfile:1.7-labs
ARG BASE_IMAGE=legal-ai/backend-base:cu130  
FROM ${BASE_IMAGE}

WORKDIR /workspace/backend
COPY app.py /workspace/backend/app.py

EXPOSE 8000
# запуск задаёт compose: command: uvicorn ...
