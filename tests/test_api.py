import io
from fastapi.testclient import TestClient
from app.main import app
from app.models.database import init_db

client = TestClient(app)

def setup_module():
    init_db()

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

