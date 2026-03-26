#!/usr/bin/env bash
set -euo pipefail

# Creates the air-gapped bootstrap archive expected by the evaluation VM.
#
# Expected contents (to exist before running):
# - deploy/setup.sh
# - deploy/docker-compose.yml
# - deploy/rpms/*.rpm
# - deploy/docker-images/*.tar
# - deploy/ollama-data.tar

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT_DIR="${ROOT_DIR}/deploy"
OUT_TAR="${OUT_DIR}/loomin-docs-bootstrap-rhel9.tar.gz"

require_file_or_dir() {
  local p="$1"
  if [ ! -e "$p" ]; then
    echo "[package] Missing: $p"
    exit 1
  fi
}

require_file_or_dir "${OUT_DIR}/setup.sh"
require_file_or_dir "${OUT_DIR}/docker-compose.yml"
require_file_or_dir "${OUT_DIR}/rpms"
require_file_or_dir "${OUT_DIR}/docker-images"
require_file_or_dir "${OUT_DIR}/ollama-data.tar"

echo "[package] Creating bootstrap archive:"
echo "  ${OUT_TAR}"

tar -czf "${OUT_TAR}" \
  -C "${ROOT_DIR}" \
  "deploy/setup.sh" \
  "deploy/docker-compose.yml" \
  "deploy/rpms" \
  "deploy/docker-images" \
  "deploy/ollama-data.tar"

ls -lah "${OUT_TAR}"
echo "[package] Done."

