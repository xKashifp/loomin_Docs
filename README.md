# Loomin-Docs

Loomin-Docs is a self-contained, air-gapped collaborative Markdown editor with an AI assistant sidebar powered by a local Ollama model and local RAG (FAISS + embeddings).

## Repository layout

- `frontend/` React (TypeScript) UI
- `backend/` FastAPI backend (FAISS + SQLite + Ollama integration)
- `deploy/` Docker compose stack and offline bootstrap

## Offline evaluation (RHEL 9, no internet)

1. On the target VM, copy the provided bootstrap archive contents into a directory (for example `/opt/loomin-docs`).
2. Run:
   - `chmod +x deploy/setup.sh`
   - `sudo ./deploy/setup.sh`
3. Then open the frontend:
   - `http://<vm-ip>:3000`
4. Backend API:
   - `http://<vm-ip>:8000/health`

## Offline verification (faithfulness)

After the stack is running, you can run:

```bash
python backend/scripts/verify_faithfulness.py
```

If running from a different machine/container, set:
- `BACKEND_BASE_URL` (default `http://localhost:8000`)
- `VERIFY_MODEL_ID` (default `loomin-llama3`)

## Local development (requires network to install deps)

Docker is recommended:
1. `docker compose -f deploy/docker-compose.yml up --build`

## Notes

- Model weights and Docker images must be side-loaded via the bootstrap package.
- The backend supports upload/indexing of `.pdf`, `.md`, and `.txt` files for grounded citations.

## Architecture diagram

Source diagram is in `deploy/architecture.mmd`.

If you have Mermaid CLI installed, you can render a PNG:

```bash
npx @mermaid-js/mermaid-cli -i deploy/architecture.mmd -o deploy/architecture.png
```

