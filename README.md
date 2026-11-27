# Document library frontend

A responsive shadcn/ui interface for one-page printed scans. Upload JPG or PNG images, extract English text, search, review, correct, export, and delete pages.

## Run

```sh
npm install
npm run dev
```

The standalone experience uses IndexedDB and a bundled, on-device English OCR model. OCR assets are copied into `public/ocr` before development and production builds. OCR stays inside the browser unless `VITE_OCR_ENDPOINT` is configured.

Set `VITE_API_BASE_URL` to use the authenticated backend adapter. When unset, documents are browser-local. See `.env.example`.

## Backend contract

The existing OCR service accepts `POST /tesseract` as `multipart/form-data` with a file field named `file` and an `options` JSON string such as `{"languages":["eng"],"pageSegmentationMethod":3}`. Its successful response contains `data.stdout`, the extracted text. Configure `VITE_OCR_ENDPOINT` with the full endpoint URL to send images directly to it. The OCR host must allow browser requests from the frontend origin when the service is cross-origin.

The authenticated library adapter expects these routes relative to `VITE_API_BASE_URL`:

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/session` | Return `{ "email": "..." }`, or 401 when signed out |
| POST | `/session` | Accept `{ "email": "...", "password": "..." }`, set an HTTP-only session cookie, return the session |
| DELETE | `/session` | End the session |
| GET | `/documents?q=...` | Return matching document records |
| POST | `/documents` | Accept multipart `file` and `title`, create a queued page, return its record |
| GET | `/documents/:id/image` | Stream the original image |
| PATCH | `/documents/:id` | Update `text`, `title`, or `starred` |
| DELETE | `/documents/:id` | Delete document, image, extracted text, and index record |
| POST | `/documents/:id/retry` | Retry a failed OCR job |

A document record follows the `Page` shape in `src/lib/types.ts`. The backend should update `status` as its background worker processes uploads. The worker can forward each stored image to the existing OCR service using the multipart contract above, save `data.stdout`, then index the corrected text. The frontend polls for status changes and searches through `/documents?q=...`.

Use same-origin deployment or enable credentialed CORS for the frontend origin. Provide secure, HTTP-only session cookies with an appropriate CSRF strategy. Enforce user ownership for every document route. Apply the proposal's one-page scope, image-size bound, English language scope, bounded retries, and worker concurrency limits on the server too.

## shadcn/ui

This is a Vite and React app configured with the shadcn/ui New York style and CSS variable theme in `components.json`. The open-code Button, Input, Textarea, Badge, Dialog, and Dropdown Menu components live in `src/components/ui`. Their source comes from the official shadcn/ui registry.

## Checks

`npm run build` runs TypeScript checking and generates production assets. The development preview was also checked in Chrome at desktop and mobile widths, including upload, OCR, text correction, search after reload, export, delete, filters, and view switching.

Registration uses `POST /accounts` with `{ "email": "...", "password": "..." }` and returns a signed-in session. The backend must enforce password policy, hash passwords, rate-limit attempts, and issue the same secure session cookie as login. The profile menu shows the five most recently uploaded pages from the current library response.
