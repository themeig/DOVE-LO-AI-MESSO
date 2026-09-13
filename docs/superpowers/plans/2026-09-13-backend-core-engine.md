# Backend Core Engine & API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the complete Python FastAPI backend, SQLite database, Pydantic AI extraction engine, and REST endpoints for "Dove L'Ho Messo", fully connecting the frontend chat and dashboard.

**Architecture:** Clean Layered FastAPI architecture. The API layer delegates to specialized services (`ai_service`, `document_service`) that read and persist entities in an embedded SQLite database (`vault.db`). Pluggable AI provider supports both real Gemini Flash API and an offline Mock for deterministic TDD.

**Tech Stack:** Python 3.12+, FastAPI, Uvicorn, SQLAlchemy, Pydantic V2, Pytest, HTTPX, SQLite.

**Spec:** [`docs/superpowers/specs/2026-09-13-software-architecture-design.md`](file:///c:/Users/Leo/Desktop/DOVE-LO-AI-MESSO/docs/superpowers/specs/2026-09-13-software-architecture-design.md)

## Global Constraints
- Target platform: Windows / cross-platform Python 3.12+
- Database: Embedded SQLite (`storage/vault.db`)
- Zero mandatory cloud dependencies during test suite: `MockAIService` must allow 100% offline passing test runs
- Frontend contract: serve `index.html` statically on `/` and expose REST APIs under `/api/`

---

### Task 1: Scaffolding, Dependencies & Environment Config

**Files:**
- Create: `requirements.txt`
- Create: `app/__init__.py`
- Create: `app/config.py`
- Create: `tests/__init__.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `app.config.Settings` (providing `DATABASE_URL`, `STORAGE_DIR`, `GEMINI_API_KEY`, `DEBUG`)

- [ ] **Step 1: Write the failing test for configuration**

```python
# tests/test_config.py
from app.config import get_settings

def test_settings_load_defaults():
    settings = get_settings()
    assert settings.DATABASE_URL.startswith("sqlite:///")
    assert settings.STORAGE_DIR is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py`
Expected: FAIL (ModuleNotFoundError or ImportError)

- [ ] **Step 3: Write requirements.txt and app/config.py**

```text
# requirements.txt
fastapi>=0.115.0
uvicorn>=0.30.0
sqlalchemy>=2.0.0
pydantic>=2.8.0
python-multipart>=0.0.9
httpx>=0.27.0
pytest>=8.0.0
```

```python
# app/config.py
from pathlib import Path
from pydantic import BaseModel
import os

class Settings(BaseModel):
    BASE_DIR: Path = Path(__file__).resolve().parent.parent
    STORAGE_DIR: Path = BASE_DIR / "storage" / "uploads"
    DB_PATH: Path = BASE_DIR / "storage" / "vault.db"
    DATABASE_URL: str = f"sqlite:///{DB_PATH}"
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    DEBUG: bool = True

_settings = None

def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
        _settings.STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    return _settings
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_config.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add requirements.txt app/__init__.py app/config.py tests/__init__.py tests/test_config.py
git commit -m "chore: scaffold project structure and config"
```

---

### Task 2: Database Models & SQLite Setup

**Files:**
- Create: `app/models/__init__.py`
- Create: `app/models/database.py`
- Test: `tests/test_database.py`

**Interfaces:**
- Consumes: `app.config.Settings`
- Produces: `app.models.database.Base`, `Document`, `PhysicalItem`, `ChatMessage`, `get_db()`, `init_db()`

- [ ] **Step 1: Write failing tests for Database Models**

```python
# tests/test_database.py
from datetime import date, datetime
from app.models.database import Document, PhysicalItem, ChatMessage, init_db, get_engine
from sqlalchemy.orm import Session

def test_document_and_item_crud():
    engine = get_engine("sqlite:///:memory:")
    init_db(engine)
    with Session(engine) as session:
        # 1. Document creation
        doc = Document(
            title="Bolletta Enel",
            file_path="uploads/test.pdf",
            file_type="pdf",
            doc_type="bolletta",
            issuer="Enel",
            amount=64.20,
            due_date=date(2026, 10, 28),
            status="da_pagare",
            summary="Bolletta luce"
        )
        session.add(doc)
        
        # 2. Item creation
        item = PhysicalItem(
            item_name="Passaporto",
            category="documenti",
            primary_location="Scrivania",
            detailed_location="1° Cassetto"
        )
        session.add(item)
        session.commit()
        
        saved_doc = session.query(Document).first()
        saved_item = session.query(PhysicalItem).first()
        assert saved_doc.amount == 64.20
        assert saved_item.detailed_location == "1° Cassetto"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_database.py`
Expected: FAIL with ImportError

- [ ] **Step 3: Implement database.py**

```python
# app/models/database.py
from datetime import datetime, date
from sqlalchemy import create_engine, Column, Integer, String, Float, Date, DateTime, Text
from sqlalchemy.orm import declarative_base, sessionmaker
from app.config import get_settings

Base = declarative_base()

class Document(Base):
    __tablename__ = "documents"
    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)
    file_type = Column(String(50), nullable=False)
    doc_type = Column(String(50), nullable=False, default="generico")
    issuer = Column(String(255), nullable=True)
    amount = Column(Float, nullable=True)
    due_date = Column(Date, nullable=True)
    status = Column(String(50), nullable=False, default="da_pagare")
    summary = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class PhysicalItem(Base):
    __tablename__ = "physical_items"
    id = Column(Integer, primary_key=True, autoincrement=True)
    item_name = Column(String(255), nullable=False, index=True)
    category = Column(String(100), nullable=True)
    primary_location = Column(String(255), nullable=False)
    detailed_location = Column(String(255), nullable=True)
    notes = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id = Column(Integer, primary_key=True, autoincrement=True)
    sender = Column(String(20), nullable=False) # 'user' or 'assistant'
    message_type = Column(String(20), default="text")
    content = Column(Text, nullable=False)
    metadata_json = Column(Text, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)

