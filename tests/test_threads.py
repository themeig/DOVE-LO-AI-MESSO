import io
from fastapi.testclient import TestClient
from app.main import app
from app.models.database import init_db

client = TestClient(app)


def test_list_default_threads():
    res = client.get("/api/threads")
    assert res.status_code == 200
    data = res.json()
    assert "threads" in data
    thread_ids = [t["id"] for t in data["threads"]]
    assert "general" in thread_ids
    assert "famiglia" in thread_ids
    assert "lavoro" in thread_ids
    assert "casa" in thread_ids

def test_create_group_thread():
    payload = {
        "name": "Famiglia Vacanze",
        "thread_type": "group",
        "members": ["Io", "Luca", "Sara"],
        "description": "Cose da portare e spese delle vacanze"
    }
    res = client.post("/api/threads", json=payload)
    assert res.status_code == 201
    thread = res.json()
    assert thread["thread_type"] == "group"
    assert "Luca" in thread["members"]
    assert "Sara" in thread["members"]
    assert thread["name"] == "Famiglia Vacanze"

def test_create_thematic_thread():
    payload = {
        "name": "Fisco & Tasse",
        "thread_type": "thematic",
        "icon": "fa-receipt",
        "description": "F24 e ricevute commercialista"
    }
    res = client.post("/api/threads", json=payload)
    assert res.status_code == 201
    thread = res.json()
    assert thread["thread_type"] == "thematic"
    assert thread["icon"] == "fa-receipt"

def test_chat_message_in_thread():
    # 1. Send chat message to famiglia thread
    msg_res = client.post("/api/chat", json={
        "message": "Ho messo la tenda da campeggio in garage",
        "thread_id": "famiglia"
    })
    assert msg_res.status_code == 200
    
    # 2. Verify messages in that thread
    thread_msgs_res = client.get("/api/threads/famiglia/messages")
    assert thread_msgs_res.status_code == 200
    msgs = thread_msgs_res.json()["messages"]
    assert any("tenda" in m["content"].lower() for m in msgs)

def test_upload_document_to_thread():
    fake_pdf = io.BytesIO(b"%PDF-1.4 fake contract")
    res = client.post(
        "/api/documents/upload",
        files={"file": ("contratto_lavoro.pdf", fake_pdf, "application/pdf")},
        data={"thread_id": "lavoro"}
    )
    assert res.status_code == 201
    doc_id = res.json()["document_id"]
    
    # Check dashboard filtering by thread
    dash_res = client.get("/api/dashboard?thread_id=lavoro")
    assert dash_res.status_code == 200
    dash_records = dash_res.json()["records"]
    assert any(r["id"] == doc_id and r["thread_id"] == "lavoro" for r in dash_records)

def test_delete_thread():
    # Attempt to delete general -> should fail with 400
    err_res = client.delete("/api/threads/general")
    assert err_res.status_code == 400

    # Create temporary thread
    create_res = client.post("/api/threads", json={"name": "Temp Test", "thread_type": "thematic"})
    temp_id = create_res.json()["id"]

    # Delete temporary thread -> should succeed with 200
    del_res = client.delete(f"/api/threads/{temp_id}")
    assert del_res.status_code == 200
