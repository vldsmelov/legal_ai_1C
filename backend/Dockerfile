# backend/Dockerfile
# syntax=docker/dockerfile:1.7-labs

FROM nvidia/cuda:13.0.0-runtime-ubuntu24.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/root/.cache/huggingface \
    VIRTUAL_ENV=/opt/venv

# Базовые пакеты + Python 3.12 из Ubuntu 24.04
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 \
        python3-venv \
        python3-pip \
        python3-dev \
        build-essential \
        git \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m venv "$VIRTUAL_ENV"
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

RUN python -m pip install --upgrade pip setuptools wheel

WORKDIR /opt/app

COPY requirements.txt /tmp/requirements.txt

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir --pre \
        --index-url https://download.pytorch.org/whl/nightly/cu130 \
        --extra-index-url https://pypi.org/simple \
        torch torchvision torchaudio && \
    pip install --no-cache-dir -r /tmp/requirements.txt

COPY . /opt/app

EXPOSE 8087
# команда запуска задаётся в docker-compose.yml
