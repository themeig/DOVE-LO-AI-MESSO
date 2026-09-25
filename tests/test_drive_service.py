from datetime import date
import pytest
import httpx
from app.services.drive_service import (
    GoogleDriveServiceInterface,
    MockGoogleDriveService,
    RealGoogleDriveService,
    get_drive_service,
    resolve_drive_folder_path,
    sanitize_drive_folder_name,
)


def test_resolve_drive_folder_path():
    path_bill = resolve_drive_folder_path("bolletta", date(2026, 10, 28))
    assert path_bill == ["DoveLoAIMesso", "2026", "Bollette & Utenze"]

    path_tax = resolve_drive_folder_path("f24", date(2025, 6, 16))
    assert path_tax == ["DoveLoAIMesso", "2025", "Fisco & Tasse"]

    path_generic = resolve_drive_folder_path("generico", None)
    assert path_generic == ["DoveLoAIMesso", "Documenti & Foto"]


def test_sanitize_drive_folder_name():
    assert sanitize_drive_folder_name("Famiglia 👨‍👩‍👧", thread_id="famiglia") == "Famiglia"
    assert sanitize_drive_folder_name("Lavoro & Studio 💼", thread_id="lavoro") == "Lavoro & Studio"
    assert sanitize_drive_folder_name("Casa & Utenze 🏠", thread_id="casa") == "Casa & Utenze"
    assert sanitize_drive_folder_name("Dove lo AI messo", thread_id="general") == "Generale"
    assert sanitize_drive_folder_name(None, thread_id="general") == "Generale"
    assert sanitize_drive_folder_name("", thread_id="all") == "Generale"
    assert sanitize_drive_folder_name("Progetto 2026 🚀", thread_id="proj-1") == "Progetto 2026"
    assert sanitize_drive_folder_name("Cartella / Test : Special *", thread_id="custom") == "Cartella Test Special"


def test_resolve_drive_folder_path_with_chat_folder():
    # Chat Famiglia: bolletta con scadenza 2026
    path_fam = resolve_drive_folder_path("bolletta", date(2026, 10, 28), chat_folder="Famiglia")
    assert path_fam == ["DoveLoAIMesso", "Famiglia", "Bollette & Utenze", "2026"]

    # Chat Famiglia: scontrino senza scadenza
    path_scontrino = resolve_drive_folder_path("scontrino", None, chat_folder="Famiglia")
    assert path_scontrino == ["DoveLoAIMesso", "Famiglia", "Fatture & Spese"]

    # Chat Lavoro & Studio con category_label personalizzata
    path_lavoro = resolve_drive_folder_path("contratto", None, category_label="Contratti Lavoro", chat_folder="Lavoro & Studio")
    assert path_lavoro == ["DoveLoAIMesso", "Lavoro & Studio", "Contratti Lavoro"]

    # Chat Generale con sottocartella
    path_gen = resolve_drive_folder_path("canzone", None, category_label="Canzoni & Musica", subfolder="Bozze 2026", chat_folder="Generale")
    assert path_gen == ["DoveLoAIMesso", "Generale", "Canzoni & Musica", "Bozze 2026"]

    # Retrocompatibilità: senza chat_folder rimane identico al passato
    legacy = resolve_drive_folder_path("bolletta", date(2026, 10, 28))
    assert legacy == ["DoveLoAIMesso", "2026", "Bollette & Utenze"]


def test_resolve_drive_folder_path_categories():
    assert resolve_drive_folder_path("utenza", date(2024, 1, 1)) == ["DoveLoAIMesso", "2024", "Bollette & Utenze"]
    assert resolve_drive_folder_path("tributo", date(2023, 5, 20)) == ["DoveLoAIMesso", "2023", "Fisco & Tasse"]
    assert resolve_drive_folder_path("fiscale", None) == ["DoveLoAIMesso", "Fisco & Tasse"]
    assert resolve_drive_folder_path("modello_unico", date(2022, 11, 30)) == ["DoveLoAIMesso", "2022", "Fisco & Tasse"]
    assert resolve_drive_folder_path("fattura", date(2025, 4, 15)) == ["DoveLoAIMesso", "2025", "Fatture & Spese"]
    assert resolve_drive_folder_path("ricevuta", None) == ["DoveLoAIMesso", "Fatture & Spese"]
    assert resolve_drive_folder_path("scontrino", None) == ["DoveLoAIMesso", "Fatture & Spese"]
    assert resolve_drive_folder_path("contratto", date(2026, 2, 1)) == ["DoveLoAIMesso", "2026", "Contratti & Polizze"]
    assert resolve_drive_folder_path("certificato", None) == ["DoveLoAIMesso", "Contratti & Polizze"]
    assert resolve_drive_folder_path("polizza", date(2027, 8, 10)) == ["DoveLoAIMesso", "2027", "Contratti & Polizze"]
    assert resolve_drive_folder_path("sconosciuto", None) == ["DoveLoAIMesso", "Documenti & Foto"]
    assert resolve_drive_folder_path("  BOLLETTA  ", date(2026, 10, 28)) == ["DoveLoAIMesso", "2026", "Bollette & Utenze"]


