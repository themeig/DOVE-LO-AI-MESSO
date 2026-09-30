"""Test specifici per la cancellazione di Google Drive e del root folder durante il wipe del database."""
import io
import httpx
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from app.main import app
from app.models.database import (
    init_db, get_db, Document, GoogleDriveCredential, get_session_maker
)
from app.services.crypto_service import get_vault_manager
from app.services.drive_service import (
    MockGoogleDriveService,
    RealGoogleDriveService,
    get_drive_service,
)

client = TestClient(app)


def setup_module():
    init_db()
    mgr = get_vault_manager()
    mgr.initialize_if_needed("1234")
    mgr.unlock("1234")
    mgr.rate_limiter.reset("127.0.0.1")
    mgr.rate_limiter.reset("testclient")


def test_mock_drive_service_delete_and_upload():
    service = MockGoogleDriveService()
    assert service.delete_vault_root_folder("mock_token") is True
    assert service.delete_vault_root_folder("mock_token", root_folder_id="root-123") is True

    res = service.upload_file(
        file_bytes=b"sample",
        filename="test.pdf",
        mime_type="application/pdf",
        folder_path=["DoveLoAIMesso", "2026", "Bollette"],
        access_token="mock_token",
    )
    assert res.get("root_folder_id") == "mock-root-folder-id"
    assert "file_id" in res
    assert "web_view_link" in res


def test_real_drive_service_delete_with_root_folder_id():
    deleted_urls = []

    def mock_handler(request: httpx.Request):
        url = str(request.url)
        if request.method == "DELETE":
            deleted_urls.append(url)
            return httpx.Response(204)
        if "googleapis.com/drive/v3/files" in url and request.method == "GET":
            q = request.url.params.get("q", "")
            if "name = 'DoveLoAIMesso'" in q:
                return httpx.Response(200, json={"files": [{"id": "root-folder-id", "name": "DoveLoAIMesso"}]})
            if "trashed = false" in q:
                return httpx.Response(200, json={"files": [{"id": "child-file-1", "name": "bolletta.pdf"}]})
        return httpx.Response(404)

    transport = httpx.MockTransport(mock_handler)
    with httpx.Client(transport=transport) as mock_client:
        service = RealGoogleDriveService(
            client_id="cid", client_secret="csec", redirect_uri="http://localhost/cb", http_client=mock_client
        )
        success = service.delete_vault_root_folder(access_token="tok", root_folder_id="root-folder-id")
        assert success is True
        assert any("root-folder-id" in u for u in deleted_urls)
        assert any("child-file-1" in u for u in deleted_urls)


def test_real_drive_service_delete_auth_failure():
    def mock_handler(request: httpx.Request):
        return httpx.Response(401, json={"error": {"message": "Invalid Credentials"}})

    transport = httpx.MockTransport(mock_handler)
    with httpx.Client(transport=transport) as mock_client:
        service = RealGoogleDriveService(
            client_id="cid", client_secret="csec", redirect_uri="http://localhost/cb", http_client=mock_client
        )
        success = service.delete_vault_root_folder(access_token="expired_tok")
        assert success is False


def test_wipe_database_refreshes_token_and_deletes_drive():
    get_db_func = app.dependency_overrides.get(get_db, get_db)
    db = next(get_db_func())
    try:
        # Prepara credenziale Drive
        db.query(GoogleDriveCredential).delete()
        cred = GoogleDriveCredential(
            user_email="test.wipe@example.com",
            access_token="expired_or_stale_token",
            refresh_token="valid_refresh_token",
            storage_mode="dual",
            root_folder_id="folder-to-delete-456",
        )
        db.add(cred)
        db.commit()

        # Mock di get_fresh_access_token per simulare il rinnovo riuscito
        with patch("app.services.drive_service.get_fresh_access_token", return_value="refreshed_fresh_token_789") as mock_fresh:
            res = client.post(
                "/api/settings/wipe-database",
                json={"password": "1234", "delete_drive": True}
            )
            assert res.status_code == 200
            data = res.json()
            assert data["success"] is True
            assert data["drive_deleted"] is True
            assert mock_fresh.called

        # Credenziali eliminate dal DB
        assert db.query(GoogleDriveCredential).count() == 0
    finally:
        db.close()


def test_document_upload_sets_root_folder_id():
    init_db()
    client.post("/api/drive/disconnect")
    # Connetti Drive mock
    client.get("/api/drive/callback?code=test_code")

    SessionLocal = get_session_maker()
    with SessionLocal() as db:
        cred = db.query(GoogleDriveCredential).first()
        assert cred is not None
        assert cred.root_folder_id is None

    # Upload documento
    pdf_bytes = io.BytesIO(b"%PDF-1.4 test document for root folder tracking")
    res = client.post(
        "/api/documents/upload",
        files={"file": ("fattura_test.pdf", pdf_bytes, "application/pdf")},
        data={"thread_id": "general"}
    )
    assert res.status_code in (200, 201)

    # Verifica che root_folder_id sia stato memorizzato su GoogleDriveCredential
    with SessionLocal() as db:
        cred = db.query(GoogleDriveCredential).first()
        assert cred is not None
        assert cred.root_folder_id == "mock-root-folder-id"

    # Cleanup
    client.post("/api/drive/disconnect")
