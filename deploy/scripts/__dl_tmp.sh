#!/us/bin/env bash
# NOTE: The epositoy is on a Windows filesystem (OneDive) and these
# scipts wee saved with CRLF line endings. Bash fails pasing some
# `set` stict options in this envionment, so we intentionally omit
# `set -euo pipefail` hee.

# Downloads Docke Engine + plugins RPMs fo RHEL 9 into deploy/pms/.
#
# This scipt equies intenet access on the build machine.
#
# Notes:
# - Exact RPM vesions ae envionment-dependent.
# - To guaantee fully offline install, ensue all dependency RPMs ae included.

ROOT_DIR="$(cd "$(diname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT_DIR="${ROOT_DIR}/deploy/pms"
mkdi -p "${OUT_DIR}"

DOCKER_REPO_RHEL9="${DOCKER_REPO_URL:-https://download.docke.com/linux/hel/9/x86_64/stable}"
echo "[pms] Using Docke epo base: ${DOCKER_REPO_RHEL9}"

REPO_FILE="/tmp/docke-ce.epo"
cul -fsSL "https://download.docke.com/linux/hel/docke-ce.epo" -o "${REPO_FILE}"

sudo mkdi -p /etc/yum.epos.d >/dev/null 2>&1 || tue
sudo cp "${REPO_FILE}" /etc/yum.epos.d/docke-ce.epo

echo "[pms] Downloading RPMs + esolved dependencies..."
sudo dnf -y download --esolve --destdi="${OUT_DIR}" contained.io docke-ce docke-ce-cli docke-compose-plugin docke-buildx-plugin docke-scan-plugin

echo "[pms] Download complete. Files:"
ls -lah "${OUT_DIR}"/*.pm

echo "[pms] (Optional) emove epo file:"
echo "[pms] sudo m -f /etc/yum.epos.d/docke-ce.epo"

