import pytest
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.models.database import init_db, get_engine, UIEvent, Document
from app.services.agent_service import AgentService

client = TestClient(app)

def setup_module():
    init_db()

def test_post_ui_telemetry_event():
    payload = {
        "thread_id": "general",
        "event_type": "CARD_RENDER_ERROR",
        "target_type": "document",
        "target_id": 99,
        "title": "Bolletta Enel Test",
        "error_details": "Failed to render card widget: missing element"
    }
    res = client.post("/api/telemetry/ui-event", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert "event_id" in data
    assert data["event_id"] > 0

def test_get_ui_telemetry_events():
    res = client.get("/api/telemetry/ui-events?thread_id=general")
    assert res.status_code == 200
    data = res.json()
    assert "events" in data
    assert len(data["events"]) > 0
    event = data["events"][0]
    assert event["event_type"] == "CARD_RENDER_ERROR"
    assert event["title"] == "Bolletta Enel Test"

def test_agent_telemetry_context_injection():
    engine = get_engine()
    with Session(engine) as db:
        # Create a document
        doc = Document(
            title="Patente di Guida B",
            file_path="uploads/patente.pdf",
            file_type="application/pdf",
            doc_type="documento_identita",
            summary="Patente di guida categoria B",
            thread_id="general"
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)

        # Log a UI render error for this document
        ui_ev = UIEvent(
            thread_id="general",
            event_type="CARD_RENDER_ERROR",
            target_type="document",
            target_id=doc.id,
            title=doc.title,
            error_details="Script rendering failure in WhatsApp bubble",
            created_at=datetime.utcnow()
        )
        db.add(ui_ev)
        db.commit()

        # Ask the agent when user reports not seeing the button
        agent = AgentService()
        recent_events = agent.get_recent_ui_events(db, "general")
        assert len(recent_events) > 0
        assert recent_events[0].title == "Patente di Guida B"

        # Check telemetry injection string
        note = agent._build_ui_telemetry_prompt_note(db, "general")
        assert "Patente di Guida B" in note
        assert f"/api/documents/{doc.id}/download" in note
