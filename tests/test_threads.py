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

def test_thread_messages_document_widgets_persistence():
    # Create a dedicated thread
    t_res = client.post("/api/threads", json={"name": "Test Widget Persistence", "thread_type": "thematic"})
    assert t_res.status_code == 201
    tid = t_res.json()["id"]

    fake_pdf = io.BytesIO(b"%PDF-1.4 persistence test")
    upload_res = client.post(
        "/api/documents/upload",
        files={"file": ("fattura_persistente.pdf", fake_pdf, "application/pdf")},
        data={"thread_id": tid}
    )
    assert upload_res.status_code == 201
    doc_id = upload_res.json()["document_id"]

    # Fetch thread messages
    msgs_res = client.get(f"/api/threads/{tid}/messages")
    assert msgs_res.status_code == 200
    msgs = msgs_res.json()["messages"]

    # Find the user upload message and assistant response
    user_msg = next((m for m in msgs if m["sender"] == "user" and m["message_type"] == "document"), None)
    asst_msg = next((m for m in msgs if m["sender"] == "assistant" and m.get("metadata", {}).get("documents")), None)

    assert user_msg is not None, "User document upload message must exist"
    assert user_msg["metadata"].get("documents"), "User message metadata must contain documents"
    assert user_msg["metadata"].get("file_url"), "User message metadata must have file_url for preview"
    assert user_msg["metadata"].get("download_url"), "User message metadata must have download_url"

    assert asst_msg is not None, "Assistant message with document widget must exist"
    docs = asst_msg["metadata"]["documents"]
    assert len(docs) > 0
    assert docs[0]["id"] == doc_id
    assert docs[0]["title"]
    assert docs[0]["file_url"]
    assert docs[0]["download_url"]

