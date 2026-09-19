import io
from datetime import date
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.models.database import Document, PhysicalItem, init_db, get_engine
from app.services.agent_service import AgenticChatService

client = TestClient(app)


def setup_module():
    init_db()


def test_targeted_bulk_delete_vs_total_vault():
    engine = get_engine("sqlite:///:memory:")
    init_db(engine)
    with Session(engine) as session:
        # Crea 2 documenti 730 test
        d1 = Document(title="730 Test 2025", file_path="uploads/730_1.pdf", file_type="pdf", doc_type="730", thread_id="t1", summary="Dichiarazione 730 test anno 2025")
        d2 = Document(title="730 Test Integrativo", file_path="uploads/730_2.pdf", file_type="pdf", doc_type="730", thread_id="t1", summary="730 test integrativo")
        # Crea 1 bolletta Enel e 1 contratto
        d3 = Document(title="Bolletta Enel Ottobre", file_path="uploads/enel.pdf", file_type="pdf", doc_type="bolletta", thread_id="t1", summary="Bolletta luce")
        d4 = Document(title="Contratto Locazione", file_path="uploads/contratto.pdf", file_type="pdf", doc_type="contratto", thread_id="t1", summary="Contratto affitto")
        session.add_all([d1, d2, d3, d4])
        session.commit()

        agent = AgenticChatService()

        # 1. "elimina tutti i 730 test" -> deve eliminare SOLO i 2 documenti 730 test, NON tutto il caveau!
        res_730 = agent._handle_deletion_intent("elimina tutti i 730 test", "elimina tutti i 730 test", session, thread_id="t1")
        assert res_730 is not None
        assert res_730.action == "REQUEST_DELETE"
        assert res_730.confirmation is not None
        assert res_730.confirmation["target_type"] == "bulk_documents"
        assert len(res_730.confirmation["target_ids"]) == 2
        assert d1.id in res_730.confirmation["target_ids"]
        assert d2.id in res_730.confirmation["target_ids"]
        assert d3.id not in res_730.confirmation["target_ids"]
        assert d4.id not in res_730.confirmation["target_ids"]

        # 2. Tool delete_vault_record con title="730 test"
        tool_res = agent.execute_tool("delete_vault_record", {"target_type": "bulk_documents", "title": "730 test"}, session, thread_id="t1")
        assert tool_res.get("status") == "pending_confirmation"
        assert len(tool_res["confirmation"]["target_ids"]) == 2

        # 3. "elimina tutti i documenti" -> deve proporre l'eliminazione di TUTTI e 4 i documenti
        res_all = agent._handle_deletion_intent("elimina tutti i documenti", "elimina tutti i documenti", session, thread_id="t1")
        assert res_all is not None
        assert res_all.action == "REQUEST_DELETE"
        assert len(res_all.confirmation["target_ids"]) == 4


def test_link_document_to_physical_item_via_api():
    # 1. Crea un oggetto fisico
    item_res = client.post("/api/items", json={"item_name": "Pianoforte Verticale", "primary_location": "Salone principale"})
    assert item_res.status_code == 201
    item_id = item_res.json()["id"]

    # 2. Carica un'immagine
    fake_img = io.BytesIO(b"\xff\xd8\xff fake jpeg photo of piano")
    upload_res = client.post("/api/documents/upload", files={"file": ("foto_piano.jpg", fake_img, "image/jpeg")})
    assert upload_res.status_code == 201
    doc_id = upload_res.json()["document_id"]

    # 3. Collega la foto all'oggetto tramite endpoint REST
    link_res = client.post(f"/api/items/{item_id}/link-document/{doc_id}")
    assert link_res.status_code == 200
    data = link_res.json()
    assert data["success"] is True
    assert data["item"]["document_id"] == doc_id
    assert data["item"]["has_photo"] is True
    assert data["item"]["image_url"] is not None

    # 4. Verifica nel feed della dashboard
    dash_res = client.get("/api/dashboard")
    assert dash_res.status_code == 200
    records = dash_res.json()["records"]
    piano_record = next((r for r in records if r["type"] == "physical_item" and r["id"] == item_id), None)
    assert piano_record is not None
    assert piano_record["has_photo"] is True
    assert piano_record["document_id"] == doc_id
    assert piano_record["image_url"] is not None


def test_conversational_photo_linking_and_where_query():
    # 1. Memorizza posizione del "Piano"
    chat_store = client.post("/api/chat", json={"message": "Ho messo il Piano in Salotto accanto alla finestra"})
    assert chat_store.status_code == 200
    assert "salotto" in chat_store.json()["reply"].lower()

    # 2. Carica una foto
    fake_img = io.BytesIO(b"\xff\xd8\xff photo of piano location")
    upload_res = client.post("/api/documents/upload", files={"file": ("posizione_piano.jpg", fake_img, "image/jpeg")})
    assert upload_res.status_code == 201
    doc_id = upload_res.json()["document_id"]

    # 3. Invia messaggio di collegamento foto: "ti allego una foto per il piano"
    chat_link = client.post("/api/chat", json={"message": "ti allego una foto per il piano"})
    assert chat_link.status_code == 200
    link_data = chat_link.json()
    assert "associato la foto" in link_data["reply"].lower() or "piano" in link_data["reply"].lower()

    # 4. Chiedi: "dov'è il piano?" -> Deve restituire la posizione e allegare la scheda della foto!
    chat_query = client.post("/api/chat", json={"message": "dov'è il piano?"})
    assert chat_query.status_code == 200
    query_data = chat_query.json()
    assert "salotto" in query_data["reply"].lower()
    # Verifica che la foto sia inclusa nei documenti allegati per il rendering della scheda
    assert query_data.get("documents") is not None
    assert len(query_data["documents"]) >= 1
    assert query_data["documents"][0]["document_id"] == doc_id
