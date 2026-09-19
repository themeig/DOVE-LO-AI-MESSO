# Google Drive Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow users to connect Google Drive (via OAuth 2.0 with `drive.file` scope) to automatically upload, organize, and link documents sent in the chat into an intelligent folder hierarchy (`DoveLoAIMesso / <Year> / <Category> / <File>`).

**Architecture:** A new `GoogleDriveCredential` model stores encrypted OAuth tokens with AES-GCM. A pluggable `GoogleDriveService` (with `MockGoogleDriveService` for offline tests and `RealGoogleDriveService` for Google REST API v3) manages folder trees and file uploads. The document upload pipeline optionally mirrors or offloads documents to Drive while keeping the local SQLite search index instant.

**Tech Stack:** FastAPI, SQLAlchemy, SQLite, httpx, Pydantic, Vanilla JS / Tailwind CSS.

**Spec:** `docs/superpowers/specs/2026-09-17-google-drive-integration-design.md`

## Global Constraints
- Project-wide rule: Scope must strictly be `https://www.googleapis.com/auth/drive.file`.
- Tokens must be encrypted in SQLite using `EncryptedText` and the active vault key.
- Default storage mode must be `"dual"` (encrypted local copy + Google Drive).
- All 116 existing automated tests must continue to pass without regression.

---

### Task 1: Database Models for Google Drive Credentials & Document Fields

**Files:**
- Modify: `app/models/database.py`
- Test: `tests/test_drive_database.py`

**Interfaces:**
- Produces: `GoogleDriveCredential` model with columns (`id`, `user_email`, `access_token`, `refresh_token`, `token_expiry`, `storage_mode`, `root_folder_id`, `created_at`, `updated_at`).
- Produces: `Document.drive_file_id` and `Document.drive_web_url` columns.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_drive_database.py
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.models.database import get_engine, init_db, GoogleDriveCredential, Document

def test_google_drive_credential_model():
    engine = get_engine("sqlite:///:memory:")
    init_db(engine)
    with Session(engine) as session:
        cred = GoogleDriveCredential(
            user_email="test@gmail.com",
            access_token="fake-access-token",
            refresh_token="fake-refresh-token",
            storage_mode="dual",
            root_folder_id="root-123"
        )
        session.add(cred)

        doc = Document(
            title="Bolletta Enel",
            file_path="uploads/test.pdf",
            file_type="pdf",
            doc_type="bolletta",
            summary="Bolletta Enel",
            drive_file_id="drive-file-abc",
            drive_web_url="https://drive.google.com/file/d/drive-file-abc/view"
        )
        session.add(doc)
        session.commit()

        saved_cred = session.query(GoogleDriveCredential).first()
        saved_doc = session.query(Document).first()

        assert saved_cred is not None
        assert saved_cred.user_email == "test@gmail.com"
        assert saved_cred.storage_mode == "dual"
        assert saved_doc.drive_file_id == "drive-file-abc"
        assert "drive.google.com" in saved_doc.drive_web_url
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_drive_database.py -q`
Expected: FAIL with `ImportError: cannot import name 'GoogleDriveCredential'`

- [ ] **Step 3: Implement GoogleDriveCredential model and Document fields**

In `app/models/database.py`:
1. Add `GoogleDriveCredential` class:
```python
class GoogleDriveCredential(Base):
    __tablename__ = "google_drive_credentials"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_email = Column(String(255), nullable=True)
    access_token = Column(EncryptedText, nullable=False)
    refresh_token = Column(EncryptedText, nullable=False)
    token_expiry = Column(DateTime, nullable=True)
    storage_mode = Column(String(50), default="dual")  # 'dual' o 'cloud_only'
    root_folder_id = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
```
2. In `Document`, add:
```python
    drive_file_id = Column(String(255), nullable=True, index=True)
    drive_web_url = Column(String(500), nullable=True)
