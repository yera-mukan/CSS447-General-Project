# Backend implementation and verification

- Foundation. The backend is on the local feature branch. The locked dependencies installed, the images built, PostgreSQL became healthy, and Alembic exited successfully.
- Core and library. The local stack passed the real OCR smoke test, covering registration, login, corrupt upload rejection, upload, polling, recognition, timestamps, original image retrieval, cross-user image denial, search, correction, export, and deletion.
- Delivery. Ruff lint and format checks passed. Linux pytest passed both tests. Windows pytest initially failed because Application Control blocked the SQLAlchemy native extension. The backend workflow passed local YAML parsing. GitHub Actions execution is pending.
- Persistence. All five ready benchmark documents still contained image bytes after a Compose restart.
- OCR. Readiness returned HTTP 200 and direct multipart OCR returned exit code 0 with the expected text. Tested image digest is ferraripupu/ocr-app@sha256:5fef8089504e53c0fc968a28e54bdb93f1fc9b5a87e40d8b4446dc8efe15431c.
- Benchmark. Five of five uploads succeeded. Mean queue wait was 0.703 s, mean processing was 0.415 s, and mean upload-to-searchable was 1.484 s.
- Remaining checks. Worker recovery after an interrupted claim, pending-job admission under concurrency, and exhaustive ownership tests remain unverified.
