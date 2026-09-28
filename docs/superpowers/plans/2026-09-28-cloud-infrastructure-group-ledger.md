# Cloud Infrastructure & Group Activity Ledger Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Progettare e implementare l'infrastruttura cloud multi-account, la gestione dei gruppi con codici d'invito e il registro operativo degli eventi condivisi (Activity Ledger) per famiglie e team, con autenticazione Supabase JWT, storage ibrido Cloudflare R2 e broadcast WebSockets su FastAPI/Railway.

**Architecture:** Backend FastAPI con SQLAlchemy PostgreSQL (Supabase), autenticazione JWT asimmetrica (`get_current_user`), Object Storage compatibile S3 (Cloudflare R2 con presigned URLs a 15 minuti per i file di gruppo), WebSocket Connection Manager per il live broadcast delle attività e Dockerfile ottimizzato per il deployment continuo su Railway.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy, PostgreSQL / SQLite (test suite), PyJWT, Boto3 (Cloudflare R2), WebSockets, Pydantic v2, Docker.

**Spec:** [`docs/superpowers/specs/2026-09-28-cloud-infrastructure-design.md`](file:///c:/Users/Leo/Desktop/DOVE-LO-AI-MESSO/docs/superpowers/specs/2026-09-28-cloud-infrastructure-design.md)

## Global Constraints
- I messaggi nei gruppi sono **esclusivamente eventi di protocollo e registro operativo** (`DOCUMENT_UPLOADED`, `DOCUMENT_PAID`, `ITEM_STORED`, `DEADLINE_ALERT`, `AI_ASSISTANT_QUERY`). Nessuna chat sociale/informale libera.
- I file personali rimangono nel perimetro privato dell'utente (locale / Google Drive personale); i file di gruppo risiedono nel bucket R2 con accesso protetto via presigned URL.
- Zero downtime e totale retrocompatibilità: l'app continua a supportare il funzionamento locale/offline deterministico se le credenziali cloud non sono configurate.
- Tutte le modifiche al codice devono mantenere l'incremento di versione conforme alla Regola 4 di `AGENTS.md`.

## Review Focus
1. Utente non autorizzato che tenta di accedere a documenti o messaggi di un gruppo di cui non fa parte (deve restituire 403 Forbidden).
2. Codice di invito gruppo errato o scaduto durante la join (deve restituire 404/400 con messaggio chiaro).
3. Token JWT manomesso, scaduto o non firmato da Supabase (deve restituire 401 Unauthorized immediato).
4. Generazione presigned URL R2 per file inesistente o per membro non autorizzato (deve impedire la generazione del link).
5. Connessione WebSocket che si disconnette bruscamente (il connection manager deve pulire la connessione in memoria senza provocare memory leak o crash).

---

### Task 1: Database Models for Multi-Account & Group Ledger

**Files:**
- Modify: `app/models/database.py`
- Test: `tests/test_cloud_database_models.py`

**Interfaces:**
- Consumes: SQLAlchemy `Base`, `init_db`, `Session`
- Produces: `User`, `Group`, `GroupMember`, `ActivityEvent` models, e campi `group_id` su `Document` e `PhysicalItem`.

- [ ] **Step 1: Write the failing test in `tests/test_cloud_database_models.py`**

```python
from app.models.database import init_db, get_engine, User, Group, GroupMember, ActivityEvent, Document
from sqlalchemy.orm import Session

def test_create_group_and_membership():
    engine = get_engine("sqlite:///:memory:")
    init_db(engine)
    with Session(engine) as db:
        user1 = User(id="user-123", email="marco@test.it", full_name="Marco Rossi")
        group = Group(id="group-abc", name="Famiglia Rossi", invite_code="ROX-8821", created_by=user1.id)
        db.add_all([user1, group])
        db.flush()

        member = GroupMember(group_id=group.id, user_id=user1.id, role="admin")
        event = ActivityEvent(
            group_id=group.id,
            actor_user_id=user1.id,
            actor_name="Marco",
            event_type="DOCUMENT_UPLOADED",
            title="Bolletta Enel"
        )
        db.add_all([member, event])
        db.commit()

        assert group.name == "Famiglia Rossi"
        assert event.event_type == "DOCUMENT_UPLOADED"
        assert member.role == "admin"
```

- [ ] **Step 2: Run test to verify it fails**
Run: `python -m pytest tests/test_cloud_database_models.py -v`
Expected: FAIL with `ImportError: cannot import name 'User'`

- [ ] **Step 3: Implement `User`, `Group`, `GroupMember`, `ActivityEvent` in `app/models/database.py`**
Aggiungere le classi ORM con vincoli foreign key e aggiungere colonne opzionali `group_id` su `Document` e `PhysicalItem`.

- [ ] **Step 4: Run test to verify it passes**
Run: `python -m pytest tests/test_cloud_database_models.py -v`
Expected: PASS

- [ ] **Step 5: Commit**
```bash
git add app/models/database.py tests/test_cloud_database_models.py
git commit -m "feat(database): add User, Group, GroupMember, and ActivityEvent models"
```

---

### Task 2: Supabase Auth JWT Verification Dependency

**Files:**
- Create: `app/services/auth_service.py`
- Modify: `app/config.py`
- Test: `tests/test_cloud_auth.py`

**Interfaces:**
- Consumes: `get_settings()`, `HTTPBearer`, PyJWT
- Produces: `verify_supabase_jwt(token: str) -> dict`, `get_current_user(token: str) -> dict`

- [ ] **Step 1: Write the failing test in `tests/test_cloud_auth.py`**

```python
import jwt
from app.services.auth_service import verify_supabase_jwt, get_current_user

def test_verify_valid_jwt():
    secret = "test-secret-key-32-bytes-minimum!!"
    payload = {"sub": "user-uuid-123", "email": "test@example.com", "role": "authenticated"}
    token = jwt.encode(payload, secret, algorithm="HS256")
    
    user_data = verify_supabase_jwt(token, secret=secret)
    assert user_data["sub"] == "user-uuid-123"
    assert user_data["email"] == "test@example.com"

def test_verify_expired_or_invalid_jwt():
    import pytest
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        verify_supabase_jwt("invalid-token-string", secret="secret")
    assert exc.value.status_code == 401
```

- [ ] **Step 2: Run test to verify it fails**
Run: `python -m pytest tests/test_cloud_auth.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.auth_service'`

- [ ] **Step 3: Implement `app/services/auth_service.py`**
Implementare decodifica JWT con PyJWT, gestione eccezioni `ExpiredSignatureError` e `InvalidTokenError`, e dependency `get_current_user` con fallback di sviluppo.

- [ ] **Step 4: Run test to verify it passes**
Run: `python -m pytest tests/test_cloud_auth.py -v`
Expected: PASS

- [ ] **Step 5: Commit**
```bash
git add app/services/auth_service.py app/config.py tests/test_cloud_auth.py
git commit -m "feat(auth): implement Supabase JWT verification and FastAPI dependency"
```

---

### Task 3: Group Management & Membership API Endpoints

**Files:**
- Create: `app/api/groups.py`
- Modify: `app/main.py`
- Test: `tests/test_groups_api.py`

**Interfaces:**
- Consumes: `get_current_user`, `get_db`, `Group`, `GroupMember`, `User`
- Produces: `POST /api/groups`, `GET /api/groups`, `POST /api/groups/join`, `GET /api/groups/{id}/members`

- [ ] **Step 1: Write the failing test in `tests/test_groups_api.py`**

```python
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_create_and_join_group(monkeypatch):
    # Mock auth user
    monkeypatch.setattr("app.services.auth_service.get_current_user", lambda: {"sub": "user-test-1", "email": "admin@test.it"})
    
    # 1. Create group
    res = client.post("/api/groups", json={"name": "Casa Mare", "description": "Spese condivise"})
    assert res.status_code == 201
    group_data = res.json()
    invite_code = group_data["invite_code"]
    group_id = group_data["id"]

    # 2. Join group with user 2
    monkeypatch.setattr("app.services.auth_service.get_current_user", lambda: {"sub": "user-test-2", "email": "ospite@test.it"})
    join_res = client.post("/api/groups/join", json={"invite_code": invite_code})
    assert join_res.status_code == 200
    assert join_res.json()["group_id"] == group_id
```

- [ ] **Step 2: Run test to verify it fails**
Run: `python -m pytest tests/test_groups_api.py -v`
Expected: FAIL with 404 Not Found on `/api/groups`

- [ ] **Step 3: Implement `app/api/groups.py` and register in `app/main.py`**
Creare router con Pydantic schemas per creazione gruppo, generazione codice invito casuale alfanumerico univoco (`UUID` o token 8 caratteri), e controllo appartenenza.

- [ ] **Step 4: Run test to verify it passes**
Run: `python -m pytest tests/test_groups_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**
```bash
git add app/api/groups.py app/main.py tests/test_groups_api.py
git commit -m "feat(api): implement group creation, invite codes, and membership endpoints"
```

---

### Task 4: Activity Ledger & Event Recording Service

**Files:**
- Create: `app/services/activity_service.py`
- Modify: `app/api/documents.py` (hook upload and status update)
- Test: `tests/test_activity_service.py`

**Interfaces:**
- Consumes: `ActivityEvent`, `db: Session`
- Produces: `record_activity_event(db, group_id, actor_id, actor_name, event_type, title, ...) -> ActivityEvent`

- [ ] **Step 1: Write the failing test in `tests/test_activity_service.py`**

```python
from app.services.activity_service import record_activity_event
from app.models.database import ActivityEvent

def test_record_activity_event(db_session):
    event = record_activity_event(
        db=db_session,
        group_id="group-1",
        actor_user_id="user-1",
        actor_name="Marco",
        event_type="DOCUMENT_UPLOADED",
        title="Bolletta Enel",
        content="Importo 64.20 €",
        payload={"amount": 64.20, "due_date": "2026-10-28"}
    )
    assert event.id is not None
    assert event.event_type == "DOCUMENT_UPLOADED"
    assert event.actor_name == "Marco"
    assert event.payload["amount"] == 64.20
```

- [ ] **Step 2: Run test to verify it fails**
Run: `python -m pytest tests/test_activity_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.activity_service'`

- [ ] **Step 3: Implement `app/services/activity_service.py` and hook into document pipeline**
Implementare `record_activity_event` e `list_group_activity_feed` con filtri per data e paginazione.

- [ ] **Step 4: Run test to verify it passes**
Run: `python -m pytest tests/test_activity_service.py -v`
Expected: PASS

- [ ] **Step 5: Commit**
```bash
git add app/services/activity_service.py app/api/documents.py tests/test_activity_service.py
git commit -m "feat(ledger): implement shared group activity event logging service"
```

---

### Task 5: Cloudflare R2 Group Storage Client & Presigned URLs

**Files:**
- Create: `app/services/r2_service.py`
- Modify: `app/api/documents.py`
- Test: `tests/test_r2_storage.py`

**Interfaces:**
- Consumes: Boto3 S3 client, `R2StorageServiceInterface`
- Produces: `upload_group_file`, `generate_presigned_download_url(file_key, expires_in=900) -> str`

- [ ] **Step 1: Write the failing test in `tests/test_r2_storage.py`**

```python
from app.services.r2_service import MockR2StorageService

def test_mock_r2_upload_and_presigned_url():
    r2 = MockR2StorageService()
    file_key = r2.upload_group_file(
        file_bytes=b"%PDF-1.4 test",
        filename="fattura.pdf",
        group_id="group-123",
        category="utenze"
    )
    assert "group-123" in file_key
    assert file_key.endswith(".pdf")

    url = r2.generate_presigned_download_url(file_key, expires_in=900)
    assert "https://" in url
    assert "X-Amz-Signature" in url or "mock_signature" in url
```

- [ ] **Step 2: Run test to verify it fails**
Run: `python -m pytest tests/test_r2_storage.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.r2_service'`

- [ ] **Step 3: Implement `app/services/r2_service.py` with Mock and Real Boto3 client**
Implementare `RealR2StorageService` e `MockR2StorageService` con factory `get_r2_service()`.

- [ ] **Step 4: Run test to verify it passes**
Run: `python -m pytest tests/test_r2_storage.py -v`
Expected: PASS

- [ ] **Step 5: Commit**
```bash
git add app/services/r2_service.py tests/test_r2_storage.py
git commit -m "feat(storage): implement Cloudflare R2 object storage client and presigned URLs"
```

---

### Task 6: Real-Time WebSocket Connection Manager & Broadcast Feed

**Files:**
- Create: `app/services/websocket_manager.py`
- Modify: `app/api/groups.py`
- Test: `tests/test_group_websockets.py`

**Interfaces:**
- Consumes: FastAPI `WebSocket`, `WebSocketDisconnect`
- Produces: `GroupWebSocketManager`, `broadcast_to_group(group_id, message_dict)`

- [ ] **Step 1: Write the failing test in `tests/test_group_websockets.py`**

```python
import pytest
from app.services.websocket_manager import GroupWebSocketManager

@pytest.mark.asyncio
async def test_websocket_manager_connect_and_broadcast():
    manager = GroupWebSocketManager()
    
    class DummyWS:
        def __init__(self):
            self.sent = []
        async def accept(self): pass
        async def send_json(self, data): self.sent.append(data)
    
    ws1 = DummyWS()
    ws2 = DummyWS()
    
    await manager.connect("group-1", ws1)
    await manager.connect("group-1", ws2)
    
    await manager.broadcast("group-1", {"event": "DOCUMENT_UPLOADED", "title": "Enel"})
    assert len(ws1.sent) == 1
    assert len(ws2.sent) == 1
    assert ws1.sent[0]["event"] == "DOCUMENT_UPLOADED"
```

- [ ] **Step 2: Run test to verify it fails**
Run: `python -m pytest tests/test_group_websockets.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.websocket_manager'`

- [ ] **Step 3: Implement `GroupWebSocketManager` in `app/services/websocket_manager.py`**
Implementare gestione connessioni per stanza (`group_id`), lock asincrono per rimozione pulita e broadcast non bloccante.

- [ ] **Step 4: Run test to verify it passes**
Run: `python -m pytest tests/test_group_websockets.py -v`
Expected: PASS

- [ ] **Step 5: Commit**
```bash
git add app/services/websocket_manager.py tests/test_group_websockets.py
git commit -m "feat(realtime): implement group WebSocket manager and live event broadcast"
```

---

### Task 7: Dockerfile & Railway Deployment Configuration

**Files:**
- Create: `Dockerfile`
- Create: `railway.json`
- Modify: `app/main.py` (endpoint `/api/health`)
- Test: `tests/test_health_and_deployment.py`

**Interfaces:**
- Consumes: `GET /api/health`
- Produces: Production Docker container setup, Railway deployment manifest.

- [ ] **Step 1: Write the failing test in `tests/test_health_and_deployment.py`**

```python
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_health_check_endpoint():
    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "healthy"
    assert "version" in data
    assert "database" in data
```

- [ ] **Step 2: Run test to verify it fails**
Run: `python -m pytest tests/test_health_and_deployment.py -v`
Expected: FAIL with 404 Not Found on `/api/health`

- [ ] **Step 3: Implement `/api/health` in `app/main.py`, create `Dockerfile` and `railway.json`**
Aggiungere healthcheck dettagliato, Dockerfile multi-stage con Python 3.12-slim e configurazione Railway per avviare Uvicorn.

- [ ] **Step 4: Run test to verify it passes**
Run: `python -m pytest tests/test_health_and_deployment.py -v`
Expected: PASS

- [ ] **Step 5: Commit**
```bash
git add Dockerfile railway.json app/main.py tests/test_health_and_deployment.py
git commit -m "feat(deployment): configure production Dockerfile, Railway manifest, and healthcheck"
```