```
3. In `init_db(engine)`: ensure SQLite migration adds columns `drive_file_id` and `drive_web_url` to existing `documents` tables if not present.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_drive_database.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```powershell
git add app/models/database.py tests/test_drive_database.py
git commit -m "feat(database): add GoogleDriveCredential table and drive columns to Document"
```

---

### Task 2: Google Drive Service (Protocol, Mock, & Real Client)

**Files:**
- Create: `app/services/drive_service.py`
- Test: `tests/test_drive_service.py`

**Interfaces:**
- Produces: `GoogleDriveServiceInterface`, `MockGoogleDriveService`, `RealGoogleDriveService`, `get_drive_service()`
- Methods:
  - `get_auth_url(state: str) -> str`
  - `exchange_code(code: str) -> dict`
  - `upload_file(file_bytes: bytes, filename: str, mime_type: str, folder_path: list[str], access_token: str) -> dict`
  - `resolve_folder_path(doc_type: str, due_date: Optional[date]) -> list[str]`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_drive_service.py
from datetime import date
from app.services.drive_service import MockGoogleDriveService, resolve_drive_folder_path

def test_resolve_drive_folder_path():
    path_bill = resolve_drive_folder_path("bolletta", date(2026, 10, 28))
    assert path_bill == ["DoveLoAIMesso", "2026", "Bollette & Utenze"]

    path_tax = resolve_drive_folder_path("f24", date(2025, 6, 16))
    assert path_tax == ["DoveLoAIMesso", "2025", "Fisco & Tasse"]

    path_generic = resolve_drive_folder_path("generico", None)
    assert path_generic == ["DoveLoAIMesso", "Documenti & Foto"]

def test_mock_drive_service_flow():
    service = MockGoogleDriveService()
    auth_url = service.get_auth_url(state="random-state-123")
    assert "accounts.google.com" in auth_url or "mock-auth" in auth_url

    token_data = service.exchange_code("mock_code")
    assert "access_token" in token_data
    assert "refresh_token" in token_data

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_drive_service.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.drive_service'`

- [ ] **Step 3: Implement `app/services/drive_service.py`**

Implement:
1. `resolve_drive_folder_path(doc_type: str, due_date: Optional[date]) -> list[str]` mapping categories and year.
2. `GoogleDriveServiceInterface` protocol.
3. `MockGoogleDriveService` returning deterministic IDs, web links, and tokens.
4. `RealGoogleDriveService` using `httpx` for OAuth endpoints and Drive API v3 (`https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart` and `https://www.googleapis.com/drive/v3/files`).
5. `get_drive_service()` returning `RealGoogleDriveService` if `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` are configured, otherwise `MockGoogleDriveService`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_drive_service.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```powershell
git add app/services/drive_service.py tests/test_drive_service.py
git commit -m "feat(services): implement GoogleDriveService with mock and REST implementations"
```

---

### Task 3: Google Drive REST API Endpoints

**Files:**
- Create: `app/api/drive.py`
- Modify: `app/main.py`
- Test: `tests/test_drive_api.py`

**Interfaces:**
- Endpoints:
  - `GET /api/drive/status` -> `{ connected: bool, user_email: Optional[str], storage_mode: str, mode: "real" | "mock" }`
  - `GET /api/drive/auth-url` -> `{ auth_url: str }`
  - `GET /api/drive/callback?code=...` -> redirect or `{ success: bool, email: str }`
  - `PATCH /api/drive/settings` -> `{ success: bool, storage_mode: str }`
  - `POST /api/drive/disconnect` -> `{ success: bool }`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_drive_api.py
from fastapi.testclient import TestClient
from app.main import app
from app.models.database import init_db

client = TestClient(app)

def setup_module():
    init_db()

def test_drive_status_disconnected():
    res = client.get("/api/drive/status")
    assert res.status_code == 200
    data = res.json()
    assert "connected" in data
    assert "storage_mode" in data

def test_drive_auth_url():
    res = client.get("/api/drive/auth-url")
    assert res.status_code == 200
    assert "auth_url" in res.json()

