#!/usr/bin/env bash
set -euo pipefail

VOLUME_NAME=${1:-legal_ai_1c_qdrant_data}
CONTAINER_NAME=${2:-qdrant}

if ! command -v docker >/dev/null 2>&1; then
  echo "docker CLI is required" >&2
  exit 1
fi

if ! docker volume inspect "$VOLUME_NAME" >/dev/null 2>&1; then
  echo "Volume '$VOLUME_NAME' does not exist. Nothing to reset."
  exit 0
fi

if docker ps -a --format '{{.Names}}' | grep -qx "$CONTAINER_NAME"; then
  running_state=$(docker inspect -f '{{.State.Running}}' "$CONTAINER_NAME" 2>/dev/null || echo "false")
  if [ "$running_state" = "true" ]; then
    echo "Stopping running qdrant container: $CONTAINER_NAME"
    docker stop "$CONTAINER_NAME" >/dev/null 2>&1 || true
  fi

  echo "Removing qdrant container: $CONTAINER_NAME"
  docker rm "$CONTAINER_NAME" >/dev/null 2>&1 || true
fi

echo "Removing volume '$VOLUME_NAME'"
docker volume rm "$VOLUME_NAME"

echo "Qdrant volume has been reset. Run 'docker compose up -d qdrant' to recreate it."
