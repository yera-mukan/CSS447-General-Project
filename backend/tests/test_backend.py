import io
import os
import time
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
