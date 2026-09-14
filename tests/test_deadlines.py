from datetime import date, timedelta
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.models.database import get_db, Document
from app.services.agent_service import AgenticChatService, get_current_date_info, categorize_deadline
import app.mcp_server as mcp_mod

client = TestClient(app)

def test_get_current_date_helper_and_tool():
    info = get_current_date_info()
    assert "date" in info
    assert "formatted_italian" in info
    assert "weekday" in info
    assert "month" in info
    assert "year" in info
    assert "current_time" in info
    assert len(info["date"].split("-")) == 3
    assert info["year"] >= 2024

    agent = AgenticChatService()
    # Test execute_tool with get_current_date
    db = next(app.dependency_overrides[get_db]())
    try:
        tool_res = agent.execute_tool("get_current_date", {}, db)
        assert tool_res["date"] == info["date"]
        assert tool_res["formatted_italian"] == info["formatted_italian"]
    finally:
        db.close()


def test_categorize_deadline_urgency():
    today = date.today()

    # 1. Overdue
    cat_overdue = categorize_deadline(today - timedelta(days=5), today)
    assert cat_overdue["urgency"] == "overdue"
    assert cat_overdue["days_remaining"] == -5
    assert "SCADUTA DA 5 GIORNI" in cat_overdue["urgency_label"]

    # 2. Today
    cat_today = categorize_deadline(today, today)
    assert cat_today["urgency"] == "today"
    assert cat_today["days_remaining"] == 0
    assert cat_today["urgency_label"] == "SCADE OGGI!"

    # 3. Urgent (<= 3 days)
    cat_urgent = categorize_deadline(today + timedelta(days=2), today)
    assert cat_urgent["urgency"] == "urgent"
    assert cat_urgent["days_remaining"] == 2
    assert "SCADE TRA 2 GIORNI" in cat_urgent["urgency_label"]

    # 4. Soon (<= 7 days)
    cat_soon = categorize_deadline(today + timedelta(days=6), today)
    assert cat_soon["urgency"] == "soon"
    assert cat_soon["days_remaining"] == 6
    assert "IN SCADENZA TRA 6 GIORNI" in cat_soon["urgency_label"]

    # 5. Future (> 7 days)
    cat_future = categorize_deadline(today + timedelta(days=25), today)
    assert cat_future["urgency"] == "future"
    assert cat_future["days_remaining"] == 25
    assert "FUTURA" in cat_future["urgency_label"]


def test_get_upcoming_deadlines_countdown_in_agent():
    today = date.today()
    db: Session = next(app.dependency_overrides[get_db]())
    try:
        doc = Document(
            thread_id="test_deadlines_thread",
            title="Bolletta A2A Luce Test",
            issuer="A2A",
            doc_type="bolletta",
            amount=78.50,
            due_date=today + timedelta(days=2),
            status="da_pagare",
            file_path="storage/fake_a2a.pdf",
            file_type="pdf",
            summary="Bolletta energetica di test"
        )
        db.add(doc)
        db.commit()

        agent = AgenticChatService()
        out = agent.execute_tool("get_upcoming_deadlines", {}, db, thread_id="test_deadlines_thread")
        assert "today" in out
        assert out["deadlines_count"] >= 1
        found = next((d for d in out["deadlines"] if d["title"] == "Bolletta A2A Luce Test"), None)
        assert found is not None
        assert found["days_remaining"] == 2
        assert found["urgency"] == "urgent"
        assert "SCADE TRA 2 GIORNI" in found["urgency_label"]
    finally:
        db.close()


def test_mcp_date_and_deadlines_tools():
    date_str = mcp_mod.get_current_date()
    assert "Oggi è" in date_str
    assert "Data ISO:" in date_str

    deadlines_str = mcp_mod.get_upcoming_deadlines()
    assert isinstance(deadlines_str, str)
    assert "Scadenze e bollette da pagare in sospeso" in deadlines_str or "quietanzati" in deadlines_str

    context_str = mcp_mod.get_vault_context()
    assert "DATA E ORA ATTUALE:" in context_str


