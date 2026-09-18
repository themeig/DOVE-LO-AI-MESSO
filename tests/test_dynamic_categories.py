import pytest
from datetime import date
from fastapi.testclient import TestClient
from app.main import app
from app.models.database import init_db, get_db, Document
from app.services.ai_service import MockAIService
from app.services.agent_service import AgentService
from app.api.dashboard import classify_document_category

client = TestClient(app)

def test_mock_ai_extracts_dynamic_categories():
    ai = MockAIService()
    
    # 1. Test Song
    doc_song = ai.extract_document(b"Sei nell'anima e ti sento vicina...", "text/plain", "canzone_gianna.txt")
    assert doc_song.category == "canzoni_musica"
    assert doc_song.category_label == "Canzoni & Testi Musicali"
    assert doc_song.category_icon == "fa-music"
    assert doc_song.doc_type == "testo_personale"

    # 2. Test Certificate
    doc_cert = ai.extract_document(b"test tolc", "application/pdf", "certificato_tolc.pdf")
    assert doc_cert.category == "formazione_certificati"
    assert doc_cert.category_label == "Formazione & Certificati"
    assert doc_cert.category_icon == "fa-graduation-cap"

    # 3. Test Bill
    doc_bill = ai.extract_document(b"bolletta enel luce", "application/pdf", "bolletta_enel.pdf")
    assert doc_bill.category == "utenze_bollette"
    assert doc_bill.category_label == "Utenze & Bollette"
    assert doc_bill.category_icon == "fa-bolt"


def test_classify_document_category_gives_primacy_to_ai():
    init_db()
    
    # Create document with an arbitrary custom AI-generated category
    custom_doc = Document(
        title="Pasta al Forno con Besciamella",
        file_path="uploads/ricetta.txt",
        file_type="txt",
        doc_type="ricetta",
        summary="Ricetta per la domenica in famiglia",
        category="ricette_cucina",
        category_label="Ricette & Cucina Tradizionale",
        category_icon="fa-utensils"
    )
    
    cat, label, icon = classify_document_category(custom_doc)
    assert cat == "ricette_cucina"
    assert label == "Ricette & Cucina Tradizionale"
    assert icon == "fa-utensils"


def test_agent_recategorize_vault_document_tool():
    init_db()
    db = next(get_db())
    
    doc = Document(
        title="Appunti di Meccanica Quantistica",
        file_path="uploads/fisica.pdf",
        file_type="pdf",
        doc_type="appunti",
        summary="Formule e postulati di fisica moderna",
        category="altro",
        category_label="Altri Documenti",
        category_icon="fa-folder-closed"
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    
    agent = AgentService()
    res = agent.execute_tool(
        name="recategorize_vault_document",
        args={
            "document_id": doc.id,
            "category_label": "Appunti Universitari di Fisica",
            "category_icon": "fa-atom"
        },
        db=db,
        thread_id="general"
    )
    
    assert res["success"] is True
    assert res["new_category_label"] == "Appunti Universitari di Fisica"
    assert res["category_icon"] == "fa-atom"
    
    # Verify in DB
    updated = db.query(Document).filter(Document.id == doc.id).first()
    assert updated.category_label == "Appunti Universitari di Fisica"
    assert updated.category_icon == "fa-atom"
    assert "appunti" in updated.category


def test_dashboard_feed_returns_dynamic_categories_and_backfills():
    init_db()
    db = next(get_db())
    
    # Document without category_label (simulate legacy data)
    legacy_song = Document(
        title="Testo Il cielo d'Irlanda",
        file_path="uploads/cielo_irlanda.txt",
        file_type="txt",
        doc_type="canzone",
        summary="Testo poetico e musicale di una canzone",
        category=None,
        category_label=None,
        category_icon=None
    )
    db.add(legacy_song)
    db.commit()
    
    res = client.get("/api/dashboard")
    assert res.status_code == 200
    data = res.json()
    
    # Find the record in the feed
    found = next((r for r in data["records"] if r["id"] == legacy_song.id and r["type"] == "document"), None)
    assert found is not None
    assert found["category_label"] == "Canzoni & Testi Musicali"
    assert found["category_icon"] == "fa-music"
    assert found["category"] == "canzoni_musica"
