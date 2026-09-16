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
    assert "memorizzato" in data["reply"].lower()
    
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
    # Verifica campi di categorizzazione per la vista raggruppata
    doc_rec = next((r for r in feed["records"] if r["type"] == "document"), None)
    item_rec = next((r for r in feed["records"] if r["type"] == "physical_item"), None)
    if doc_rec:
        assert doc_rec.get("category") is not None
        assert doc_rec.get("category_label") is not None
        assert doc_rec.get("category_icon") is not None
    if item_rec:
        assert item_rec.get("room") is not None
        assert item_rec.get("category") is not None

def test_dashboard_filter_aliases():
    # Test ?filter=da_pagare
    res_dp = client.get("/api/dashboard?filter=da_pagare")
    assert res_dp.status_code == 200
    for r in res_dp.json()["records"]:
        if r["type"] == "document":
            assert r["status"] == "da_pagare"

    # Test ?filter=oggetti
    res_ogg = client.get("/api/dashboard?filter=oggetti")
    assert res_ogg.status_code == 200
    for r in res_ogg.json()["records"]:
        assert r["type"] == "physical_item"

    # Test ?filter=quietanzati
    res_q = client.get("/api/dashboard?filter=quietanzati")
    assert res_q.status_code == 200
    for r in res_q.json()["records"]:
        if r["type"] == "document":
            assert r["status"] == "quietanzato"


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

def test_showcase_and_demo_endpoints():
    res_sc = client.get("/showcase")
    assert res_sc.status_code == 200
    assert "Product Showcase" in res_sc.text or "Dove lo AI messo" in res_sc.text

    res_demo = client.get("/demo")
    assert res_demo.status_code == 200
    assert "Product Showcase" in res_demo.text or "Dove lo AI messo" in res_demo.text

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
    assert any(k in data["reply"].lower() for k in ["sei sicuro", "sicurezza", "conferma", "eliminare"])

def test_download_document_file():
    fake_pdf = io.BytesIO(b"%PDF-1.4 test download content")
    upload_res = client.post("/api/documents/upload", files={"file": ("certificato_esame.pdf", fake_pdf, "application/pdf")})
    assert upload_res.status_code == 201
    doc_id = upload_res.json()["document_id"]
    assert "download_url" in upload_res.json()
    assert upload_res.json()["download_url"] == f"/api/documents/{doc_id}/download"

    # Test download endpoint
    dl_res = client.get(f"/api/documents/{doc_id}/download")
    assert dl_res.status_code == 200
    assert dl_res.content == b"%PDF-1.4 test download content"
    assert "attachment;" in dl_res.headers.get("content-disposition", "")

def test_delete_documents_bulk():
    # Carica 2 documenti di test
    p1 = io.BytesIO(b"%PDF-1.4 bulk doc 1")
    p2 = io.BytesIO(b"%PDF-1.4 bulk doc 2")
    u1 = client.post("/api/documents/upload", files={"file": ("doc_bulk_1.pdf", p1, "application/pdf")}).json()
    u2 = client.post("/api/documents/upload", files={"file": ("doc_bulk_2.pdf", p2, "application/pdf")}).json()
    
    doc1_id = u1["document_id"]
    doc2_id = u2["document_id"]
    
    del_res = client.request("DELETE", "/api/documents/bulk", json={"document_ids": [doc1_id, doc2_id]})
    assert del_res.status_code == 200
    data = del_res.json()
    assert data["success"] is True
    assert data["count"] == 2
    assert doc1_id in data["deleted_ids"]
    assert doc2_id in data["deleted_ids"]
    
    # Verifica che ora sono stati cancellati
    check1 = client.get(f"/api/documents/{doc1_id}/file")
    assert check1.status_code == 404

def test_chat_listing_and_bulk_delete_intents():
    # 1. Carica un documento
    p = io.BytesIO(b"%PDF-1.4 test listing")
    u = client.post("/api/documents/upload", files={"file": ("fattura_test.pdf", p, "application/pdf")}).json()
    doc_id = u["document_id"]
    
    # 2. Chiedi la lista di tutti i documenti
    list_res = client.post("/api/chat", json={"message": "fai la lista di tutti i documenti che hai"})
    assert list_res.status_code == 200
    list_data = list_res.json()
    assert list_data["action"] in ["list_vault_contents", "list_documents"]
    assert "elenco" in list_data["reply"].lower() or "documenti" in list_data["reply"].lower()
    docs_returned = list_data.get("data", {}).get("documents", []) or list_data.get("documents", [])
    assert any(d.get("document_id") == doc_id or d.get("id") == doc_id for d in docs_returned)
    
    # 3. Chiedi di eliminarli tutti
    del_res = client.post("/api/chat", json={"message": "elimina tutti i documenti che hai"})
    assert del_res.status_code == 200
    del_data = del_res.json()
    assert del_data["action"] == "REQUEST_DELETE"
    assert del_data["confirmation"] is not None
    assert del_data["confirmation"]["target_type"] == "bulk_documents"
    assert doc_id in del_data["confirmation"]["target_ids"]

def test_chat_with_quoted_message():
    # Invia un messaggio quotando un testo precedente
    quote_payload = {
        "message": "Chi è l'emittente?",
        "thread_id": "general",
        "quoted_message": {
            "sender": "Dove lo AI messo",
            "text": "Bolletta Enel Energia da 64.20€"
        }
    }
    res = client.post("/api/chat", json=quote_payload)
    assert res.status_code == 200
    data = res.json()
    assert "reply" in data

    # Verifica che nei messaggi del thread ci sia il metadata quoted_message salvato
    msgs_res = client.get("/api/threads/general/messages")
    assert msgs_res.status_code == 200
    msgs = msgs_res.json().get("messages", [])
    last_user_msg = [m for m in msgs if m["sender"] == "user"][-1]
    assert last_user_msg["metadata"] is not None
    assert "quoted_message" in last_user_msg["metadata"]
    assert last_user_msg["metadata"]["quoted_message"]["text"] == "Bolletta Enel Energia da 64.20€"