def get_engine(db_url: str = None):
    url = db_url or get_settings().DATABASE_URL
    return create_engine(url, connect_args={"check_same_thread": False})

def init_db(engine=None):
    eng = engine or get_engine()
    Base.metadata.create_all(bind=eng)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_database.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/models/database.py tests/test_database.py
git commit -m "feat(models): implement SQLite database tables and session factory"
```

---

### Task 3: Pydantic Schemas & Structured Data Contracts

**Files:**
- Create: `app/models/schemas.py`
- Test: `tests/test_schemas.py`

**Interfaces:**
- Produces: `ExtractedDocument`, `MessageIntent`, `ChatRequest`, `ChatResponse`, `DashboardResponse`, `DocumentStatusUpdate`

- [ ] **Step 1: Write failing test for Schemas**

```python
# tests/test_schemas.py
from app.models.schemas import ExtractedDocument, MessageIntent, ChatResponse

def test_extracted_document_schema():
    data = {
        "doc_type": "bolletta",
        "issuer": "Enel Energia",
        "amount": 64.20,
        "due_date": "2026-10-28",
        "summary": "Bolletta luce di ottobre",
        "tags": ["luce", "enel"]
    }
    doc = ExtractedDocument(**data)
    assert doc.amount == 64.20
    assert doc.issuer == "Enel Energia"

def test_message_intent_schema():
    intent = MessageIntent(
        intent="STORE_LOCATION",
        item_name="passaporto",
        primary_location="studio",
        detailed_location="scrivania"
    )
    assert intent.intent == "STORE_LOCATION"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_schemas.py`
Expected: FAIL with ImportError

- [ ] **Step 3: Implement app/models/schemas.py**

```python
# app/models/schemas.py
from typing import Literal, Optional, List
from pydantic import BaseModel, Field

class ExtractedDocument(BaseModel):
    doc_type: str = Field(default="generico", description="Tipo documento")
    issuer: str = Field(default="Sconosciuto", description="Ente o fornitore")
    amount: Optional[float] = Field(default=None, description="Importo in euro")
    due_date: Optional[str] = Field(default=None, description="Data scadenza YYYY-MM-DD")
    summary: str = Field(default="", description="Spiegazione semplice del documento")
    tags: List[str] = Field(default_factory=list)

class MessageIntent(BaseModel):
    intent: Literal["STORE_LOCATION", "QUERY_LOCATION", "QUERY_DEADLINES", "GENERAL"]
    item_name: Optional[str] = None
    primary_location: Optional[str] = None
    detailed_location: Optional[str] = None
    query_text: Optional[str] = None

class ChatRequest(BaseModel):
    message: str

class ChatResponse(BaseModel):
    reply: str
    action: str = "REPLY"
    data: Optional[dict] = None

class DocumentStatusUpdate(BaseModel):
    status: Literal["da_pagare", "quietanzato", "archiviato"]

