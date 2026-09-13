import io
from fastapi.testclient import TestClient
from app.main import app
from app.models.database import init_db

client = TestClient(app)


def test_chat_store_and_query():
    # 1. Store item via chat
    res = client.post("/api/chat", json={"message": "Ho messo il passaporto nel primo cassetto della scrivania"})
    assert res.status_code == 200
    data = res.json()
    assert "Memorizzato" in data["reply"]
    
    # 2. Query item via chat
    res_query = client.post("/api/chat", json={"message": "Dov'è il passaporto?"})
    assert res_query.status_code == 200
    assert "passaporto" in res_query.json()["reply"].lower()

def test_upload_document():
    fake_pdf = io.BytesIO(b"%PDF-1.4 fake content")
    res = client.post("/api/documents/upload", files={"file": ("bolletta_enel.pdf", fake_pdf, "application/pdf")})
    assert res.status_code == 201
    data = res.json()
    assert data["amount"] == 64.20
    assert "Enel" in data["issuer"]

def test_dashboard_feed():
    res = client.get("/api/dashboard")
    assert res.status_code == 200
    feed = res.json()
    assert "kpi" in feed
    assert "records" in feed
    assert len(feed["records"]) > 0

def test_patch_document_status():
    fake_pdf = io.BytesIO(b"%PDF-1.4 fake content")
    upload_res = client.post("/api/documents/upload", files={"file": ("f24_tributi.pdf", fake_pdf, "application/pdf")})
    doc_id = upload_res.json()["document_id"]
    
    patch_res = client.patch(f"/api/documents/{doc_id}/status", json={"status": "quietanzato"})
    assert patch_res.status_code == 200
    assert patch_res.json()["status"] == "quietanzato"

def test_root_serves_index():
    res = client.get("/")
    assert res.status_code == 200
    assert "Dove lo AI messo" in res.text

def test_delete_document():
    fake_pdf = io.BytesIO(b"%PDF-1.4 test delete")
    upload_res = client.post("/api/documents/upload", files={"file": ("doc_da_eliminare.pdf", fake_pdf, "application/pdf")})
    assert upload_res.status_code == 201
    doc_id = upload_res.json()["document_id"]

    del_res = client.delete(f"/api/documents/{doc_id}")
    assert del_res.status_code == 200
    assert del_res.json()["success"] is True

    # Verifica che ora restituisce 404
    del_res_again = client.delete(f"/api/documents/{doc_id}")
    assert del_res_again.status_code == 404

def test_delete_physical_item():
    client.post("/api/chat", json={"message": "Ho messo gli occhiali da sole nella custodia sul comodino"})
    feed = client.get("/api/dashboard?filter=items").json()
    item = next((r for r in feed["records"] if "occhiali" in r["title"].lower()), None)
    assert item is not None

    del_res = client.delete(f"/api/items/{item['id']}")
    assert del_res.status_code == 200
    assert del_res.json()["success"] is True

    # Verifica che ora restituisce 404
    del_res_again = client.delete(f"/api/items/{item['id']}")
    assert del_res_again.status_code == 404

def test_chat_delete_confirmation_intent():
    # Salva un elemento per poi richiederne l'eliminazione
    client.post("/api/chat", json={"message": "Ho messo la patente nel cassetto dello studio"})
    
    # Chiedi di eliminarlo via chat
    res = client.post("/api/chat", json={"message": "elimina la patente per favore"})
    assert res.status_code == 200
    data = res.json()
    assert data["action"] == "REQUEST_DELETE"
    assert data["confirmation"] is not None
    assert data["confirmation"]["type"] == "delete_confirmation"
    assert data["confirmation"]["target_type"] == "physical_item"
    assert "patente" in data["confirmation"]["title"].lower()
    assert "Sei sicuro" in data["reply"]

