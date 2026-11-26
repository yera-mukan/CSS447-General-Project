import argparse
import statistics
import time
from datetime import datetime

import httpx


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Measure document OCR queue and end-to-end latency"
    )
    parser.add_argument("--image", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--token", required=True)
    parser.add_argument("--count", type=int, default=5)
    args = parser.parse_args()
    samples = []
    successes = 0
    with httpx.Client(
        base_url=args.base_url, headers={"Authorization": f"Bearer {args.token}"}, timeout=10
    ) as client:
        for _ in range(args.count):
            started = time.monotonic()
            with open(args.image, "rb") as image:
                response = client.post("/api/v1/documents", files={"file": (args.image, image)})
            response.raise_for_status()
            document_id = response.json()["id"]
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                detail = client.get(f"/api/v1/documents/{document_id}").json()
                if detail["status"] in {"ready", "failed"}:
                    break
                time.sleep(0.5)
            if detail["status"] == "ready":
                successes += 1
                queued = client.get(f"/api/v1/documents/{document_id}").json()
                created = datetime.fromisoformat(queued["created_at"])
                claimed = datetime.fromisoformat(detail["processing_started_at"])
                finished = datetime.fromisoformat(detail["processed_at"])
                samples.append(
                    (
                        claimed.timestamp() - created.timestamp(),
                        finished.timestamp() - claimed.timestamp(),
                        time.monotonic() - started,
                    )
                )
    print(f"success_rate={successes / args.count:.1%} ({successes}/{args.count})")
    if samples:
        for label, index in (
            ("queue_wait_s", 0),
            ("processing_s", 1),
            ("upload_to_searchable_s", 2),
        ):
            print(f"{label}_mean={statistics.mean(row[index] for row in samples):.3f}")


if __name__ == "__main__":
    main()
