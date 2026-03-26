#!/usr/bin/env bash
set -euo pipefail

# Builds and exports Docker images as offline-loadable .tar files.
#
# Output:
# - deploy/docker-images/loomin-backend.tar
# - deploy/docker-images/loomin-frontend.tar
# - deploy/docker-images/ollama-ollama.tar

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT_DIR="${ROOT_DIR}/deploy/docker-images"
mkdir -p "${OUT_DIR}"

echo "[images] Building backend image..."
docker build -t loomin-backend "${ROOT_DIR}/backend"

echo "[images] Building frontend image..."
docker build -t loomin-frontend "${ROOT_DIR}/frontend"

echo "[images] Exporting images..."
docker save loomin-backend:latest -o "${OUT_DIR}/loomin-backend.tar"
docker save loomin-frontend:latest -o "${OUT_DIR}/loomin-frontend.tar"

echo "[images] Exporting Ollama image (needed for bootstrap restore)..."
docker pull ollama/ollama:latest >/dev/null
docker save ollama/ollama:latest -o "${OUT_DIR}/ollama-ollama.tar"

echo "[images] Done. Artifacts:"
ls -lah "${OUT_DIR}"/*.tar

