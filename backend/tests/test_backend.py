import io
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from PIL import Image, ImageDraw, ImageFont


def test_openapi(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "local-test-secret-not-used-for-signing")
    from app import app

    paths = app.openapi()["paths"]
    assert "post" in paths["/api/v1/documents"]
    assert "get" in paths["/api/v1/documents/search"]
    assert "delete" in paths["/api/v1/documents/{doc_id}"]


@pytest.mark.skipif(not os.getenv("SMOKE_URL"), reason="requires the running local OCR stack")
def test_real_ocr_library():
    image = Image.new("RGB", (1000, 200), "white")
    font = ImageFont.load_default(size=48)
    ImageDraw.Draw(image).text((40, 50), "Library OCR sample", font=font, fill="black")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    raw = buffer.getvalue()
    with httpx.Client(base_url=os.environ["SMOKE_URL"], timeout=15) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/docs").status_code == 200

        def account():
            credentials = {"email": f"{uuid4().hex}@example.com", "password": "example-password"}
            assert client.post("/api/v1/auth/register", json=credentials).status_code == 201
            token = client.post("/api/v1/auth/login", json=credentials).raise_for_status().json()
            return {"Authorization": f"Bearer {token['access_token']}"}

        owner, other = account(), account()
        root = "/api/v1/documents"
        bad = {"file": ("broken.png", b"invalid", "image/png")}
        assert client.post(root, headers=owner, files=bad).status_code == 422
        result = client.post(root, headers=owner, files={"file": ("page.png", raw, "image/png")})
        assert result.status_code == 202, result.text
        path = f"{root}/{result.json()['id']}"
        try:
            for _ in range(120):
                detail = client.get(path, headers=owner).raise_for_status().json()
                if detail["status"] in {"ready", "failed"}:
                    break
                time.sleep(0.5)
            assert detail["status"] == "ready", detail
            assert "library ocr sample" in detail["extracted_text"].lower()
            assert detail["processing_started_at"] and detail["processed_at"]
            assert client.get(f"{path}/image", headers=owner).content == raw
            assert client.get(f"{path}/image", headers=other).status_code == 404
            assert client.get(f"{root}/search", headers=owner, params={"q": "OCR sample"}).json()[
                "items"
            ]
            corrected = f"Corrected {uuid4().hex}"
            client.patch(path, headers=owner, json={"corrected_text": corrected}).raise_for_status()
            search = client.get(f"{root}/search", headers=owner, params={"q": corrected})
            assert corrected in search.json()["items"][0]["snippet"]
            assert client.get(f"{path}/export", headers=owner).text == corrected
        finally:
            assert client.delete(path, headers=owner).status_code == 204
        assert client.get(f"{path}/image", headers=owner).status_code == 404
        assert not client.get(f"{root}/search", headers=owner, params={"q": corrected}).json()[
            "items"
        ]


@pytest.mark.skipif(not os.getenv("SMOKE_URL"), reason="requires the running local OCR stack")
def test_cross_user_access_for_every_document_route():
    with httpx.Client(base_url=os.environ["SMOKE_URL"], timeout=10) as client:

        def token():
            user = {"email": f"{uuid4().hex}@example.com", "password": "example-password"}
            client.post("/api/v1/auth/register", json=user).raise_for_status()
            result = client.post("/api/v1/auth/login", json=user).raise_for_status().json()
            return {"Authorization": f"Bearer {result['access_token']}"}

        owner, stranger = token(), token()
        image = Image.new("RGB", (20, 20), "white")
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        created = client.post(
            "/api/v1/documents",
            headers=owner,
            files={"file": ("access.png", buf.getvalue(), "image/png")},
        )
        created.raise_for_status()
        doc_id = created.json()["id"]
        root = f"/api/v1/documents/{doc_id}"
        try:
            for _ in range(100):
                if client.get(root, headers=owner).json()["status"] in {"ready", "failed"}:
                    break
                time.sleep(0.2)
            checks = [
                client.get(root, headers=stranger),
                client.get(f"{root}/image", headers=stranger),
                client.patch(root, headers=stranger, json={"title": "stolen"}),
                client.post(f"{root}/retry", headers=stranger),
                client.get(f"{root}/export", headers=stranger),
                client.delete(root, headers=stranger),
            ]
            assert [r.status_code for r in checks] == [404] * len(checks)
            listed = client.get("/api/v1/documents", headers=stranger).json()["items"]
            searched = client.get(
                "/api/v1/documents/search", headers=stranger, params={"q": "access"}
            ).json()["items"]
            assert doc_id not in {str(row["id"]) for row in listed + searched}
        finally:
            client.delete(root, headers=owner)


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="requires PostgreSQL")
def test_expired_lease_is_reclaimed_and_stale_token_cannot_finish():
    from sqlalchemy import update

    from app import Document, SessionLocal, User, claim_document

    with SessionLocal.begin() as db:
        user = User(email=f"{uuid4().hex}@example.com", password_hash="test-only")
        db.add(user)
        db.flush()
        document = Document(
            owner_id=user.id,
            title="lease",
            original_filename="x.png",
            mime_type="image/png",
            image_data=b"image",
            status="processing",
            attempts=1,
            claim_token="expired-token",
            lease_expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )
        db.add(document)
        db.flush()
        doc_id = document.id
    with SessionLocal() as db:
        claimed = claim_document(db)
    assert claimed and claimed[0] == doc_id and claimed[1] != "expired-token"
    with SessionLocal.begin() as db:
        result = db.execute(
            update(Document)
            .where(
                Document.id == doc_id,
                Document.status == "processing",
                Document.claim_token == "expired-token",
            )
            .values(status="ready", extracted_text="stale")
        )
        assert result.rowcount == 0
        db.execute(update(Document).where(Document.id == doc_id).values(status="failed"))
        db.execute(Document.__table__.delete().where(Document.id == doc_id))


@pytest.mark.skipif(not os.getenv("SMOKE_URL"), reason="requires the running local OCR stack")
def test_concurrent_pending_admission_limit():
    with httpx.Client(base_url=os.environ["SMOKE_URL"], timeout=30) as client:
        user = {"email": f"{uuid4().hex}@example.com", "password": "example-password"}
        client.post("/api/v1/auth/register", json=user).raise_for_status()
        login = client.post("/api/v1/auth/login", json=user).raise_for_status().json()
        headers = {"Authorization": f"Bearer {login['access_token']}"}

    def upload(_):
        with httpx.Client(base_url=os.environ["SMOKE_URL"], timeout=30) as client:
            return client.post(
                "/api/v1/documents",
                headers=headers,
                files={"file": ("queue.png", TEST_IMAGE, "image/png")},
            ).status_code

    TEST_IMAGE_BUFFER = io.BytesIO()
    Image.new("RGB", (30, 30), "white").save(TEST_IMAGE_BUFFER, format="PNG")
    TEST_IMAGE = TEST_IMAGE_BUFFER.getvalue()
    with ThreadPoolExecutor(max_workers=16) as pool:
        codes = list(pool.map(upload, range(16)))
    assert codes.count(202) <= 10
    assert codes.count(429) >= 6