def test_api_deadlines_alerts_endpoint():
    today = date.today()
    db: Session = next(app.dependency_overrides[get_db]())
    try:
        # Create test documents
        doc_overdue = Document(
            thread_id="alerts_test_group",
            title="Tassa Rifiuti TARI Arretrata",
            issuer="Comune",
            doc_type="tributo",
            amount=120.00,
            due_date=today - timedelta(days=3),
            status="da_pagare",
            file_path="storage/tari_overdue.pdf",
            file_type="pdf",
            summary="Tari scaduta da saldare"
        )
        doc_due_soon = Document(
            thread_id="alerts_test_group",
            title="Bolletta Vodafone Fibra",
            issuer="Vodafone",
            doc_type="bolletta",
            amount=29.90,
            due_date=today + timedelta(days=3),
            status="da_pagare",
            file_path="storage/voda.pdf",
            file_type="pdf",
            summary="Fibra casa"
        )
        doc_future = Document(
            thread_id="alerts_test_group",
            title="Assicurazione Auto Annuale",
            issuer="Allianz",
            doc_type="assicurazione",
            amount=450.00,
            due_date=today + timedelta(days=45),
            status="da_pagare",
            file_path="storage/allianz.pdf",
            file_type="pdf",
            summary="Polizza RC auto"
        )
        doc_paid = Document(
            thread_id="alerts_test_group",
            title="Bolletta Gas Già Pagata",
            issuer="Eni",
            doc_type="bolletta",
            amount=85.00,
            due_date=today + timedelta(days=1),
            status="quietanzato",
            file_path="storage/eni_paid.pdf",
            file_type="pdf",
            summary="Quietanza gas"
        )
        db.add_all([doc_overdue, doc_due_soon, doc_future, doc_paid])
        db.commit()

        # 1. Query for alerts in thread with default days_ahead=7
        res = client.get("/api/deadlines/alerts?thread_id=alerts_test_group&days_ahead=7")
        assert res.status_code == 200
        data = res.json()
        assert data["has_alerts"] is True
        assert data["overdue_count"] == 1
        assert data["due_soon_count"] == 1
        assert data["total_alerts"] == 2
        assert round(data["total_amount"], 2) == round(120.00 + 29.90, 2)
        assert len(data["alerts"]) == 2

        # Verify ordering: overdue first
        assert data["alerts"][0]["title"] == "Tassa Rifiuti TARI Arretrata"
        assert data["alerts"][0]["days_remaining"] == -3
        assert data["alerts"][0]["urgency"] == "overdue"
        assert data["alerts"][1]["title"] == "Bolletta Vodafone Fibra"
        assert data["alerts"][1]["days_remaining"] == 3

        # 2. Query with days_ahead=60 includes doc_future
        res_60 = client.get("/api/deadlines/alerts?thread_id=alerts_test_group&days_ahead=60")
        assert res_60.status_code == 200
        data_60 = res_60.json()
        assert data_60["total_alerts"] == 3
        assert any(a["title"] == "Assicurazione Auto Annuale" for a in data_60["alerts"])

        # 3. Query without alerts for a non-existent thread
        res_empty = client.get("/api/deadlines/alerts?thread_id=non_existent_thread&days_ahead=7")
        assert res_empty.status_code == 200
        data_empty = res_empty.json()
        assert data_empty["has_alerts"] is False
        assert data_empty["total_alerts"] == 0
        assert data_empty["total_amount"] == 0.0

    finally:
        db.close()


def test_chat_date_and_deadlines_intent():
    # 1. Test question about current date (with space and without space / typo)
    for q in ["Che giorno è oggi?", "che giornoè?", "quanti ne abbiamo?"]:
        res_date = client.post("/api/chat", json={"message": q})
        assert res_date.status_code == 200
        date_reply = res_date.json()["reply"]
        info = get_current_date_info()
        assert str(info["year"]) in date_reply or info["month"].lower() in date_reply.lower()

    # 2. Test question about tomorrow
    res_tomorrow = client.post("/api/chat", json={"message": "che giorno è domani?"})
    assert res_tomorrow.status_code == 200
    assert "Domani sarà" in res_tomorrow.json()["reply"]

    # 3. Test question about yesterday
    res_yesterday = client.post("/api/chat", json={"message": "che giorno era ieri?"})
    assert res_yesterday.status_code == 200
    assert "Ieri era" in res_yesterday.json()["reply"]

    # 4. Test question about upcoming deadlines
    res_deadlines = client.post("/api/chat", json={"message": "Quali scadenze ho nei prossimi giorni?"})
    assert res_deadlines.status_code == 200
    deadlines_reply = res_deadlines.json()["reply"]
    assert "scadenz" in deadlines_reply.lower() or "pagare" in deadlines_reply.lower()
