import io
from datetime import date
from fastapi.testclient import TestClient

from app.main import app
from app.models.database import init_db, get_engine, get_session_maker, Document, GoogleDriveCredential
from app.services.calendar_service import set_calendar_service, MockGoogleCalendarService

client = TestClient(app)

def setup_module():
    init_db()
    set_calendar_service(MockGoogleCalendarService())

def test_calendar_status_disconnected():
    # Assicura disconnessione preliminare
    client.post("/api/drive/disconnect")
    res = client.get("/api/calendar/status")
    assert res.status_code == 200
    data = res.json()
    assert data["connected"] is False
    assert data["user_email"] is None
    assert "Dove Lo AI Messo - Scadenze" in data["calendar_name"]

def test_calendar_sync_disconnected_returns_400():
    client.post("/api/drive/disconnect")
    res = client.post("/api/calendar/sync")
    assert res.status_code == 400
    assert "non collegato" in res.json()["detail"].lower()

def test_calendar_sync_connected():
    # Connetti account Google tramite callback mock
    client.get("/api/drive/callback?code=mock_code")

    # Inserisci un documento con data di scadenza
    engine = get_engine()
    SessionLocal = get_session_maker(engine)
    with SessionLocal() as db:
        doc = Document(
            title="Bolletta A2A Ottobre",
            doc_type="bolletta",
            amount=88.50,
            due_date=date(2026, 10, 31),
            status="da_pagare",
            summary="Bolletta gas ottobre",
            file_path="storage/uploads/fake_a2a.pdf",
            file_type="pdf",
        )
        db.add(doc)
        db.commit()
        doc_id = doc.id

    # Richiedi la sincronizzazione in blocco
    res_sync = client.post("/api/calendar/sync")
    assert res_sync.status_code == 200
    sync_data = res_sync.json()
    assert sync_data["success"] is True
    assert sync_data["synced_count"] >= 1
    assert "mock-cal" in sync_data["calendar_id"]

    # Verifica che il doc ora abbia google_calendar_event_id
    with SessionLocal() as db:
        updated_doc = db.query(Document).filter(Document.id == doc_id).first()
        assert updated_doc.google_calendar_event_id is not None
        assert "mock-cal-ev-" in updated_doc.google_calendar_event_id

    # Test sync singolo documento
    res_single = client.post(f"/api/calendar/sync/{doc_id}")
    assert res_single.status_code == 200
    assert res_single.json()["success"] is True
    assert res_single.json()["event_id"] is not None

    # Test eliminazione evento da calendario
    res_del = client.delete(f"/api/calendar/events/{doc_id}")
    assert res_del.status_code == 200
    assert res_del.json()["success"] is True

    # Verifica rimozione riferimento in DB
    with SessionLocal() as db:
        cleared_doc = db.query(Document).filter(Document.id == doc_id).first()
        assert cleared_doc.google_calendar_event_id is None

    # Cleanup credenziale
    client.post("/api/drive/disconnect")

def test_calendar_sync_single_errors():
    # 400 se disconnesso
    client.post("/api/drive/disconnect")
    res = client.post("/api/calendar/sync/999999")
    assert res.status_code == 400

    # Connetti
    client.get("/api/drive/callback?code=mock_code")

    # 404 se documento inesistente
    res_404 = client.post("/api/calendar/sync/999999")
    assert res_404.status_code == 404

    # 400 se documento senza scadenza
    engine = get_engine()
    SessionLocal = get_session_maker(engine)
    with SessionLocal() as db:
        doc_no_due = Document(
            title="Foto Chiavi Studio",
            doc_type="foto_oggetto",
            status="archiviato",
            summary="Foto delle chiavi nello studio",
            file_path="storage/uploads/fake_chiavi.jpg",
            file_type="jpg",
        )
        db.add(doc_no_due)
        db.commit()
        no_due_id = doc_no_due.id

    res_no_due = client.post(f"/api/calendar/sync/{no_due_id}")
    assert res_no_due.status_code == 400

    # Cleanup
    client.post("/api/drive/disconnect")

def test_document_upload_auto_syncs_calendar_when_connected():
    # Connetti
    client.get("/api/drive/callback?code=mock_code")

    fake_pdf = io.BytesIO(b"%PDF-1.4 fake invoice content for auto sync")
    res = client.post(
        "/api/documents/upload",
        files={"file": ("fattura_scadenza.pdf", fake_pdf, "application/pdf")},
    )
    assert res.status_code == 201
    data = res.json()
    assert "google_calendar_event_id" in data
    assert data["google_calendar_event_id"] is not None

    # Cleanup
    client.post("/api/drive/disconnect")