class RecordItem(BaseModel):
    id: int
    type: str # 'document' or 'physical_item'
    title: str
    source: str
    amount: Optional[float] = None
    due_date: Optional[str] = None
    status: str
    location_or_notes: Optional[str] = None
    badge_color: str

class DashboardKPI(BaseModel):
    total_upcoming_amount: float
    pending_deadlines_count: int
    total_documents_count: int
    total_items_count: int

class DashboardResponse(BaseModel):
    kpi: DashboardKPI
    records: List[RecordItem]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_schemas.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/models/schemas.py tests/test_schemas.py
git commit -m "feat(schemas): define strict Pydantic schemas for AI extraction and API payload"
```

---

### Task 4: AI Extraction Engine with Pluggable Mock

**Files:**
- Create: `app/services/__init__.py`
- Create: `app/services/ai_service.py`
- Test: `tests/test_ai_service.py`

**Interfaces:**
- Consumes: `app.models.schemas.ExtractedDocument`, `MessageIntent`
- Produces: `AIServiceInterface`, `MockAIService`, `get_ai_service()`

- [ ] **Step 1: Write failing test for AI Service**

```python
# tests/test_ai_service.py
from app.services.ai_service import MockAIService

def test_mock_ai_extract_document():
    ai = MockAIService()
    result = ai.extract_document(b"fake pdf content", "application/pdf", filename="bolletta_enel.pdf")
    assert result.doc_type == "bolletta"
    assert result.amount == 64.20
    assert result.due_date == "2026-10-28"

def test_mock_ai_route_intent_store():
    ai = MockAIService()
    intent = ai.classify_and_extract_intent("Ho messo il passaporto nella scrivania in camera")
    assert intent.intent == "STORE_LOCATION"
    assert "passaporto" in (intent.item_name or "").lower()

def test_mock_ai_route_intent_query():
    ai = MockAIService()
    intent = ai.classify_and_extract_intent("Dov'è il passaporto?")
    assert intent.intent == "QUERY_LOCATION"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ai_service.py`
Expected: FAIL with ImportError

- [ ] **Step 3: Implement app/services/ai_service.py**

```python
# app/services/ai_service.py
import re
from typing import Protocol
from app.models.schemas import ExtractedDocument, MessageIntent
from app.config import get_settings

class AIServiceInterface(Protocol):
    def extract_document(self, file_bytes: bytes, mime_type: str, filename: str = "") -> ExtractedDocument:
        ...
    def classify_and_extract_intent(self, text: str) -> MessageIntent:
        ...

class MockAIService:
    """Deterministic offline AI Service for tests and development without API keys."""
    def extract_document(self, file_bytes: bytes, mime_type: str, filename: str = "") -> ExtractedDocument:
        fn = filename.lower()
        if "f24" in fn or "tribut" in fn:
            return ExtractedDocument(
                doc_type="f24",
                issuer="Agenzia delle Entrate",
                amount=2450.00,
                due_date="2026-09-16",
                summary="Modello F24 versamento IVA trimestrale.",
                tags=["f24", "fisco", "iva"]
            )
        # Default: Bolletta
        return ExtractedDocument(
            doc_type="bolletta",
            issuer="Enel Energia",
            amount=64.20,
            due_date="2026-10-28",
            summary="Bolletta Enel Luce bimestre agosto-settembre.",
            tags=["luce", "energia", "utenze"]
        )

    def classify_and_extract_intent(self, text: str) -> MessageIntent:
        t = text.lower()
        if "dov'è" in t or "dove si trova" in t or "dove ho messo" in t or "dove sono" in t:
            item = re.sub(r".*?(dov'è|dove si trova|dove ho messo|dove sono)\s+", "", t).strip(" ?.")
            return MessageIntent(intent="QUERY_LOCATION", item_name=item, query_text=text)
        
        if "scadenz" in t or "da pagare" in t or "quanto devo pagare" in t:
            return MessageIntent(intent="QUERY_DEADLINES", query_text=text)

        if "messo" in t or "riposto" in t or "lasciato" in t or "salvato" in t:
            # Extract basic parts: "Ho messo [oggetto] in [luogo]"
            item = "oggetto"
            loc = "posto specificato"
            m = re.search(r"(?:messo|riposto|salvato)\s+(?:il\s+|la\s+|le\s+|i\s+|l\')?(.+?)\s+(?:nel|nella|in|su|sul|sotto)\s+(.+)", t)
            if m:
                item = m.group(1).strip()
                loc = m.group(2).strip()
            return MessageIntent(
                intent="STORE_LOCATION",
                item_name=item,
                primary_location=loc,
                detailed_location=None
            )

        return MessageIntent(intent="GENERAL", query_text=text)

