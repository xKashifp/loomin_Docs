#!/usr/bin/env bash
set -euo pipefail

# Downloads Docker Engine + plugins RPMs for RHEL 9 into deploy/rpms/.
#
# This script requires internet access on the build machine.
#
# Notes:
# - Exact RPM versions are environment-dependent.
# - To guarantee fully offline install, ensure all dependency RPMs are included.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT_DIR="${ROOT_DIR}/deploy/rpms"
mkdir -p "${OUT_DIR}"

SUDO=""
if [ "$(id -u)" -ne 0 ] && command -v sudo >/dev/null 2>&1; then
  SUDO="sudo"
fi

DOCKER_REPO_RHEL9="${DOCKER_REPO_URL:-https://download.docker.com/linux/rhel/9/x86_64/stable}"
echo "[rpms] Using Docker repo base: ${DOCKER_REPO_RHEL9}"

REPO_FILE="/tmp/docker-ce.repo"
curl -fsSL "https://download.docker.com/linux/rhel/docker-ce.repo" -o "${REPO_FILE}"

${SUDO} mkdir -p /etc/yum.repos.d >/dev/null 2>&1 || true
${SUDO} cp "${REPO_FILE}" /etc/yum.repos.d/docker-ce.repo

echo "[rpms] Downloading RPMs + resolved dependencies..."
${SUDO} dnf -y download --resolve --destdir="${OUT_DIR}" \
  containerd.io docker-ce docker-ce-cli docker-compose-plugin docker-buildx-plugin

# docker-scan-plugin is optional and may not exist for the repo snapshot you're using.
${SUDO} dnf -y download --resolve --destdir="${OUT_DIR}" docker-scan-plugin || true

echo "[rpms] Download complete. Files:"
ls -lah "${OUT_DIR}"/*.rpm

echo "[rpms] (Optional) remove repo file:"
echo "[rpms] sudo rm -f /etc/yum.repos.d/docker-ce.repo"

