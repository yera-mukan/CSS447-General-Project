# CSS447 Document Library Backend

FastAPI backend and single-concurrency worker for private, searchable printed-page images. The API stores images and durable OCR work in PostgreSQL and calls the existing OCR service.

## Start locally

Copy `.env.example` to `.env`, set `JWT_SECRET` to a random secret and set a local PostgreSQL password consistently in `POSTGRES_PASSWORD` and `DATABASE_URL`. Start from this directory with `docker compose --env-file .env -f compose.yaml up --build --wait`. The API is at `http://127.0.0.1:8000`, Swagger at `/docs`, and database health at `/health`. Alembic runs as the Compose migration service.

## API contract

All application routes use `/api/v1`. Register with `POST /auth/register` and `{"email":"student@example.edu","password":"correct horse battery"}`. Log in at `POST /auth/login` for a bearer token. `GET /auth/me` returns the authenticated account.

Upload one JPEG or PNG page to `POST /documents` as multipart `file`, optionally adding `title`. The `202` response includes document ID, title, filename, media type, `queued` status, attempts, error, and timestamps. Poll `GET /documents/{id}` for `queued`, `processing`, `ready`, or `failed`. The detail response adds `extracted_text` and `corrected_text`.

`GET /documents` lists the private library. `GET /documents/search?q=phrase` performs case-insensitive substring search and includes a text snippet. `GET /documents/{id}/image` returns the original private image. `PATCH /documents/{id}` takes `{"corrected_text":"edited text"}` and optionally `title`. `POST /documents/{id}/retry` retries failed OCR. `GET /documents/{id}/export` downloads effective text. `DELETE /documents/{id}` deletes the document and image. Detail responses include `processing_started_at` and `processed_at` for latency analysis.

## Settings

See `.env.example` for database, signing secret, CORS origins, OCR endpoint and timeouts, image limits, pending-job limits, attempt budget, and claim lease. OCR uses a 60-second total deadline, a 5-second connect timeout, and a 90-second lease. Local OCR traffic uses the internal Compose address `http://ocr-app:8884`. Do not use the remote unencrypted endpoint for private files.

## Checks and smoke test

Install development dependencies with `uv sync --extra dev`. Run `uv run ruff check .` and `uv run pytest`. Run the stack smoke test with a synthetic printed-English image: register, log in, upload, poll to ready, view image and extracted text, search, correct, confirm updated search, export, and delete. Check the OCR readiness endpoint independently at `http://127.0.0.1:8884/.well-known/health/ready` when using the supplied standalone OCR Compose file. OCR results come from `POST /tesseract`, not readiness.

For a deployment handoff, configure PostgreSQL, the API environment variables, the API service, and one worker with one OCR request at a time. The cluster OCR base URL is `http://ocr.ocr-lab.svc.cluster.local:8884`.

## Benchmark

Run `uv run python benchmark.py --image path/to/synthetic-page.png --base-url http://127.0.0.1:8000 --token TOKEN`. It reports queue wait, OCR processing time, upload-to-searchable latency, and success rate. Record the OCR image digest for each run with `docker image inspect ferraripupu/ocr-app:latest --format '{{index .RepoDigests 0}}'`.

The local verification used five synthetic uploads and measured mean queue wait of 0.703 s, processing of 0.415 s, and upload-to-searchable latency of 1.484 s. All five succeeded. See PLAN.md for the tested OCR digest and verification coverage.

Frontend clients can retrieve the schema from http://127.0.0.1:8000/openapi.json. Send the login token in the Authorization header for document requests. Set CORS_ORIGINS to the frontend origin before starting Compose.
