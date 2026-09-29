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

def test_upload_multipage_photos():
    """Test caricamento e compilazione multipagina di più foto da cellulare."""
    from PIL import Image

    img1 = Image.new("RGB", (200, 300), color="red")
    buf1 = io.BytesIO()
    img1.save(buf1, format="JPEG")
    buf1.seek(0)

    img2 = Image.new("RGB", (200, 300), color="yellow")
    buf2 = io.BytesIO()
    img2.save(buf2, format="JPEG")
    buf2.seek(0)

    files = [
        ("files", ("foto_pag1.jpg", buf1, "image/jpeg")),
        ("files", ("foto_pag2.jpg", buf2, "image/jpeg")),
    ]

    res = client.post(
        "/api/documents/upload-multipage-photos",
        files=files,
        data={"thread_id": "general"}
    )
    assert res.status_code == 201
    data = res.json()
    assert data["document_id"] > 0
    assert data["title"]
    assert "foto" in data["chat_reply"].lower() or "multipagina" in data["chat_reply"].lower()
    assert data["file_url"].endswith(".pdf")


def test_upload_batch_without_chat_message_and_batch_record_chat():
    """Test del flusso a blocchi: caricamento batch senza creare messaggi di chat e successiva registrazione aggregata."""
    fake_pdf_1 = io.BytesIO(b"%PDF-1.4 blocco 1 doc 1")
    fake_pdf_2 = io.BytesIO(b"%PDF-1.4 blocco 1 doc 2")

    files = [
        ("files", ("bolletta_luce_blocco.pdf", fake_pdf_1, "application/pdf")),
        ("files", ("fattura_gas_blocco.pdf", fake_pdf_2, "application/pdf")),
    ]

    # Caricamento blocco con save_chat_message=False
    res = client.post(
        "/api/documents/upload-batch",
        files=files,
        data={"thread_id": "general", "save_chat_message": "false"}
    )
    assert res.status_code == 201
    data = res.json()
    assert data["success"] is True
    assert data["count"] == 2
    doc_ids = [d["id"] for d in data["documents"]]
    assert len(doc_ids) == 2

    # Registrazione aggregata finale via /api/documents/batch-record-chat
    record_res = client.post(
        "/api/documents/batch-record-chat",
        json={
            "document_ids": doc_ids,
            "thread_id": "general",
            "total_files_count": 2
        }
    )
    assert record_res.status_code == 200
    rec_data = record_res.json()
    assert rec_data["success"] is True
    assert rec_data["count"] == 2
    assert "2 documenti" in rec_data["chat_reply"] or "documenti" in rec_data["chat_reply"]
    assert len(rec_data["documents"]) == 2