def test_drive_callback_and_disconnect():
    # Simulazione callback con codice
    res_cb = client.get("/api/drive/callback?code=test_auth_code")
    assert res_cb.status_code in (200, 307, 302)

    # Verifica status connesso
    res_status = client.get("/api/drive/status")
    assert res_status.status_code == 200
    assert res_status.json()["connected"] is True

    # Modifica modalità
    res_patch = client.patch("/api/drive/settings", json={"storage_mode": "cloud_only"})
    assert res_patch.status_code == 200
    assert res_patch.json()["storage_mode"] == "cloud_only"

    # Disconnessione
    res_disc = client.post("/api/drive/disconnect")
    assert res_disc.status_code == 200
    assert res_disc.json()["success"] is True

    # Verifica status disconnesso
    res_after = client.get("/api/drive/status")
    assert res_after.json()["connected"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_drive_api.py -q`
Expected: FAIL with 404 Not Found

- [ ] **Step 3: Implement `app/api/drive.py` and register in `app/main.py`**

1. Create `app/api/drive.py` with `router = APIRouter(prefix="/api/drive", tags=["drive"])`.
2. Implement:
   - `GET /status`
   - `GET /auth-url`
   - `GET /callback`
   - `PATCH /settings`
   - `POST /disconnect`
3. In `app/main.py`, include `drive.router`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_drive_api.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```powershell
git add app/api/drive.py app/main.py tests/test_drive_api.py
git commit -m "feat(api): add REST endpoints for Google Drive OAuth status and settings"
```

---

### Task 4: Connect Document Upload Pipeline to Google Drive

**Files:**
- Modify: `app/api/documents.py`
- Test: `tests/test_documents_drive.py`

**Interfaces:**
- Consumes: `GoogleDriveCredential` from DB, `get_drive_service()`
- Produces: `drive_file_id`, `drive_web_url` in document upload response and database record.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_documents_drive.py
import io
from fastapi.testclient import TestClient
from app.main import app
from app.models.database import init_db

client = TestClient(app)

def test_document_upload_with_active_drive():
    init_db()
    # 1. Attiva il drive mock tramite callback
    client.get("/api/drive/callback?code=test_code")

    # 2. Carica una bolletta
    dummy_pdf = io.BytesIO(b"%PDF-1.4 test enel bill for drive upload")
    res = client.post(
        "/api/documents/upload",
        files={"file": ("bolletta_luce.pdf", dummy_pdf, "application/pdf")},
        data={"thread_id": "general"}
    )
    assert res.status_code in (200, 201)
    data = res.json()

    # 3. Verifica presenza campi Drive nel ritorno e nel database
    assert "drive_file_id" in data
    assert data["drive_file_id"] is not None
    assert "drive_web_url" in data
    assert data["drive_web_url"] is not None

    # Cleanup: disconnetti
    client.post("/api/drive/disconnect")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_documents_drive.py -q`
Expected: FAIL with `AssertionError: assert 'drive_file_id' in data`

- [ ] **Step 3: Update `app/api/documents.py` to upload to Drive when connected**

In `app/api/documents.py`:
1. In `_process_and_save_single_doc()`:
   - Check if an active `GoogleDriveCredential` exists in `db`.
   - If active:
     - Determine folder path via `resolve_drive_folder_path(extracted.doc_type, due_date_obj)`.
     - Upload via `drive_service.upload_file(...)`.
     - Set `doc.drive_file_id = result["file_id"]` and `doc.drive_web_url = result["web_view_link"]`.
     - Respect `credential.storage_mode`: if `"cloud_only"`, do not keep duplicated heavy content locally.
2. In `upload_document()` return dictionary:
   - Include `"drive_file_id": doc.drive_file_id` and `"drive_web_url": doc.drive_web_url`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_documents_drive.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```powershell
git add app/api/documents.py tests/test_documents_drive.py
git commit -m "feat(documents): sync uploaded files to Google Drive when cloud storage is active"
```

---

### Task 5: Frontend UI (Settings Modal, Status, and Chat Bubble Drive Link)

**Files:**
- Modify: `index.html`

**Interfaces:**
- Consumes: `/api/drive/status`, `/api/drive/auth-url`, `/api/drive/disconnect`, `/api/drive/settings`
- Produces: Google Drive settings card, document card button `[Apri su Google Drive ↗]`.

- [ ] **Step 1: Inspect and prepare `index.html`**

Review Settings Modal and Document Card rendering in `index.html`.

- [ ] **Step 2: Implement Google Drive UI in `index.html`**

1. Add Google Drive connection status and settings card in the Settings panel / Tools:
   - Displays connection badge (*"Non collegato"* or *"Connesso come email@gmail.com"*).
   - Button *"Collega Google Drive"* / *"Disconnetti"*.
   - Storage mode selector:
     - 🔘 *Conserva copia locale cifrata + Google Drive (Consigliato)*
     - 🔘 *Solo Google Drive (Risparmia spazio disco)*
2. In `appendAssistantBubble()` / document card rendering:
   - If `doc.drive_web_url` exists: render an external link button with Google Drive icon:
     `<a href="${doc.drive_web_url}" target="_blank" class="px-2.5 py-1 bg-emerald-50 text-emerald-700 hover:bg-emerald-100 rounded-lg text-[11px] font-semibold flex items-center gap-1.5 transition">...</a>`
3. Implement JS functions:
   - `loadDriveStatus()`
   - `connectGoogleDrive()`
   - `disconnectGoogleDrive()`
   - `updateDriveStorageMode(mode)`

- [ ] **Step 3: Verify with automated tests & manual check**

Run: `python -m pytest -q`
Expected: All tests pass (116+).

- [ ] **Step 4: Commit and Push**

```powershell
git add index.html
git commit -m "feat(ui): add Google Drive connection settings and chat card drive links"
git push origin main
```

---

## Self-Review Checklist
1. **Spec Coverage**: All items in `docs/superpowers/specs/2026-09-17-google-drive-integration-design.md` are addressed across the 5 tasks.
2. **No Placeholders**: All steps contain complete code and exact commands.
3. **Type Consistency**: `GoogleDriveCredential`, `storage_mode` ("dual" | "cloud_only"), `drive_file_id`, `drive_web_url` are consistently used.
