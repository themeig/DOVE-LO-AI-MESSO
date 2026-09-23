# tests/test_documents_drive.py
import io
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app
from app.models.database import init_db, get_session_maker, Document

client = TestClient(app)

def setup_function():
    init_db()
    client.post("/api/drive/disconnect")

def teardown_function():
    client.post("/api/drive/disconnect")

def test_document_upload_with_active_drive():
    init_db()
    # 1. Attiva il drive mock tramite callback
    client.get("/api/drive/callback?code=test_code")

    # 2. Carica una bolletta
    dummy_pdf = io.BytesIO(b"%PDF-1.4 test enel bill for drive upload")
    res = client.post(
        "/api/documents/upload",
        files={"file": ("bolletta_luce.pdf", dummy_pdf, "application/pdf")},
        data={"thread_id": "general"}
    )
    assert res.status_code in (200, 201)
    data = res.json()

    # 3. Verifica presenza campi Drive nel ritorno e nel database
    assert "drive_file_id" in data
    assert data["drive_file_id"] is not None
    assert "drive_web_url" in data
    assert data["drive_web_url"] is not None
    assert "drive.google.com" in data["drive_web_url"] or "drive-mock" in data["drive_file_id"]

    # Verifica nel database
    SessionLocal = get_session_maker()
    with SessionLocal() as db:
        doc = db.query(Document).filter(Document.id == data["document_id"]).first()
        assert doc is not None
        assert doc.drive_file_id == data["drive_file_id"]
        assert doc.drive_web_url == data["drive_web_url"]

    # 4. Verifica upload batch
    dummy2 = io.BytesIO(b"%PDF-1.4 second document for batch test")
    res_batch = client.post(
        "/api/documents/upload-batch",
        files=[("files", ("f24.pdf", dummy2, "application/pdf"))],
        data={"thread_id": "general"}
    )
    assert res_batch.status_code in (200, 201)
    batch_data = res_batch.json()
    assert "documents" in batch_data
    assert len(batch_data["documents"]) > 0
    assert batch_data["documents"][0].get("drive_web_url") is not None
    assert batch_data["documents"][0].get("drive_file_id") is not None

    # Cleanup: disconnetti
    client.post("/api/drive/disconnect")

def test_document_upload_with_disconnected_drive():
    init_db()
    client.post("/api/drive/disconnect")

    dummy_pdf = io.BytesIO(b"%PDF-1.4 disconnected test pdf")
    res = client.post(
        "/api/documents/upload",
        files={"file": ("documento_offline.pdf", dummy_pdf, "application/pdf")},
        data={"thread_id": "general"}
    )
    assert res.status_code in (200, 201)
    data = res.json()
    assert "drive_file_id" in data
    assert data["drive_file_id"] is None
    assert "drive_web_url" in data
    assert data["drive_web_url"] is None

def test_document_upload_batch_disconnected_drive():
    init_db()
    client.post("/api/drive/disconnect")

    dummy_pdf = io.BytesIO(b"%PDF-1.4 disconnected batch pdf")
    res_batch = client.post(
        "/api/documents/upload-batch",
        files=[("files", ("offline_batch.pdf", dummy_pdf, "application/pdf"))],
        data={"thread_id": "general"}
    )
    assert res_batch.status_code in (200, 201)
    data = res_batch.json()
    assert data["success"] is True
    assert len(data["documents"]) == 1
    assert data["documents"][0].get("drive_file_id") is None
    assert data["documents"][0].get("drive_web_url") is None

def test_document_upload_drive_error_fallback():
    init_db()
    client.get("/api/drive/callback?code=test_code")

    with patch("app.services.drive_service.MockGoogleDriveService.upload_file", side_effect=Exception("Drive API network failure")):
        dummy_pdf = io.BytesIO(b"%PDF-1.4 failing drive upload")
        res = client.post(
            "/api/documents/upload",
            files={"file": ("doc_fail.pdf", dummy_pdf, "application/pdf")},
            data={"thread_id": "general"}
        )
        assert res.status_code in (200, 201)
        data = res.json()
        assert data["drive_file_id"] is None
        assert data["drive_web_url"] is None

    client.post("/api/drive/disconnect")


def test_document_upload_with_local_only_mode():
    init_db()
    # 1. Connetti Drive
    client.get("/api/drive/callback?code=test_code")
    
    # 2. Imposta storage_mode su 'local_only'
    res_mode = client.patch("/api/drive/settings", json={"storage_mode": "local_only"})
    assert res_mode.status_code == 200
    assert res_mode.json()["storage_mode"] == "local_only"

    # 3. Carica documento singolo
    dummy_pdf = io.BytesIO(b"%PDF-1.4 test local only mode document")
    res = client.post(
        "/api/documents/upload",
        files={"file": ("contratto_privato.pdf", dummy_pdf, "application/pdf")},
        data={"thread_id": "general"}
    )
    assert res.status_code in (200, 201)
    data = res.json()

    # Verifica che NON sia stato caricato su Drive
    assert "drive_file_id" in data
    assert data["drive_file_id"] is None
    assert "drive_web_url" in data
    assert data["drive_web_url"] is None

    # Verifica nel database
    SessionLocal = get_session_maker()
    with SessionLocal() as db:
        doc = db.query(Document).filter(Document.id == data["document_id"]).first()
        assert doc is not None
        assert doc.drive_file_id is None
        assert doc.drive_web_url is None

    # 4. Verifica batch upload in modalità local_only
    dummy_batch = io.BytesIO(b"%PDF-1.4 batch local only")
    res_batch = client.post(
        "/api/documents/upload-batch",
        files=[("files", ("batch_local.pdf", dummy_batch, "application/pdf"))],
        data={"thread_id": "general"}
    )
    assert res_batch.status_code in (200, 201)
    batch_data = res_batch.json()
    assert batch_data["documents"][0].get("drive_file_id") is None
    assert batch_data["documents"][0].get("drive_web_url") is None

    # Pulizia
    client.post("/api/drive/disconnect")
