"""
Test suite per il servizio Activity Ledger (registro eventi condivisi).
"""
import pytest
from sqlalchemy.orm import Session
from app.models.database import get_engine, init_db, Group, User, ActivityEvent
from app.services.activity_service import record_activity_event, list_group_activity_feed


@pytest.fixture
def db_session():
    engine = get_engine("sqlite:///:memory:")
    init_db(engine)
    with Session(engine) as session:
        user = User(id="user-act-1", email="leo@test.it", full_name="Leo")
        group = Group(id="group-act-1", name="Famiglia", invite_code="FAM-1122", created_by=user.id)
        session.add_all([user, group])
        session.commit()
        yield session


def test_record_activity_event(db_session):
    event = record_activity_event(
        db=db_session,
        group_id="group-act-1",
        actor_user_id="user-act-1",
        actor_name="Leo",
        event_type="DOCUMENT_UPLOADED",
        title="Leo ha caricato la Bolletta Enel",
        content="Importo: 64,20 € - Scadenza 28/10/2026",
        payload={"amount": 64.20, "due_date": "2026-10-28"}
    )
    assert event.id is not None
    assert event.event_type == "DOCUMENT_UPLOADED"
    assert event.actor_name == "Leo"
    assert event.payload["amount"] == 64.20


def test_list_group_activity_feed(db_session):
    record_activity_event(
        db=db_session,
        group_id="group-act-1",
        actor_name="Leo",
        event_type="DOCUMENT_UPLOADED",
        title="Evento 1"
    )
    record_activity_event(
        db=db_session,
        group_id="group-act-1",
        actor_name="Leo",
        event_type="DOCUMENT_PAID",
        title="Evento 2"
    )

    feed = list_group_activity_feed(db_session, "group-act-1", limit=10)
    assert len(feed) == 2
    # L'evento più recente è il primo
    assert feed[0].title == "Evento 2"
    assert feed[1].title == "Evento 1"


def test_document_patch_status_logs_activity_event():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.models.database import Document, SessionLocal

    client = TestClient(app)
    db = SessionLocal()
    try:
        doc = Document(
            title="Bolletta A2A Luce",
            file_path="uploads/fake_a2a.pdf",
            file_type="pdf",
            doc_type="bolletta",
            amount=85.50,
            status="da_pagare",
            group_id="group-act-1"
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
        doc_id = doc.id
    finally:
        db.close()

    res = client.patch(f"/api/documents/{doc_id}/status", json={"status": "quietanzato"})
    assert res.status_code == 200

    db = SessionLocal()
    try:
        events = list_group_activity_feed(db, "group-act-1", limit=10)
        paid_events = [e for e in events if e.event_type == "DOCUMENT_PAID" and e.document_id == doc_id]
        assert len(paid_events) == 1
        assert "Bolletta A2A Luce" in paid_events[0].title
    finally:
        db.close()
