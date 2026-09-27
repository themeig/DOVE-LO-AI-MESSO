import io
import zipfile
from datetime import date
from fastapi.testclient import TestClient

from app.main import app
from app.models.database import (
    init_db,
    get_engine,
    get_session_maker,
    Document,
    GoogleDriveCredential,
)
from app.services.calendar_service import (
    set_calendar_service,
    MockGoogleCalendarService,
    get_calendar_service,
    auto_sync_calendar_event,
    auto_delete_calendar_event,
    auto_sync_all_deadlines,
)

client = TestClient(app)


def setup_module():
    init_db()
    set_calendar_service(MockGoogleCalendarService())


def setup_function():
    # Reset del mock prima di ogni test
    set_calendar_service(MockGoogleCalendarService())


def test_auto_sync_on_status_change_to_quietanzato_and_back():
    """Verifica che al cambio di stato in 'quietanzato' l'evento sul calendario sia aggiornato con [PAGATO] e viceversa."""
    # 1. Connetti account Google
    client.get("/api/drive/callback?code=mock_code")

    engine = get_engine()
    SessionLocal = get_session_maker(engine)
    with SessionLocal() as db:
        doc = Document(
            title="Bolletta Telefono TIM",
            doc_type="bolletta",
            amount=45.90,
            due_date=date(2026, 11, 15),
            status="da_pagare",
            category="utenze_bollette",
            category_label="Utenze & Bollette",
            summary="Bolletta fibra TIM novembre",
            file_path="storage/uploads/fake_tim.pdf",
            file_type="pdf",
        )
        db.add(doc)
        db.commit()
        doc_id = doc.id

    # Sincronizza inizialmente la scadenza su calendar
    res_sync = client.post(f"/api/calendar/sync/{doc_id}")
    assert res_sync.status_code == 200
    ev_id = res_sync.json()["event_id"]
    assert ev_id is not None

    mock_cal = get_calendar_service()
    event_data = mock_cal.events_db.get(ev_id)
    assert event_data is not None
    assert "[PAGATO]" not in event_data["title"]

    # 2. Segna il documento come PAGATO / QUIETANZATO tramite endpoint PATCH
    patch_res = client.patch(
        f"/api/documents/{doc_id}/status",
        json={"status": "quietanzato"}
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["status"] == "quietanzato"

    # 3. L'evento sul calendario deve essere stato aggiornato automaticamente con [PAGATO]
    updated_event = mock_cal.events_db.get(ev_id)
    assert updated_event is not None
    assert "[PAGATO]" in updated_event["title"]
    assert updated_event["status"] == "quietanzato"

    # 4. Riporta lo stato a da_pagare
    patch_res_back = client.patch(
        f"/api/documents/{doc_id}/status",
        json={"status": "da_pagare"}
    )
    assert patch_res_back.status_code == 200
    assert patch_res_back.json()["status"] == "da_pagare"

    # L'evento sul calendario non deve più avere [PAGATO]
    reverted_event = mock_cal.events_db.get(ev_id)
    assert "[PAGATO]" not in reverted_event["title"]
    assert reverted_event["status"] == "da_pagare"

    # Cleanup
    client.post("/api/drive/disconnect")


def test_auto_delete_calendar_event_on_single_doc_delete():
    """Verifica che eliminando un documento dal caveau, il suo evento su Google Calendar venga rimosso."""
    client.get("/api/drive/callback?code=mock_code")

    engine = get_engine()
    SessionLocal = get_session_maker(engine)
    with SessionLocal() as db:
        doc = Document(
            title="Fattura Commercialista",
            doc_type="fattura",
            amount=320.00,
            due_date=date(2026, 12, 10),
            status="da_pagare",
            summary="Consulenza contabile",
            file_path="storage/uploads/fake_commercialista.pdf",
            file_type="pdf",
        )
        db.add(doc)
        db.commit()
        doc_id = doc.id

    # Sincronizza
    res_sync = client.post(f"/api/calendar/sync/{doc_id}")
    ev_id = res_sync.json()["event_id"]
    mock_cal = get_calendar_service()
    assert ev_id in mock_cal.events_db

    # Elimina il documento via DELETE /api/documents/{id}
    del_res = client.delete(f"/api/documents/{doc_id}")
    assert del_res.status_code == 200

    # L'evento su Google Calendar deve essere stato rimosso
    assert ev_id not in mock_cal.events_db

    # Cleanup
    client.post("/api/drive/disconnect")


def test_auto_delete_calendar_event_on_bulk_delete():
    """Verifica che eliminando documenti in blocco, i rispettivi eventi su Google Calendar vengano rimossi."""
    client.get("/api/drive/callback?code=mock_code")

    engine = get_engine()
    SessionLocal = get_session_maker(engine)
    doc_ids = []
    with SessionLocal() as db:
        for i in range(2):
            doc = Document(
                title=f"Rata Finanziamento #{i+1}",
                doc_type="finanziamento",
                amount=150.00,
                due_date=date(2026, 11, 20 + i),
                status="da_pagare",
                summary=f"Rata #{i+1}",
                file_path=f"storage/uploads/fake_rata_{i+1}.pdf",
                file_type="pdf",
            )
            db.add(doc)
            db.commit()
            doc_ids.append(doc.id)

    mock_cal = get_calendar_service()
    ev_ids = []
    for did in doc_ids:
        res = client.post(f"/api/calendar/sync/{did}")
        eid = res.json()["event_id"]
        ev_ids.append(eid)
        assert eid in mock_cal.events_db

    # Esegui eliminazione bulk
    res_bulk = client.request(
        "DELETE",
        "/api/documents/bulk",
        json={"document_ids": doc_ids}
    )
    assert res_bulk.status_code == 200

    # Tutti gli eventi devono essere stati rimossi dal calendario
    for eid in ev_ids:
        assert eid not in mock_cal.events_db

    # Cleanup
    client.post("/api/drive/disconnect")


def test_auto_sync_on_rename_document():
    """Verifica che rinominando un documento con scadenza, il titolo su Google Calendar venga aggiornato."""
    client.get("/api/drive/callback?code=mock_code")

    engine = get_engine()
    SessionLocal = get_session_maker(engine)
    with SessionLocal() as db:
        doc = Document(
            title="Tassa Rifiuti TARI 2026",
            doc_type="tributi",
            amount=210.00,
            due_date=date(2026, 12, 1),
            status="da_pagare",
            summary="Avviso TARI",
            file_path="storage/uploads/fake_tari.pdf",
            file_type="pdf",
        )
        db.add(doc)
        db.commit()
        doc_id = doc.id

    # Sincronizza
    res_sync = client.post(f"/api/calendar/sync/{doc_id}")
    ev_id = res_sync.json()["event_id"]
    mock_cal = get_calendar_service()
    assert "TARI" in mock_cal.events_db[ev_id]["title"]

    # Rinomina documento via agent execute_tool
    from app.services.agent_service import AgenticChatService
    agent = AgenticChatService()
    with SessionLocal() as db:
        res_rename = agent.execute_tool(
            "rename_vault_document",
            {"document_id": doc_id, "new_title": "TARI Milano 2026 - Seconda Rata"},
            db=db,
            thread_id="general"
        )
        assert res_rename.get("success") is True

    # Verifica che l'evento su calendar sia aggiornato
    assert "TARI Milano 2026 - Seconda Rata" in mock_cal.events_db[ev_id]["title"]

    # Ricategorizza il documento
    with SessionLocal() as db:
        res_recar = agent.execute_tool(
            "recategorize_vault_document",
            {"document_id": doc_id, "category_label": "Tributi Comunali"},
            db=db,
            thread_id="general"
        )
        assert res_recar.get("success") is True

    # Verifica che la nuova categoria sia riflessa nel titolo dell'evento
    assert f"[{res_recar['new_category_label']}]" in mock_cal.events_db[ev_id]["title"]

    # Cleanup
    client.post("/api/drive/disconnect")


def test_auto_sync_all_on_oauth_connection():
    """Verifica che al collegamento dell'account Google, tutte le scadenze del caveau vengano sincronizzate automaticamente."""
    client.post("/api/drive/disconnect")

    engine = get_engine()
    SessionLocal = get_session_maker(engine)
    with SessionLocal() as db:
        doc = Document(
            title="Bolletta Acqua Publiacqua",
            doc_type="bolletta",
            amount=74.30,
            due_date=date(2026, 10, 25),
            status="da_pagare",
            summary="Utenza idrica",
            file_path="storage/uploads/fake_acqua.pdf",
            file_type="pdf",
        )
        db.add(doc)
        db.commit()
        doc_id = doc.id

    mock_cal = get_calendar_service()
    assert len(mock_cal.events_db) == 0

    # Collega account Google via callback
    res_cb = client.get("/api/drive/callback?code=mock_code")
    assert res_cb.status_code == 200

    # L'evento per il documento deve essere stato sincronizzato automaticamente
    with SessionLocal() as db:
        refreshed = db.query(Document).filter(Document.id == doc_id).first()
        assert refreshed.google_calendar_event_id is not None
        assert refreshed.google_calendar_event_id in mock_cal.events_db

    # Cleanup
    client.post("/api/drive/disconnect")


def test_auto_sync_on_archive_unzip(tmp_path):
    """Verifica che quando viene decompresso uno ZIP contenente documenti con scadenze, questi vengano sincronizzati su Google Calendar."""
    client.get("/api/drive/callback?code=mock_code")

    # Crea uno ZIP in memoria con un PDF fake che ha 'bolletta' nel nome
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w") as zf:
        zf.writestr("bolletta_luce_marzo.pdf", b"%PDF-1.4 Fake Enel bill content")
    zip_buf.seek(0)

    # Carica il file ZIP nel caveau
    res_upload = client.post(
        "/api/documents/upload",
        files={"file": ("archivio_bollette.zip", zip_buf, "application/zip")}
    )
    assert res_upload.status_code == 201
    zip_doc_id = res_upload.json()["document_id"]

    mock_cal = get_calendar_service()
    initial_event_count = len(mock_cal.events_db)

    # Decomprimi lo ZIP nel caveau
    from app.services.archive_service import unzip_document_to_vault
    engine = get_engine()
    SessionLocal = get_session_maker(engine)
    with SessionLocal() as db:
        extracted = unzip_document_to_vault(db=db, document_id=zip_doc_id)
        assert len(extracted) >= 1
        extracted_doc = extracted[0]
        # Se ha scadenza, deve avere google_calendar_event_id
        if extracted_doc.due_date:
            assert extracted_doc.google_calendar_event_id is not None
            assert extracted_doc.google_calendar_event_id in mock_cal.events_db

    # Cleanup
    client.post("/api/drive/disconnect")
