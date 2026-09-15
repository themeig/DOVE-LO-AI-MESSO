"""Test per il caricamento batch di piu file e cartelle."""
import io
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.models.database import init_db

client = TestClient(app)

def setup_module():
    init_db()

def test_upload_batch_multiple_documents():
    """Test caricamento simultaneo di piu documenti (PDF e immagini)."""
    fake_pdf_1 = io.BytesIO(b"%PDF-1.4 bolletta luce 1")
    fake_pdf_2 = io.BytesIO(b"%PDF-1.4 tributo f24 2")
    fake_img_1 = io.BytesIO(b"\xff\xd8\xff\xe0 fake jpeg 1")

    files = [
        ("files", ("bolletta_enel_settembre.pdf", fake_pdf_1, "application/pdf")),
        ("files", ("f24_imposte_2026.pdf", fake_pdf_2, "application/pdf")),
        ("files", ("foto_cassetto_chiavi.jpg", fake_img_1, "image/jpeg")),
    ]

    res = client.post(
        "/api/documents/upload-batch",
        files=files,
        data={"thread_id": "general"}
    )
    assert res.status_code == 201
    data = res.json()
    assert data["success"] is True
    assert data["count"] == 3
    assert len(data["documents"]) == 3
    assert "3 file" in data["chat_reply"] or "3 documenti" in data["chat_reply"] or "documenti" in data["chat_reply"]

    # Verifica che tutti e 3 i documenti abbiano id, title, file_url, download_url
    for doc in data["documents"]:
        assert doc["id"] > 0
        assert doc["title"]
        assert doc["file_url"]
        assert doc["download_url"]

def test_upload_batch_single_file_fallback():
    """Test caricamento batch con un singolo file."""
    fake_pdf = io.BytesIO(b"%PDF-1.4 singolo file test")
    files = [
        ("files", ("contratto_locazione.pdf", fake_pdf, "application/pdf")),
    ]

    res = client.post(
        "/api/documents/upload-batch",
        files=files,
        data={"thread_id": "general"}
    )
    assert res.status_code == 201
    data = res.json()
    assert data["success"] is True
    assert data["count"] == 1
    assert len(data["documents"]) == 1