def get_ai_service() -> AIServiceInterface:
    # Later can inspect get_settings().GEMINI_API_KEY to instantiate real Gemini service
    return MockAIService()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_ai_service.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/__init__.py app/services/ai_service.py tests/test_ai_service.py
git commit -m "feat(ai): implement pluggable AI extraction service with deterministic mock"
```

---

### Task 5: Document Management & File Storage Service

**Files:**
- Create: `app/services/document_service.py`
- Test: `tests/test_document_service.py`

**Interfaces:**
- Produces: `save_uploaded_file(file_bytes, filename) -> Path`, `delete_file(file_path)`

- [ ] **Step 1: Write failing test for Document Service**

```python
# tests/test_document_service.py
from app.services.document_service import save_uploaded_file, get_safe_filename
from pathlib import Path

def test_save_uploaded_file(tmp_path):
    safe_name = get_safe_filename("bolletta luce.pdf")
    assert safe_name.endswith(".pdf")
    assert " " not in safe_name
    
    saved_path = save_uploaded_file(b"test file content", "bolletta.pdf", target_dir=tmp_path)
    assert Path(saved_path).exists()
    assert Path(saved_path).read_bytes() == b"test file content"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_document_service.py`
Expected: FAIL with ImportError

- [ ] **Step 3: Implement app/services/document_service.py**

```python
# app/services/document_service.py
import uuid
from pathlib import Path
from app.config import get_settings

def get_safe_filename(original_filename: str) -> str:
    suffix = Path(original_filename).suffix.lower() or ".bin"
    return f"{uuid.uuid4().hex}{suffix}"

def save_uploaded_file(file_bytes: bytes, original_filename: str, target_dir: Path = None) -> str:
    folder = target_dir or get_settings().STORAGE_DIR
    folder.mkdir(parents=True, exist_ok=True)
    filename = get_safe_filename(original_filename)
    dest = folder / filename
    dest.write_bytes(file_bytes)
    return str(dest)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_document_service.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/document_service.py tests/test_document_service.py
git commit -m "feat(storage): implement safe UUID file saving and retrieval"
```

---

### Task 6: FastAPI REST API Endpoints & Assembly

**Files:**
- Create: `app/api/__init__.py`
- Create: `app/api/chat.py`
- Create: `app/api/documents.py`
- Create: `app/api/dashboard.py`
- Create: `app/main.py`
- Test: `tests/test_api.py`

**Interfaces:**
- Implements:
  - `POST /api/chat`
  - `POST /api/documents/upload`
  - `GET /api/dashboard`
  - `PATCH /api/documents/{id}/status`
  - `GET /` (serves `index.html`)

- [ ] **Step 1: Write integration tests for API endpoints**

```python
# tests/test_api.py
from fastapi.testclient import TestClient
from app.main import app
from app.models.database import init_db, get_engine
import io

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_api.py`
Expected: FAIL with 404 or ImportError

- [ ] **Step 3: Implement API routers and main.py**

Create `app/api/chat.py`, `app/api/documents.py`, `app/api/dashboard.py` and assemble `app/main.py`. Mount `StaticFiles` for the root path so [`index.html`](file:///c:/Users/Leo/Desktop/DOVE-LO-AI-MESSO/index.html) is served directly on `http://localhost:8000`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_api.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/api/ app/main.py tests/test_api.py
git commit -m "feat(api): implement REST endpoints for chat, upload, and dashboard"
```

---

### Task 7: Connect Frontend index.html to Live Backend API

**Files:**
- Modify: `index.html` (wire JS `handleSend`, `openDashboard`, `simulateAttachment` to real `fetch('/api/...')` endpoints)
- Test: Manual browser check & automated headless/client check.

- [ ] **Step 1: Update index.html JavaScript to call real endpoints**
- [ ] **Step 2: Test sending messages and seeing them persist across refresh**
- [ ] **Step 3: Test uploading files and seeing them appear in the Dashboard table**
- [ ] **Step 4: Commit**

```bash
git add index.html
git commit -m "feat(frontend): connect WhatsApp chat and modern dashboard to real backend API"
```

---
