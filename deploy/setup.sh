#!/usr/bin/env bash
set -euo pipefail

# Loomin-Docs air-gapped bootstrap (RHEL 9, no internet).
#
# Expected bootstrap package layout (inside the same directory as this script):
# - rpms/                  Docker engine + compose plugin RPMs
# - docker-images/         exported Docker images as *.tar
# - docker-compose.yml     stack definition
# - ollama-data.tar        tar containing the contents of /root/.ollama
#
# This script focuses on orchestration + side-loading. The heavy artifacts
# (RPMs, image tars, model weights) must be included in the package.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "[setup] Root: ${ROOT_DIR}"

require_dir() {
  local d="$1"
  if [ ! -d "$d" ]; then
    echo "[setup] Missing directory: $d"
    exit 1
  fi
}

install_docker_from_rpms() {
  require_dir "${ROOT_DIR}/rpms"
  echo "[setup] Installing Docker from local RPMs..."

  # DNF is present on RHEL 9.
  shopt -s nullglob
  local rpms=( "${ROOT_DIR}"/rpms/*.rpm )
  if [ "${#rpms[@]}" -eq 0 ]; then
    echo "[setup] No RPMs found in rpms/; cannot install Docker offline."
    exit 1
  fi

  sudo dnf install -y "${ROOT_DIR}/rpms"/*.rpm
  sudo systemctl enable docker
  sudo systemctl start docker

  echo "[setup] Docker version:"
  docker --version || true
}

load_docker_images() {
  require_dir "${ROOT_DIR}/docker-images"
  echo "[setup] Loading pre-exported Docker images..."

  shopt -s nullglob
  local any_loaded=0
  for tar in "${ROOT_DIR}"/docker-images/*.tar; do
    echo "[setup] docker load -i $(basename "$tar")"
    docker load -i "$tar"
    any_loaded=1
  done

  if [ "$any_loaded" -eq 0 ]; then
    echo "[setup] No docker images found in docker-images/"
    exit 1
  fi
}

restore_ollama_models_if_present() {
  local vol_name="loomin-ollama-data"
  local tar_path="${ROOT_DIR}/ollama-data.tar"

  if [ -f "${tar_path}" ]; then
    echo "[setup] Restoring Ollama data snapshot into volume: ${vol_name}"

    docker volume inspect "${vol_name}" >/dev/null 2>&1 || docker volume create "${vol_name}" >/dev/null

    docker run --rm \
      -v "${vol_name}:/root/.ollama" \
      -v "${ROOT_DIR}:/pkg:ro" \
      ollama/ollama:latest \
      sh -c "tar -xf /pkg/ollama-data.tar -C /root/.ollama"
  else
    echo "[setup] ERROR: Required Ollama data snapshot not found: ${tar_path}"
    echo "[setup] The bootstrap package must include deploy/ollama-data.tar"
    exit 1
  fi
}

start_stack() {
  echo "[setup] Starting stack with docker-compose..."
  require_dir "${ROOT_DIR}"
  docker compose -f "${ROOT_DIR}/docker-compose.yml" up -d --remove-orphans
}

install_docker_from_rpms
load_docker_images
restore_ollama_models_if_present
start_stack

echo "[setup] Done."

