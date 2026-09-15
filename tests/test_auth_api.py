import io
from fastapi.testclient import TestClient
from app.main import app
from app.models.database import init_db, get_session_maker, PhysicalItem, Document
from app.services.crypto_service import get_vault_manager

client = TestClient(app)

def setup_module():
    init_db()
    mgr = get_vault_manager()
    mgr.initialize_if_needed("Leonardo2005")

def test_auth_login_wrong_password():
    res = client.post("/api/auth/login", json={"password": "PasswordSbagliata"})
    assert res.status_code == 401
    assert "non corretta" in res.json()["detail"].lower()

def test_auth_login_correct_password():
    res = client.post("/api/auth/login", json={"password": "Leonardo2005"})
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert "token" in data
    assert len(data["token"]) > 10

def test_auth_status_and_lock():
    # Login first
    login_res = client.post("/api/auth/login", json={"password": "Leonardo2005"})
    assert login_res.status_code == 200
    token = login_res.json()["token"]

    status_res = client.get("/api/auth/status")
    assert status_res.status_code == 200
    assert status_res.json()["unlocked"] is True

    # Lock vault
    lock_res = client.post("/api/auth/lock", headers={"X-Vault-Token": token})
    assert lock_res.status_code == 200
    assert lock_res.json()["success"] is True

    # Re-unlock for subsequent operations
    re_res = client.post("/api/auth/login", json={"password": "Leonardo2005"})
    assert re_res.status_code == 200

def test_upload_photo_to_physical_item():
    # Create item via endpoint to respect test DB isolation
    create_res = client.post(
        "/api/items/with-photo",
        data={
            "item_name": "Occhiali da vista",
            "primary_location": "Camera da letto",
            "detailed_location": "Comodino",
            "category": "accessori"
        }
    )
    assert create_res.status_code == 201
    item_id = create_res.json()["item_id"]

    fake_img = io.BytesIO(b"\xff\xd8\xff\xe0 fake jpeg photo bytes")
    res = client.post(
        f"/api/items/{item_id}/photo",
        files={"file": ("occhiali.jpg", fake_img, "image/jpeg")}
    )
    assert res.status_code == 200, f"Got status {res.status_code} with text {res.text} and item_id={item_id}"
    data = res.json()
    assert data["success"] is True
    assert data["item_id"] == item_id
    assert "image_url" in data
    assert data["image_url"].startswith("/api/files/")

def test_secure_file_decrypted_download():
    # Upload a document
    fake_pdf = io.BytesIO(b"%PDF-1.4 test secret encrypted document")
    upload_res = client.post(
        "/api/documents/upload",
        files={"file": ("segreto.pdf", fake_pdf, "application/pdf")}
    )
    assert upload_res.status_code == 201
    doc_id = upload_res.json()["document_id"]

    # Download through decrypted endpoint
    dl_res = client.get(f"/api/documents/{doc_id}/download")
    assert dl_res.status_code == 200
    # Decrypted content must match original plaintext
    assert dl_res.content == b"%PDF-1.4 test secret encrypted document"
