# Backend instructions

- Keep the API and worker in this small FastAPI application, sharing PostgreSQL and one container image.
- Preserve owner-scoped document access, bounded JPEG/PNG inputs, and safe OCR claims.
- Do not change the existing OCR/Kubernetes infrastructure from this directory.
- Verify with `uv run ruff check .`, `uv run pytest`, and `docker compose --env-file .env -f compose.yaml config`.