def test_mock_drive_service_flow():
    service = MockGoogleDriveService()
    auth_url = service.get_auth_url(state="random-state-123")
    assert "accounts.google.com" in auth_url or "mock-auth" in auth_url
    assert "random-state-123" in auth_url

    token_data = service.exchange_code("mock_code")
    assert "access_token" in token_data
    assert "refresh_token" in token_data
    assert token_data["access_token"] == "mock-access-token"
    assert token_data["email"] == "mock.user@gmail.com"

    upload_result = service.upload_file(
        file_bytes=b"%PDF-1.4 mock content",
        filename="2026-10-28_Enel_64.20eur.pdf",
        mime_type="application/pdf",
        folder_path=["DoveLoAIMesso", "2026", "Bollette & Utenze"],
        access_token=token_data["access_token"]
    )
    assert "file_id" in upload_result
    assert "web_view_link" in upload_result
    assert upload_result["file_id"].startswith("drive-mock-")
    assert "drive.google.com" in upload_result["web_view_link"]


def test_get_drive_service_selection(monkeypatch):
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    service_mock = get_drive_service()
    assert isinstance(service_mock, MockGoogleDriveService)

    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-client-secret")
    service_real = get_drive_service()
    assert isinstance(service_real, RealGoogleDriveService)


def test_real_drive_service_auth_url():
    service = RealGoogleDriveService(
        client_id="my-client-id",
        client_secret="my-client-secret",
        redirect_uri="http://localhost:8000/api/drive/callback"
    )
    auth_url = service.get_auth_url(state="state_xyz")
    assert "accounts.google.com" in auth_url
    assert "my-client-id" in auth_url
    assert "state_xyz" in auth_url
    assert "code" in auth_url


def test_real_drive_service_exchange_code():
    def mock_handler(request: httpx.Request):
        if "oauth2.googleapis.com/token" in str(request.url):
            return httpx.Response(200, json={
                "access_token": "real-access-token-123",
                "refresh_token": "real-refresh-token-456",
                "expires_in": 3599,
                "token_type": "Bearer"
            })
        if "googleapis.com/oauth2/v2/userinfo" in str(request.url):
            return httpx.Response(200, json={
                "email": "real.user@gmail.com"
            })
        return httpx.Response(404)

    transport = httpx.MockTransport(mock_handler)
    with httpx.Client(transport=transport) as client:
        service = RealGoogleDriveService(
            client_id="my-client-id",
            client_secret="my-client-secret",
            redirect_uri="http://localhost:8000/api/drive/callback",
            http_client=client
        )
        token_data = service.exchange_code("sample_auth_code")
        assert token_data["access_token"] == "real-access-token-123"
        assert token_data["refresh_token"] == "real-refresh-token-456"
        assert token_data["email"] == "real.user@gmail.com"


def test_real_drive_service_upload_file():
    def mock_handler(request: httpx.Request):
        url_str = str(request.url)
        # Search folder or create folder
        if "googleapis.com/drive/v3/files" in url_str and request.method == "GET":
            # Return empty list first to trigger create
            return httpx.Response(200, json={"files": []})
        if "googleapis.com/drive/v3/files" in url_str and request.method == "POST":
            # Folder created
            return httpx.Response(200, json={"id": "folder-id-789", "name": "DoveLoAIMesso"})
        if "googleapis.com/upload/drive/v3/files" in url_str and request.method == "POST":
            # File uploaded
            return httpx.Response(200, json={
                "id": "file-id-999",
                "webViewLink": "https://drive.google.com/file/d/file-id-999/view"
            })
        return httpx.Response(404)

    transport = httpx.MockTransport(mock_handler)
    with httpx.Client(transport=transport) as client:
        service = RealGoogleDriveService(
            client_id="my-client-id",
            client_secret="my-client-secret",
            redirect_uri="http://localhost:8000/api/drive/callback",
            http_client=client
        )
        res = service.upload_file(
            file_bytes=b"test-pdf-bytes",
            filename="document.pdf",
            mime_type="application/pdf",
            folder_path=["DoveLoAIMesso"],
            access_token="fake-token"
        )
        assert res["file_id"] == "file-id-999"
        assert res["web_view_link"] == "https://drive.google.com/file/d/file-id-999/view"


def test_real_drive_service_get_or_create_folder_queries():
    recorded_queries = []

    def mock_handler(request: httpx.Request):
        url_str = str(request.url)
        if "googleapis.com/drive/v3/files" in url_str and request.method == "GET":
            q_param = request.url.params.get("q", "")
            recorded_queries.append(q_param)
            return httpx.Response(200, json={"files": [{"id": "found-folder-id", "name": "Test"}]})
        return httpx.Response(404)

    transport = httpx.MockTransport(mock_handler)
    with httpx.Client(transport=transport) as client:
        service = RealGoogleDriveService(
            client_id="my-client-id",
            client_secret="my-client-secret",
            redirect_uri="http://localhost:8000/api/drive/callback",
            http_client=client
        )
        # Root folder search
        service.get_or_create_folder("DoveLoAIMesso", None, "token", client)
        assert len(recorded_queries) == 1
        assert "'root' in parents" in recorded_queries[0]

        # Nested folder search
        service.get_or_create_folder("2026", "parent-123", "token", client)
        assert len(recorded_queries) == 2
        assert "'parent-123' in parents" in recorded_queries[1]

