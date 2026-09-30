import pytest
from datetime import date, timedelta, datetime, timezone
from app.models.database import init_db, SessionLocal, Document, ChatThread
from app.services.agent.tools_executor import execute_vault_tool
from app.services.agent.orchestrator import AgenticChatService
from app.mcp_server import update_document_payment_status as mcp_update_status


@pytest.fixture(scope="module")
def setup_database():
    init_db()
    yield


@pytest.fixture
def db_session(setup_database):
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def test_update_document_payment_status_to_paid(db_session):
    # Creiamo un documento da pagare con titolo unico
    doc = Document(
        user_id="default_user",
        title="Bolletta Illumia Unique 2026",
        file_path="uploads/bolletta_illumia.pdf",
        file_type="pdf",
        doc_type="bolletta",
        issuer="Illumia",
        amount=84.50,
        due_date=date.today() + timedelta(days=10),
        status="da_pagare",
        summary="Bolletta energia elettrica Illumia"
    )
    db_session.add(doc)
    db_session.commit()
    db_session.refresh(doc)
    assert doc.status == "da_pagare"
    assert doc.paid_at is None

    # Eseguiamo il tool per segnare come pagato tramite titolo
    res = execute_vault_tool(
        "update_document_payment_status",
        {"status": "pagato", "document_title": "Bolletta Illumia Unique"},
        db=db_session
    )
    assert res["success"] is True
    assert res["document_id"] == doc.id
    assert res["status"] == "quietanzato"
    assert res["status_label"] == "Quietanzato / Pagato"
    assert len(res["documents"]) == 1
    assert res["documents"][0]["status"] == "quietanzato"

    # Verifichiamo la persistenza sul database
    db_session.refresh(doc)
    assert doc.status == "quietanzato"
    assert doc.paid_at is not None


def test_update_document_payment_status_to_unpaid(db_session):
    # Creiamo un documento già quietanzato
    doc = Document(
        user_id="default_user",
        title="Fattura Telecom 2026",
        file_path="uploads/fattura_telecom.pdf",
        file_type="pdf",
        doc_type="fattura",
        issuer="TIM",
        amount=35.00,
        due_date=date.today() + timedelta(days=5),
        status="quietanzato",
        paid_at=datetime.now(timezone.utc),
        summary="Fattura fibra TIM"
    )
    db_session.add(doc)
    db_session.commit()
    db_session.refresh(doc)

    # Segna come da pagare tramite document_id
    res = execute_vault_tool(
        "update_document_payment_status",
        {"status": "da_pagare", "document_id": doc.id},
        db=db_session
    )
    assert res["success"] is True
    assert res["status"] == "da_pagare"
    assert "da pagare" in res["status_label"].lower()

    db_session.refresh(doc)
    assert doc.status == "da_pagare"
    assert doc.paid_at is None


def test_scadenzario_retrieval(db_session):
    # Documento con scadenza
    doc = Document(
        user_id="default_user",
        title="Modello F24 Acconto",
        file_path="uploads/f24_acconto.pdf",
        file_type="pdf",
        doc_type="f24",
        issuer="Agenzia delle Entrate",
        amount=450.00,
        due_date=date.today() + timedelta(days=3),
        status="da_pagare",
        summary="F24 acconto IRPEF"
    )
    db_session.add(doc)
    db_session.commit()

    # Eseguiamo get_upcoming_deadlines
    res = execute_vault_tool("get_upcoming_deadlines", {}, db=db_session)
    deadlines = res.get("deadlines") or res.get("upcoming_documents", [])
    assert len(deadlines) >= 1
    assert any(d["title"] == "Modello F24 Acconto" for d in deadlines)


def test_orchestrator_scadenzario_and_payment_flow(db_session):
    # Creiamo un thread e una bolletta
    thread = ChatThread(id="test_thread_payment", name="Test Thread")
    db_session.add(thread)
    db_session.commit()
    db_session.refresh(thread)

    doc = Document(
        thread_id=thread.id,
        user_id="default_user",
        title="Bolletta A2A Luce 2026",
        file_path="uploads/bolletta_a2a.pdf",
        file_type="pdf",
        doc_type="bolletta",
        issuer="A2A",
        amount=112.30,
        due_date=date.today() + timedelta(days=7),
        status="da_pagare",
        summary="Bolletta elettricità"
    )
    db_session.add(doc)
    db_session.commit()

    orchestrator = AgenticChatService()

    # 1. Richiesta esplicita scadenzario
    resp_scad = orchestrator.run_turn(
        user_text="Fammi vedere lo scadenzario",
        db=db_session,
        thread_id=thread.id
    )
    assert resp_scad.action in ["get_upcoming_deadlines", "show_document_card"]
    assert len(resp_scad.documents or []) >= 1
    assert "scadenze" in resp_scad.reply.lower() or "scadenzario" in resp_scad.reply.lower() or "sospeso" in resp_scad.reply.lower()

    # 2. Richiesta di contrassegnare come pagato
    resp_pay = orchestrator.run_turn(
        user_text=f"Ho pagato la bolletta {doc.title}",
        db=db_session,
        thread_id=thread.id
    )
    assert resp_pay.action in ["update_document_payment_status", "show_document_card"]
    db_session.refresh(doc)
    assert doc.status == "quietanzato"


def test_mcp_update_document_payment_status(db_session):
    doc = Document(
        user_id="default_user",
        title="Tassa Rifiuti TARI 2026",
        file_path="uploads/tari_2026.pdf",
        file_type="pdf",
        doc_type="tributo",
        issuer="Comune di Milano",
        amount=210.00,
        due_date=date.today() + timedelta(days=15),
        status="da_pagare",
        summary="Avviso pagamento TARI"
    )
    db_session.add(doc)
    db_session.commit()

    output = mcp_update_status(status="quietanzato", document_title="TARI")
    assert "aggiornato con successo" in output
    assert "TARI" in output
    db_session.refresh(doc)
    assert doc.status == "quietanzato"
