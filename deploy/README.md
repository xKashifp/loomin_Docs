# Offline Bootstrap (RHEL 9)

This directory contains:
- `docker-compose.yml` — runs `ollama`, `backend`, and `frontend`
- `setup.sh` — installs Docker from local RPMs, side-loads Docker images, restores the Ollama model data, then starts Compose

## Expected bootstrap artifacts

When you package the archive for the evaluation VM, ensure this layout:

- `deploy/setup.sh`
- `deploy/rpms/*.rpm`  
  Docker Engine + docker-compose-plugin RPMs for RHEL 9
- `deploy/docker-images/*.tar`  
  Exported docker images for offline loading (must include at least `ollama/ollama:latest`, `loomin-backend`, and `loomin-frontend`)
- `deploy/ollama-data.tar` (required for AI)  
  A tar snapshot of Ollama's `/root/.ollama` directory (the contents of the directory)

The `setup.sh` script will:
1. `dnf install` the RPMs in `rpms/`
2. `docker load` every `*.tar` in `docker-images/`
3. If `ollama-data.tar` exists, restore it into the Docker volume `loomin-ollama-data`
4. Run `docker compose -f docker-compose.yml up -d`

## How to generate the offline artifacts (build machine, with internet)

Run these scripts in order from the repo root (`loomin_docs/`):

1. Download Docker RPMs:
   - `bash deploy/scripts/download_docker_rpms_rhel9.sh`
2. Build and export Docker images:
   - `bash deploy/scripts/build_and_export_images.sh`
3. Generate Ollama snapshot (includes chat model + embedding model):
   - `bash deploy/scripts/generate_ollama_data_tar.sh`
4. Package into a single bootstrap archive:
   - `bash deploy/scripts/package_bootstrap.sh`

## Run on a clean VM

1. Copy the archive contents to a directory, e.g. `/opt/loomin-docs`
2. Run:
   - `chmod +x /opt/loomin-docs/deploy/setup.sh`
   - `sudo /opt/loomin-docs/deploy/setup.sh`
3. Open the editor:
   - `http://<vm-ip>:3000`
4. Backend health:
   - `http://<vm-ip>:8000/health`

## Architecture diagram

The Mermaid source is in `deploy/architecture.mmd`. Render it to PNG using Mermaid CLI if available:

```bash
npx @mermaid-js/mermaid-cli -i deploy/architecture.mmd -o deploy/architecture.png
```

