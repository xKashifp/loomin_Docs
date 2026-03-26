#!/usr/bin/env bash
set -euo pipefail

# Generates deploy/ollama-data.tar by creating required Ollama models
# (chat + embeddings) inside the local Ollama volume and snapshotting it.
#
# This script requires internet access on the build machine.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

VOLUME_NAME="${OLLAMA_VOLUME_NAME:-loomin-ollama-data}"
OUT_TAR="${ROOT_DIR}/deploy/ollama-data.tar"
MODelfile_PATH="${ROOT_DIR}/backend/ollama/Modelfile"
MODelfile_MISTRAL_PATH="${ROOT_DIR}/backend/ollama/Modelfile.mistral"

CHAT_MODEL_ID="${OLLAMA_CHAT_MODEL_ID:-loomin-llama3}"
BASE_CHAT_MODEL="${OLLAMA_BASE_CHAT_MODEL:-llama3}"
CHAT_MODEL_ID_MISTRAL="${OLLAMA_CHAT_MODEL_ID_MISTRAL:-loomin-mistral}"
BASE_CHAT_MODEL_MISTRAL="${OLLAMA_BASE_CHAT_MODEL_MISTRAL:-mistral}"
EMBED_MODEL_ID="${OLLAMA_EMBED_MODEL_ID:-nomic-embed-text}"

echo "[ollama] Using docker volume: ${VOLUME_NAME}"
echo "[ollama] Output tar: ${OUT_TAR}"

if [ ! -f "${MODelfile_PATH}" ]; then
  echo "[ollama] Missing Modelfile: ${MODelfile_PATH}"
  exit 1
fi
if [ ! -f "${MODelfile_MISTRAL_PATH}" ]; then
  echo "[ollama] Missing Modelfile: ${MODelfile_MISTRAL_PATH}"
  exit 1
fi

# Ensure volume exists
docker volume inspect "${VOLUME_NAME}" >/dev/null 2>&1 || docker volume create "${VOLUME_NAME}" >/dev/null

echo "[ollama] Creating required models inside volume..."
docker run --rm --entrypoint sh \
  -v "${VOLUME_NAME}:/root/.ollama" \
  -v "${ROOT_DIR}:/pkg:ro" \
  ollama/ollama:latest -c "\
    ollama serve >/dev/null 2>&1 & \
    pid=\$!; \
    i=0; \
    until ollama list >/dev/null 2>&1; do \
      i=\$((i+1)); \
      if [ \$i -gt 60 ]; then \
        echo '[ollama] ERROR: ollama serve did not become ready in time' >&2; \
        exit 1; \
      fi; \
      sleep 1; \
    done; \
    ollama pull ${BASE_CHAT_MODEL} && \
    ollama pull ${BASE_CHAT_MODEL_MISTRAL} && \
    ollama pull ${EMBED_MODEL_ID} && \
    ollama create ${CHAT_MODEL_ID} -f /pkg/backend/ollama/Modelfile && \
    ollama create ${CHAT_MODEL_ID_MISTRAL} -f /pkg/backend/ollama/Modelfile.mistral; \
    kill \$pid \
  "

echo "[ollama] Snapshotting /root/.ollama to tar..."
docker run --rm --entrypoint sh \
  -v "${VOLUME_NAME}:/root/.ollama" \
  -v "$(dirname "${OUT_TAR}"):/out" \
  ollama/ollama:latest -c "tar -cf /out/$(basename "${OUT_TAR}") -C /root/.ollama ."

echo "[ollama] Done."

