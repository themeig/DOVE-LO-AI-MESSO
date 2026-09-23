# Persistent Document Memory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform the application into a persistent, multi-layered document memory system where original files are permanently preserved as the source of truth, full OCR text and fine-grained structured entities (e.g., tax code, identity details, birth dates) are stored in SQLite and indexed with semantic vector embeddings, and the AI retrieves facts and re-reads original images/files across new conversations without relying on LLM context memory.

**Architecture:** A multi-tier architecture where uploaded files (images, PDFs, Office) are saved encrypted as the source of truth with unique IDs (`DOC_xxxxx`). During ingestion, full OCR text is preserved in `Document.ocr_full_text`, extracted key-value pairs are stored in a new `DocumentField` table with source/confidence tracking, and content chunks with vector embeddings are indexed in a new `DocumentChunk` table for user-scoped semantic search. A dedicated `DocumentMemoryService` handles retrieval: structured lookup -> full-text/semantic search -> mandatory original document re-inspection fallback via Vision/OCR when a field is missing. The agentic chat engine uses these retrieval tools across all threads and sessions.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, SQLite with transparent AES-256-GCM encryption, Pydantic v2, OpenRouter / Google Gemini Vision & Multimodal, `text-embedding-3-small` embeddings with fast cosine similarity (NumPy), PyPDF, OpenPyXL, Python-docx.

**Spec:** User specification in prompt ("OBIETTIVO PRINCIPALE: Correggere l'architettura di gestione dei documenti e della memoria dell'app").

## Global Constraints

- Scope: All queries, chunks, fields, and document lookups must strictly be filtered by `user_id` (default `"default_user"` for single-vault, supporting multi-tenant isolation).
- Source of truth: The original file (PDF, JPG, PNG, DOCX, etc.) is NEVER deleted or replaced by AI summaries.
- Encryption: All sensitive structured fields and OCR full-text chunks must use `EncryptedString` and `EncryptedText` with the vault's AES-256-GCM key.
- Cross-conversation persistence: Memory retrieval must work seamlessly across fresh chat threads and after app restarts without depending on LLM chat history.
- Zero hallucination: If data cannot be found after structured search, semantic search, and original file re-inspection, the system must declare it not found rather than inventing values.
- Version floor: Semantic Versioning increment to `2.2.0` (MINOR release) upon completion.
- All 200 existing automated tests must continue to pass without regression.

## Review Focus

1. **Missing field in initial summary**: When an unprompted field (e.g. "luogo di nascita" or "codice fiscale") was not highlighted in the brief summary, the system must retrieve it from structured fields, OCR text, or via original image re-inspection.
2. **Fresh conversation retrieval**: In a new thread (`thread_id="new_session"`) or after closing and reopening the app, queries about previously uploaded documents must succeed without reading prior chat messages.
3. **Disambiguation between similar entities**: When two documents belong to the same person (e.g. ID card and Health card) or people with similar names ("Francesco Grossi" vs "Francesca Grossi"), the search engine must retrieve the correct document without mixing fields.
4. **Mandatory fallback to original file**: If a document was stored with minimal metadata, asking for a detail visible in the image must trigger `reprocess_document` to read the original decrypted file via Vision/OCR and permanently cache the discovered field.
5. **Non-existent field rejection**: Asking for information that truly does not exist in any uploaded document must return a clean "not found" statement with zero hallucination.

---

### Task 1: Database Models for Persistent Document Memory (`DocumentField` & `DocumentChunk`)

**Files:**
- Modify: `app/models/database.py`
- Test: `tests/test_document_memory_models.py`

**Interfaces:**
- Consumes: SQLAlchemy `Base`, `EncryptedString`, `EncryptedText`, `init_db`.
- Produces:
  - `Document` extended with `doc_uid` (String, indexed, unique), `user_id` (String, default "default_user", indexed), `ocr_full_text` (`EncryptedText`), `structured_data_json` (`EncryptedText`), `processing_status` (String, default "completed").
  - `DocumentField` model: `id`, `document_id`, `user_id`, `field_name`, `field_value`, `normalized_value`, `source`, `confidence`, `page`, `created_at`.
  - `DocumentChunk` model: `id`, `document_id`, `user_id`, `chunk_index`, `content`, `page_number`, `embedding_json`, `created_at`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_document_memory_models.py
import json
from sqlalchemy.orm import Session
from app.models.database import get_engine, init_db, Document, DocumentField, DocumentChunk

def test_document_memory_models_and_migration():
    engine = get_engine("sqlite:///:memory:")
    init_db(engine)
    with Session(engine) as session:
        # 1. Test Document with new memory columns
        doc = Document(
            doc_uid="DOC_1001",
            user_id="user_alpha",
            title="Carta d'identità Francesco Grossi",
            file_path="uploads/ci_grossi.jpg",
            file_type="jpg",
            doc_type="carta_identita",
            summary="Carta d'identità di Francesco Grossi",
            ocr_full_text="REPUBBLICA ITALIANA CARTA DI IDENTITA N CA00000AA COGNOME GROSSI NOME FRANCESCO CODICE FISCALE GRSFNC90A01H501Z",
            structured_data_json=json.dumps({
                "person": {"first_name": "Francesco", "last_name": "Grossi", "full_name": "Francesco Grossi"},
                "fields": {"tax_code": "GRSFNC90A01H501Z", "document_number": "CA00000AA"}
            }),
            processing_status="completed"
        )
        session.add(doc)
        session.flush()

        # 2. Test DocumentField
        field = DocumentField(
            document_id=doc.id,
            user_id="user_alpha",
            field_name="tax_code",
            field_value="GRSFNC90A01H501Z",
            normalized_value="grsfnc90a01h501z",
            source="ocr_vision",
            confidence=0.99,
            page=1
        )
        session.add(field)

        # 3. Test DocumentChunk
        chunk = DocumentChunk(
            document_id=doc.id,
            user_id="user_alpha",
            chunk_index=0,
            content="REPUBBLICA ITALIANA CARTA DI IDENTITA N CA00000AA COGNOME GROSSI NOME FRANCESCO",
            page_number=1,
            embedding_json=json.dumps([0.012, -0.045, 0.089])
        )
        session.add(chunk)
        session.commit()

        # Verify queries and relationships
        saved_doc = session.query(Document).filter(Document.doc_uid == "DOC_1001").first()
        assert saved_doc is not None
        assert saved_doc.user_id == "user_alpha"
        assert "GRSFNC90A01H501Z" in saved_doc.ocr_full_text
        assert saved_doc.processing_status == "completed"

        saved_field = session.query(DocumentField).filter(
            DocumentField.document_id == saved_doc.id,
            DocumentField.field_name == "tax_code"
        ).first()
        assert saved_field is not None
        assert saved_field.field_value == "GRSFNC90A01H501Z"
        assert saved_field.confidence == 0.99

        saved_chunk = session.query(DocumentChunk).filter(DocumentChunk.document_id == saved_doc.id).first()
        assert saved_chunk is not None
        assert "FRANCESCO" in saved_chunk.content
        assert len(json.loads(saved_chunk.embedding_json)) == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_document_memory_models.py -q`
Expected: FAIL with `ImportError: cannot import name 'DocumentField'` or `Document has no attribute 'doc_uid'`.

- [ ] **Step 3: Implement database models and migrations**

In `app/models/database.py`:
1. In `Document`:
   ```python
   doc_uid = Column(String(50), nullable=True, unique=True, index=True)
   user_id = Column(String(100), nullable=False, default="default_user", index=True)
   ocr_full_text = Column(EncryptedText, nullable=True)
   structured_data_json = Column(EncryptedText, nullable=True)
   processing_status = Column(String(50), nullable=False, default="completed", index=True)
   ```
2. Create `DocumentField`:
   ```python
   class DocumentField(Base):
       __tablename__ = "document_fields"
       id = Column(Integer, primary_key=True, autoincrement=True)
       document_id = Column(Integer, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
       user_id = Column(String(100), nullable=False, default="default_user", index=True)
       field_name = Column(String(100), nullable=False, index=True)
       field_value = Column(EncryptedString(500), nullable=False)
       normalized_value = Column(String(255), nullable=True, index=True)
       source = Column(String(50), nullable=False, default="ocr_vision")
       confidence = Column(Float, nullable=False, default=1.0)
       page = Column(Integer, nullable=True)
       created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
   ```
3. Create `DocumentChunk`:
   ```python
   class DocumentChunk(Base):
       __tablename__ = "document_chunks"
       id = Column(Integer, primary_key=True, autoincrement=True)
       document_id = Column(Integer, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
       user_id = Column(String(100), nullable=False, default="default_user", index=True)
       chunk_index = Column(Integer, nullable=False, default=0)
       content = Column(EncryptedText, nullable=False)
       page_number = Column(Integer, nullable=True)
       embedding_json = Column(Text, nullable=True)
       created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
   ```
4. Update `init_db(engine)` with migration checks (`PRAGMA table_info`) so existing databases automatically receive the new columns `doc_uid`, `user_id`, `ocr_full_text`, `structured_data_json`, and `processing_status`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_document_memory_models.py -q`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add app/models/database.py tests/test_document_memory_models.py
git commit -m "feat(database): add DocumentField and DocumentChunk models with memory columns"
```

---

### Task 2: Pydantic Schemas for Structured Entity & Document Extraction

**Files:**
- Modify: `app/models/schemas.py`
- Test: `tests/test_document_memory_schemas.py`

**Interfaces:**
- Produces: `PersonInfo`, `ExtractedDocumentField`, `ExtractedDocumentMemory`, enhanced `ExtractedDocument`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_document_memory_schemas.py
from app.models.schemas import PersonInfo, ExtractedDocumentField, ExtractedDocument

def test_document_memory_schemas():
    person = PersonInfo(first_name="Francesco", last_name="Grossi", full_name="Francesco Grossi")
    assert person.first_name == "Francesco"
    assert person.full_name == "Francesco Grossi"

    field = ExtractedDocumentField(field_name="tax_code", field_value="GRSFNC90A01H501Z", confidence=0.98, page=1)
    assert field.field_name == "tax_code"
    assert field.confidence == 0.98

    doc = ExtractedDocument(
        title="Carta d'identità Francesco Grossi",
        doc_type="carta_identita",
        issuer="Ministero dell'Interno",
        summary="Carta d'identità elettronica",
        ocr_full_text="Testo completo OCR estratto dal documento",
        person=person,
        fields={"tax_code": "GRSFNC90A01H501Z", "document_number": "CA00000AA", "birth_place": "Milano"}
    )
    assert doc.person.last_name == "Grossi"
    assert doc.fields["tax_code"] == "GRSFNC90A01H501Z"
    assert doc.ocr_full_text == "Testo completo OCR estratto dal documento"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_document_memory_schemas.py -q`
Expected: FAIL with `ImportError: cannot import name 'PersonInfo'`.

- [ ] **Step 3: Implement schemas**

In `app/models/schemas.py`:
1. Define `PersonInfo`:
   ```python
   class PersonInfo(BaseModel):
       first_name: Optional[str] = None
       last_name: Optional[str] = None
       full_name: Optional[str] = None
   ```
2. Define `ExtractedDocumentField`:
   ```python
   class ExtractedDocumentField(BaseModel):
       field_name: str
       field_value: str
       source: str = "ocr_vision"
       confidence: float = 1.0
       page: Optional[int] = None
   ```
3. Update `ExtractedDocument`:
   ```python
   class ExtractedDocument(BaseModel):
       # Existing fields...
       title: Optional[str] = Field(default=None, description="Titolo sintetico descrittivo")
       doc_type: str = Field(default="generico", description="Tipo documento")
       issuer: Optional[str] = Field(default=None, description="Ente, azienda o fornitore")
       amount: Optional[float] = Field(default=None, description="Importo in euro")
       due_date: Optional[str] = Field(default=None, description="Data scadenza YYYY-MM-DD")
       summary: str = Field(default="", description="Spiegazione semplice del documento")
       tags: List[str] = Field(default_factory=list)
       suggest_rename: bool = Field(default=False)
       category: Optional[str] = Field(default=None)
       category_label: Optional[str] = Field(default=None)
       category_icon: Optional[str] = Field(default=None)
       subfolder: Optional[str] = Field(default=None)
       # NEW PERSISTENT MEMORY FIELDS:
       ocr_full_text: Optional[str] = Field(default="", description="Testo completo OCR estratto dal documento")
       person: Optional[PersonInfo] = Field(default=None, description="Informazioni persona/intestatario")
       fields: Dict[str, Any] = Field(default_factory=dict, description="Campi strutturati chiave-valore estratti")
       confidence: float = Field(default=1.0, description="Punteggio di confidenza dell'estrazione")
   ```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_document_memory_schemas.py -q`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add app/models/schemas.py tests/test_document_memory_schemas.py
git commit -m "feat(schemas): add PersonInfo and structured fields to ExtractedDocument"
```

---

### Task 3: Embedding & Semantic Vector Search Engine

**Files:**
- Create: `app/services/embedding_service.py`
- Test: `tests/test_embedding_service.py`

**Interfaces:**
- Produces:
  - `chunk_text(text: str, max_chunk_words: int = 300, overlap_words: int = 50) -> List[Dict[str, Any]]`
  - `generate_embedding(text: str, api_key: Optional[str] = None) -> List[float]`
  - `cosine_similarity(vec1: List[float], vec2: List[float]) -> float`
  - `semantic_search_chunks(query_embedding: List[float], chunk_candidates: List[Dict[str, Any]], top_k: int = 5, min_score: float = 0.35) -> List[Dict[str, Any]]`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_embedding_service.py
from app.services.embedding_service import (
    chunk_text,
    generate_embedding,
    cosine_similarity,
    semantic_search_chunks
)

def test_chunk_text():
    words = ["parola"] * 500
    text = " ".join(words)
    chunks = chunk_text(text, max_chunk_words=200, overlap_words=40)
    assert len(chunks) >= 3
    assert all("text" in c and "index" in c for c in chunks)

def test_cosine_similarity():
    v1 = [1.0, 0.0, 0.0]
    v2 = [1.0, 0.0, 0.0]
    v3 = [0.0, 1.0, 0.0]
    assert abs(cosine_similarity(v1, v2) - 1.0) < 1e-5
    assert abs(cosine_similarity(v1, v3) - 0.0) < 1e-5

def test_deterministic_embedding_offline():
    emb1 = generate_embedding("Codice fiscale Francesco Grossi", api_key="")
    emb2 = generate_embedding("Codice fiscale Francesco Grossi", api_key="")
    emb3 = generate_embedding("Bolletta energia elettrica Enel", api_key="")
    assert len(emb1) == 256
    assert abs(cosine_similarity(emb1, emb2) - 1.0) < 1e-5
    # Similarity between related vs unrelated
    assert cosine_similarity(emb1, emb3) < cosine_similarity(emb1, emb2)

def test_semantic_search_ranking():
    q_emb = generate_embedding("codice fiscale", api_key="")
    candidates = [
        {"id": 1, "text": "Ricevuta ristorante pizza margherita", "embedding": generate_embedding("Ricevuta ristorante pizza margherita", api_key="")},
        {"id": 2, "text": "Codice fiscale intestatario: GRSFNC90A01H501Z", "embedding": generate_embedding("Codice fiscale intestatario: GRSFNC90A01H501Z", api_key="")},
    ]
    ranked = semantic_search_chunks(q_emb, candidates, top_k=1)
    assert len(ranked) == 1
    assert ranked[0]["id"] == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_embedding_service.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.embedding_service'`.

- [ ] **Step 3: Implement embedding_service.py**

Create `app/services/embedding_service.py`:
- Use OpenRouter `text-embedding-3-small` when `OPENROUTER_API_KEY` is present.
- Provide a high-precision deterministic normalized n-gram bag-of-words / hash embedding vector (dim=256) when offline or in test environments so unit tests and offline vaults work instantly without external network calls.
- Fast `cosine_similarity` using `numpy.dot` and vector norms.
- `chunk_text` with word boundary alignment and overlap.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_embedding_service.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add app/services/embedding_service.py tests/test_embedding_service.py
git commit -m "feat(embeddings): implement chunking, embeddings, and vector cosine search"
```

---

### Task 4: AI Extraction Pipeline with Full OCR and Structured Entities

**Files:**
- Modify: `app/services/ai_service.py`
- Test: `tests/test_ai_extraction_memory.py`

**Interfaces:**
- Enhances: `extract_document(file_bytes, mime_type, filename) -> ExtractedDocument`
- Produces: `ExtractedDocument` populated with:
  - `ocr_full_text`: complete raw text extracted from PDF, Office or Image OCR.
  - `person`: `PersonInfo` (first_name, last_name, full_name) for identity cards, tax cards, driving licenses, certificates, contracts.
  - `fields`: dictionary with all key-value pairs (tax_code, document_number, birth_date, birth_place, expiration_date, etc.).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ai_extraction_memory.py
from app.services.ai_service import MockAIService

def test_mock_ai_extract_identity_card_memory():
    ai = MockAIService()
    fake_img = b"fake-jpg-content"
    doc = ai.extract_document(fake_img, "image/jpeg", filename="carta_identita_francesco_grossi.jpg")

    assert doc.doc_type in ["carta_identita", "documento_identita", "patente"]
    assert doc.person is not None
    assert doc.person.first_name == "Francesco"
    assert doc.person.last_name == "Grossi"
    assert "tax_code" in doc.fields
    assert doc.fields["tax_code"] == "GRSFNC90A01H501Z"
    assert doc.fields["document_number"] == "CA00000AA"
    assert "REPUBBLICA ITALIANA" in doc.ocr_full_text
    assert "GRSFNC90A01H501Z" in doc.ocr_full_text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ai_extraction_memory.py -q`
Expected: FAIL with `AssertionError: assert None is not None` on `doc.person`.

- [ ] **Step 3: Update `ai_service.py`**

1. In `MockAIService._raw_extract_document`:
   - Detect identity documents, passports, health cards (e.g. filename contains `carta_identita`, `ci_`, `patente`, `passaporto`, `cf_`, `tessera_sanitaria`).
   - Populate `doc.person = PersonInfo(...)`.
   - Populate `doc.fields = {"tax_code": ..., "document_number": ..., "birth_date": ..., "birth_place": ..., "expiration_date": ...}`.
   - Populate `doc.ocr_full_text = "..."`.
2. In `OpenRouterAIService.extract_document`:
   - For Images: Update vision prompt to explicitly request:
     `ocr_full_text`: complete transcription of all visible words on the document.
     `person`: `{"first_name": "...", "last_name": "...", "full_name": "..."}` if applicable.
     `fields`: dictionary containing all specific codes, numbers, dates, places, amounts, tax codes (`tax_code`), IBAN, document numbers.
   - For PDFs and Office files: Assign extracted text to `doc.ocr_full_text` and prompt LLM to extract structured `person` and `fields`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_ai_extraction_memory.py -q`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add app/services/ai_service.py tests/test_ai_extraction_memory.py
git commit -m "feat(ai): enhance extract_document to extract OCR full text and structured fields"
```

---

### Task 5: Document Memory Service (Ingestion, Multi-Level Storage & Search)

**Files:**
- Create: `app/services/document_memory_service.py`
- Test: `tests/test_document_memory_service.py`

**Interfaces:**
- Produces:
  - `ingest_document_memory(doc: Document, extracted: ExtractedDocument, db: Session, user_id: str = "default_user") -> None`
  - `search_documents(query: str, db: Session, user_id: str = "default_user", limit: int = 10) -> List[Dict[str, Any]]`
  - `get_document(doc_id_or_uid: Any, db: Session, user_id: str = "default_user") -> Optional[Document]`
  - `get_document_fields(document_id: int, db: Session, user_id: str = "default_user") -> List[Dict[str, Any]]`
  - `search_document_content(query: str, db: Session, user_id: str = "default_user", top_k: int = 5) -> List[Dict[str, Any]]`
  - `search_person_documents(person_name: str, db: Session, user_id: str = "default_user") -> List[Dict[str, Any]]`
  - `search_expiring_documents(db: Session, date_range_days: int = 60, user_id: str = "default_user") -> List[Dict[str, Any]]`
  - `get_original_document(document_id: int, db: Session, user_id: str = "default_user") -> Dict[str, Any]`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_document_memory_service.py
from datetime import date
from sqlalchemy.orm import Session
from app.models.database import get_engine, init_db, Document
from app.models.schemas import ExtractedDocument, PersonInfo
from app.services.document_memory_service import (
    ingest_document_memory,
    search_documents,
    get_document_fields,
    search_document_content,
    search_person_documents,
    search_expiring_documents
)

def test_ingest_and_retrieve_document_memory():
    engine = get_engine("sqlite:///:memory:")
    init_db(engine)
    with Session(engine) as session:
        doc = Document(
            doc_uid="DOC_0001",
            user_id="user_1",
            title="Carta d'identità Francesco Grossi",
            file_path="uploads/ci.jpg",
            file_type="jpg",
            doc_type="carta_identita",
            summary="Carta d'identità di Francesco Grossi",
            due_date=date(2030, 5, 20)
        )
        session.add(doc)
        session.flush()

        extracted = ExtractedDocument(
            title=doc.title,
            doc_type=doc.doc_type,
            summary=doc.summary,
            ocr_full_text="REPUBBLICA ITALIANA CARTA DI IDENTITA N CA00000AA COGNOME GROSSI NOME FRANCESCO CODICE FISCALE GRSFNC90A01H501Z NATO A MILANO IL 01/01/1990",
            person=PersonInfo(first_name="Francesco", last_name="Grossi", full_name="Francesco Grossi"),
            fields={
                "tax_code": "GRSFNC90A01H501Z",
                "document_number": "CA00000AA",
                "birth_place": "Milano",
                "birth_date": "1990-01-01",
                "expiration_date": "2030-05-20"
            }
        )

        ingest_document_memory(doc, extracted, session, user_id="user_1")
        session.commit()

        # 1. Search document fields
        fields = get_document_fields(doc.id, session, user_id="user_1")
        field_map = {f["field_name"]: f["field_value"] for f in fields}
        assert field_map["tax_code"] == "GRSFNC90A01H501Z"
        assert field_map["birth_place"] == "Milano"

        # 2. Search person documents
        person_docs = search_person_documents("Francesco Grossi", session, user_id="user_1")
        assert len(person_docs) == 1
        assert person_docs[0]["id"] == doc.id

        # 3. Search document content (semantic / full-text)
        content_results = search_document_content("codice fiscale GRSFNC90A01H501Z", session, user_id="user_1")
        assert len(content_results) > 0
        assert content_results[0]["document_id"] == doc.id

        # 4. User scoping: user_2 must see nothing
        assert len(search_person_documents("Francesco Grossi", session, user_id="user_2")) == 0
        assert len(search_document_content("GRSFNC90A01H501Z", session, user_id="user_2")) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_document_memory_service.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.document_memory_service'`.

- [ ] **Step 3: Implement document_memory_service.py**

Create `app/services/document_memory_service.py`:
- `ingest_document_memory`:
  - Generates `doc.doc_uid = f"DOC_{doc.id:05d}"` if not already set.
  - Updates `doc.ocr_full_text = extracted.ocr_full_text`.
  - Updates `doc.structured_data_json = json.dumps({"person": extracted.person.model_dump() if extracted.person else None, "fields": extracted.fields})`.
  - Deletes any pre-existing `DocumentField` and `DocumentChunk` for this document.
  - Inserts a `DocumentField` for every key in `extracted.fields` and for person details (`first_name`, `last_name`, `full_name`).
  - Calls `chunk_text(extracted.ocr_full_text)`, generates embeddings with `generate_embedding`, and inserts `DocumentChunk` records.
- Implement `search_documents`, `get_document`, `get_document_fields`, `search_document_content`, `search_person_documents`, `search_expiring_documents`, `get_original_document`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_document_memory_service.py -q`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add app/services/document_memory_service.py tests/test_document_memory_service.py
git commit -m "feat(memory): implement ingest_document_memory, structured lookup, and vector retrieval"
```

---

### Task 6: Mandatory Fallback - Targeted Document Re-inspection via Vision/OCR

**Files:**
- Modify: `app/services/document_memory_service.py`
- Test: `tests/test_document_reprocess_fallback.py`

**Interfaces:**
- Produces: `reprocess_document(document_id: int, target_query: str, db: Session, user_id: str = "default_user") -> Dict[str, Any]`
- When an information item is NOT found in `DocumentField` or `DocumentChunk`, decrypts the original source file on disk, runs a targeted Vision/OCR analysis focused on `target_query`, saves any newly discovered field into `DocumentField`, and returns the extracted result.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_document_reprocess_fallback.py
from sqlalchemy.orm import Session
from app.models.database import get_engine, init_db, Document, DocumentField
from app.services.document_memory_service import reprocess_document, get_document_fields

def test_reprocess_document_targeted_fallback(monkeypatch, tmp_path):
    engine = get_engine("sqlite:///:memory:")
    init_db(engine)
    with Session(engine) as session:
        # Create a document that initially has NO tax code in fields
        fake_file = tmp_path / "ci_sample.jpg"
        fake_file.write_bytes(b"fake-image-bytes")

        doc = Document(
            doc_uid="DOC_00099",
            user_id="default_user",
            title="Carta d'identità Francesco Grossi",
            file_path=str(fake_file),
            file_type="jpg",
            doc_type="carta_identita",
            summary="Documento registrato senza dettagli fiscali",
            ocr_full_text="Testo generico"
        )
        session.add(doc)
        session.commit()

        # Mock targeted vision inspection to simulate reading the original file image
        def mock_inspect_target(file_bytes, file_type, query):
            if "codice fiscale" in query.lower() or "tax_code" in query.lower():
                return {"found": True, "field_name": "tax_code", "value": "GRSFNC90A01H501Z", "confidence": 0.96}
            return {"found": False, "field_name": None, "value": None, "confidence": 0.0}

        monkeypatch.setattr("app.services.document_memory_service._call_vision_targeted_inspection", mock_inspect_target)

        # 1. Reprocess targeted query
        res = reprocess_document(doc.id, target_query="codice fiscale", db=session, user_id="default_user")
        assert res["found"] is True
        assert res["value"] == "GRSFNC90A01H501Z"
        assert res["confidence"] == 0.96

        # 2. Check that the newly discovered field was permanently cached in DocumentField
        fields = get_document_fields(doc.id, session, user_id="default_user")
        field_names = [f["field_name"] for f in fields]
        assert "tax_code" in field_names

        # 3. Querying something non-existent must return found=False without hallucination
        res_none = reprocess_document(doc.id, target_query="targa del veicolo", db=session, user_id="default_user")
        assert res_none["found"] is False
        assert res_none["value"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_document_reprocess_fallback.py -q`
Expected: FAIL with `ImportError: cannot import name 'reprocess_document'`.

- [ ] **Step 3: Implement reprocess_document in `document_memory_service.py`**

In `app/services/document_memory_service.py`:
1. Implement `_call_vision_targeted_inspection(file_bytes, file_type, query)`:
   - If image: converts to base64, calls OpenRouter / Gemini with targeted inspection prompt:
     `"Analizza questa immagine originale del documento per trovare specificamente: '{query}'. Estrai il valore esatto. Rispondi in JSON: {{\"found\": bool, \"field_name\": str, \"value\": str, \"confidence\": float}}."`
   - If PDF: extracts pages, searches with targeted regex or LLM prompt.
2. Implement `reprocess_document(document_id, target_query, db, user_id)`:
   - Verifies document ownership (`user_id`).
   - Decrypts original file on disk via `read_decrypted_file`.
   - Executes `_call_vision_targeted_inspection`.
   - If `res["found"]`: saves a new `DocumentField` record (or updates existing) so future lookups are instantaneous.
   - Returns the result dictionary.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_document_reprocess_fallback.py -q`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add app/services/document_memory_service.py tests/test_document_reprocess_fallback.py
git commit -m "feat(memory): add reprocess_document targeted fallback on original files"
```

---

### Task 7: Wire Ingestion into Document Upload Pipelines

**Files:**
- Modify: `app/api/documents.py`
- Modify: `app/services/folder_service.py`
- Modify: `app/services/archive_service.py`
- Test: `tests/test_upload_with_memory.py`

**Interfaces:**
- Connects: Every document creation path (`_process_and_save_single_doc`, local folder scanner, zip archive extraction) calls `ingest_document_memory(doc, extracted, db)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_upload_with_memory.py
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from app.main import app
from app.models.database import get_db, Document, DocumentField, DocumentChunk

client = TestClient(app)

def test_upload_document_automatically_populates_memory():
    # Upload simulated identity card
    files = {"file": ("carta_identita_francesco_grossi.jpg", b"fake-jpg-content", "image/jpeg")}
    data = {"thread_id": "thread_upload_test"}
    resp = client.post("/api/documents/upload", files=files, data=data)
    assert resp.status_code == 201

    # Check database
    db_gen = app.dependency_overrides.get(get_db, get_db)()
    db: Session = next(db_gen)
    try:
        doc = db.query(Document).filter(Document.title.ilike("%Francesco Grossi%")).first()
        assert doc is not None
        assert doc.doc_uid is not None and doc.doc_uid.startswith("DOC_")
        assert doc.ocr_full_text is not None and len(doc.ocr_full_text) > 0

        # Check structured fields
        fields = db.query(DocumentField).filter(DocumentField.document_id == doc.id).all()
        assert len(fields) > 0
        field_keys = [f.field_name for f in fields]
        assert "tax_code" in field_keys

        # Check chunks
        chunks = db.query(DocumentChunk).filter(DocumentChunk.document_id == doc.id).all()
        assert len(chunks) > 0
    finally:
        db.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_upload_with_memory.py -q`
Expected: FAIL because `ingest_document_memory` is not called in `upload_document`.

- [ ] **Step 3: Update upload handlers**

1. In `app/api/documents.py`:
   - In `_process_and_save_single_doc`: After creating `Document`, set `doc.doc_uid = f"DOC_{doc.id:05d}"`, and call `ingest_document_memory(doc, extracted, db, user_id=doc.user_id)`.
2. In `app/services/folder_service.py`:
   - In `_index_single_file`: After creating `Document`, call `ingest_document_memory`.
3. In `app/services/archive_service.py`:
   - In `_handle_unzip_vault_document`: Call `ingest_document_memory` for each extracted file document.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_upload_with_memory.py -q`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add app/api/documents.py app/services/folder_service.py app/services/archive_service.py tests/test_upload_with_memory.py
git commit -m "feat(upload): wire ingest_document_memory into document upload and extraction pipelines"
```

---

### Task 8: Agentic Tools & Query Routing Integration

**Files:**
- Modify: `app/services/agent_service.py`
- Modify: `app/mcp_server.py`
- Test: `tests/test_agent_document_memory.py`

**Interfaces:**
- Produces MCP & Agent tools:
  - `search_document_memory`: Multi-stage retrieval tool (Structured fields -> Semantic/OCR search -> Targeted original file reprocess fallback).
  - `get_document_fields`: Returns all structured key-values of a document.
  - `search_person_documents`: Finds all documents belonging to a person.
- Updates: `_run_turn_impl` and `_fallback_deterministic_response` to route queries for personal details (tax code, birth date, document numbers) directly into `search_document_memory`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_agent_document_memory.py
from datetime import date
from sqlalchemy.orm import Session
from app.models.database import get_engine, init_db, Document
from app.models.schemas import ExtractedDocument, PersonInfo
from app.services.document_memory_service import ingest_document_memory
from app.services.agent_service import AgenticChatService

def test_agent_resolves_tax_code_across_threads():
    engine = get_engine("sqlite:///:memory:")
    init_db(engine)
    with Session(engine) as session:
        # User uploaded ID card in thread "upload_session"
        doc = Document(
            doc_uid="DOC_0001",
            user_id="default_user",
            thread_id="upload_session",
            title="Carta d'identità Francesco Grossi",
            file_path="uploads/ci.jpg",
            file_type="jpg",
            doc_type="carta_identita",
            summary="Carta d'identità di Francesco Grossi",
            due_date=date(2030, 1, 1)
        )
        session.add(doc)
        session.flush()

        extracted = ExtractedDocument(
            title=doc.title,
            doc_type=doc.doc_type,
            summary=doc.summary,
            ocr_full_text="REPUBBLICA ITALIANA CARTA DI IDENTITA N CA00000AA COGNOME GROSSI NOME FRANCESCO CODICE FISCALE GRSFNC90A01H501Z",
            person=PersonInfo(first_name="Francesco", last_name="Grossi", full_name="Francesco Grossi"),
            fields={"tax_code": "GRSFNC90A01H501Z", "document_number": "CA00000AA"}
        )
        ingest_document_memory(doc, extracted, session, user_id="default_user")
        session.commit()

        agent = AgenticChatService()
        agent.settings.OPENROUTER_API_KEY = "" # offline mode testing

        # User opens a NEW conversation thread "thread_fresh_query" and asks for tax code
        resp = agent.run_turn(
            "Qual è il codice fiscale di Francesco Grossi?",
            db=session,
            thread_id="thread_fresh_query"
        )

        assert "GRSFNC90A01H501Z" in resp.reply
        assert "Francesco Grossi" in resp.reply or "Carta d'identità" in resp.reply
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_agent_document_memory.py -q`
Expected: FAIL because `agent` does not know how to retrieve `tax_code` without the LLM context.

- [ ] **Step 3: Integrate tools and routing into agent_service.py**

1. In `TOOLS_DEFINITION`: Add schemas for `search_document_memory`, `get_document_fields`, `search_person_documents`.
2. In `execute_tool`:
   - Handle `search_document_memory`:
     - Checks `DocumentField` for requested entity (e.g. `tax_code`, `document_number`, etc.).
     - Checks `DocumentChunk` and `ocr_full_text`.
     - If not found: calls `reprocess_document` fallback.
     - Returns `{found: True, value: ..., document_id: ..., title: ..., confidence: ...}`.
   - Handle `get_document_fields` and `search_person_documents`.
3. In `_run_turn_impl` and `_fallback_deterministic_response`:
   - Detect intents requesting specific document fields (codice fiscale, numero documento, data di nascita, scadenza, etc.) or person queries.
   - Execute `search_document_memory` or `search_person_documents`.
   - If found: return formatted executive response citing source document.
   - If not found: state clearly that the requested field was not found in the documents.
4. In `app/mcp_server.py`: Expose the new tools to external MCP clients.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_agent_document_memory.py -q`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add app/services/agent_service.py app/mcp_server.py tests/test_agent_document_memory.py
git commit -m "feat(agent): integrate persistent document memory tools into agentic loop and MCP server"
```

---

### Task 9: The 10 Mandatory Verification Scenarios (End-to-End Test Suite)

**Files:**
- Create: `tests/test_document_memory_e2e.py`

**Interfaces:**
- Tests all 10 scenarios required by Section 14 of the specification:
  - `test_scenario_1_upload_and_extract_tax_code`
  - `test_scenario_2_new_conversation_retrieval`
  - `test_scenario_3_unprompted_field_recovery`
  - `test_scenario_4_app_restart_persistence`
  - `test_scenario_5_multi_document_scale` (10+ documents)
  - `test_scenario_6_non_existent_data_declaration`
  - `test_scenario_7_open_original_document`
  - `test_scenario_8_two_documents_same_person`
  - `test_scenario_9_two_similar_names_disambiguation`
  - `test_scenario_10_missing_metadata_vision_reprocess_fallback`

- [ ] **Step 1: Write the comprehensive test suite**

```python
# tests/test_document_memory_e2e.py
import pytest
from datetime import date
from sqlalchemy.orm import Session
from app.models.database import get_engine, init_db, Document
from app.models.schemas import ExtractedDocument, PersonInfo
from app.services.document_memory_service import (
    ingest_document_memory,
    get_original_document,
    reprocess_document,
    get_document_fields
)
from app.services.agent_service import AgenticChatService

@pytest.fixture
def memory_db(tmp_path):
    db_file = tmp_path / "vault_e2e.db"
    engine = get_engine(f"sqlite:///{db_file}")
    init_db(engine)
    return engine, tmp_path

def test_all_10_memory_scenarios(memory_db, monkeypatch):
    engine, tmp_path = memory_db
    with Session(engine) as session:
        # Create physical test file
        ci_file = tmp_path / "ci_francesco.jpg"
        ci_file.write_bytes(b"image-data-ci-francesco")

        # TEST 1 & 2: Upload Carta d'identità in Thread 1 -> query tax code in Thread 2 (new conversation)
        doc1 = Document(
            doc_uid="DOC_00001",
            user_id="default_user",
            thread_id="conversation_1",
            title="Carta d'identità Francesco Grossi",
            file_path=str(ci_file),
            file_type="jpg",
            doc_type="carta_identita",
            summary="Carta d'identità di Francesco Grossi emessa dal Comune",
            due_date=date(2030, 8, 15)
        )
        session.add(doc1)
        session.flush()

        extracted1 = ExtractedDocument(
            title=doc1.title,
            doc_type=doc1.doc_type,
            summary=doc1.summary,
            ocr_full_text="REPUBBLICA ITALIANA CARTA DI IDENTITA N CA12345AA COGNOME GROSSI NOME FRANCESCO CODICE FISCALE GRSFNC90A01H501Z NATO A MILANO IL 01/01/1990",
            person=PersonInfo(first_name="Francesco", last_name="Grossi", full_name="Francesco Grossi"),
            fields={
                "tax_code": "GRSFNC90A01H501Z",
                "document_number": "CA12345AA",
                "birth_place": "Milano",
                "birth_date": "1990-01-01",
                "expiration_date": "2030-08-15"
            }
        )
        ingest_document_memory(doc1, extracted1, session, user_id="default_user")
        session.commit()

        agent = AgenticChatService()
        agent.settings.OPENROUTER_API_KEY = ""

        # Query in new conversation thread
        resp2 = agent.run_turn("Qual è il codice fiscale di Francesco Grossi?", db=session, thread_id="conversation_2")
        assert "GRSFNC90A01H501Z" in resp2.reply

        # TEST 3: Query an unprompted field (e.g. luogo di nascita)
        resp3 = agent.run_turn("Dove è nato Francesco Grossi?", db=session, thread_id="conversation_3")
        assert "Milano" in resp3.reply

        # TEST 4: App restart / Fresh session -> data still available
        with Session(engine) as fresh_session:
            resp4 = agent.run_turn("Dimmi il numero del documento di Francesco Grossi", db=fresh_session, thread_id="conversation_4")
            assert "CA12345AA" in resp4.reply

        # TEST 5: Upload 10+ documents and retrieve specific document
        for i in range(10):
            d_i = Document(
                doc_uid=f"DOC_{100+i}",
                user_id="default_user",
                title=f"Bolletta Utenza {i}",
                file_path=str(tmp_path / f"bolletta_{i}.pdf"),
                file_type="pdf",
                doc_type="bolletta",
                summary=f"Bolletta generica {i}"
            )
            session.add(d_i)
        session.commit()

        resp5 = agent.run_turn("Qual è il codice fiscale di Francesco Grossi?", db=session, thread_id="conversation_5")
        assert "GRSFNC90A01H501Z" in resp5.reply

        # TEST 6: Query information that does not exist -> declare not found without hallucinating
        resp6 = agent.run_turn("Qual è il codice IBAN di Francesco Grossi?", db=session, thread_id="conversation_6")
        assert "non ho trovato" in resp6.reply.lower() or "non è presente" in resp6.reply.lower() or "non risulta" in resp6.reply.lower()

        # TEST 7: Ask to open / get original file
        orig = get_original_document(doc1.id, session, user_id="default_user")
        assert orig["found"] is True
        assert orig["file_path"] == str(ci_file)

        # TEST 8: Two documents for same person (CI + Tessera Sanitaria)
        doc_ts = Document(
            doc_uid="DOC_00002",
            user_id="default_user",
            title="Tessera Sanitaria Francesco Grossi",
            file_path=str(tmp_path / "ts.jpg"),
            file_type="jpg",
            doc_type="tessera_sanitaria",
            summary="Tessera sanitaria nazionale",
            due_date=date(2028, 4, 10)
        )
        session.add(doc_ts)
        session.flush()
        extracted_ts = ExtractedDocument(
            title=doc_ts.title,
            doc_type=doc_ts.doc_type,
            summary=doc_ts.summary,
            ocr_full_text="TESSERA SANITARIA CODICE REGIONALE 030 GROSSI FRANCESCO",
            person=PersonInfo(first_name="Francesco", last_name="Grossi", full_name="Francesco Grossi"),
            fields={"regional_code": "030", "card_type": "TS-CNS"}
        )
        ingest_document_memory(doc_ts, extracted_ts, session, user_id="default_user")
        session.commit()

        resp8 = agent.run_turn("Quali documenti ho per Francesco Grossi?", db=session, thread_id="conversation_8")
        assert "carta d'identità" in resp8.reply.lower() or "identità" in resp8.reply.lower()
        assert "tessera sanitaria" in resp8.reply.lower() or "sanitaria" in resp8.reply.lower()

        # TEST 9: Two people with similar names (Francesco Grossi vs Francesca Grossi)
        doc_francesca = Document(
            doc_uid="DOC_00003",
            user_id="default_user",
            title="Patente Francesca Grossi",
            file_path=str(tmp_path / "patente.jpg"),
            file_type="jpg",
            doc_type="patente",
            summary="Patente di guida Francesca Grossi"
        )
        session.add(doc_francesca)
        session.flush()
        extracted_francesca = ExtractedDocument(
            title=doc_francesca.title,
            doc_type=doc_francesca.doc_type,
            summary=doc_francesca.summary,
            ocr_full_text="PATENTE DI GUIDA GROSSI FRANCESCA CODICE FISCALE GRSFNC95B41H501K",
            person=PersonInfo(first_name="Francesca", last_name="Grossi", full_name="Francesca Grossi"),
            fields={"tax_code": "GRSFNC95B41H501K"}
        )
        ingest_document_memory(doc_francesca, extracted_francesca, session, user_id="default_user")
        session.commit()

        resp9_m = agent.run_turn("Qual è il codice fiscale di Francesco Grossi?", db=session, thread_id="conversation_9a")
        assert "GRSFNC90A01H501Z" in resp9_m.reply
        assert "GRSFNC95B41H501K" not in resp9_m.reply

        resp9_f = agent.run_turn("Qual è il codice fiscale di Francesca Grossi?", db=session, thread_id="conversation_9b")
        assert "GRSFNC95B41H501K" in resp9_f.reply
        assert "GRSFNC90A01H501Z" not in resp9_f.reply

        # TEST 10: Missing metadata in summary -> recovers data from original image re-inspection
        doc_bare = Document(
            doc_uid="DOC_00004",
            user_id="default_user",
            title="Documento sconosciuto",
            file_path=str(ci_file),
            file_type="jpg",
            doc_type="generico",
            summary="File senza metadati"
        )
        session.add(doc_bare)
        session.commit()

        def mock_vision(file_bytes, file_type, query):
            if "altezza" in query.lower():
                return {"found": True, "field_name": "height", "value": "1.82m", "confidence": 0.95}
            return {"found": False, "field_name": None, "value": None, "confidence": 0.0}

        monkeypatch.setattr("app.services.document_memory_service._call_vision_targeted_inspection", mock_vision)

        reprocess_res = reprocess_document(doc_bare.id, target_query="altezza", db=session, user_id="default_user")
        assert reprocess_res["found"] is True
        assert reprocess_res["value"] == "1.82m"
```

- [ ] **Step 2: Run test suite**

Run: `pytest tests/test_document_memory_e2e.py -v`
Expected: PASS (1 passed with all 10 scenarios asserted).

- [ ] **Step 3: Commit**

```bash
git add tests/test_document_memory_e2e.py
git commit -m "test(memory): add comprehensive 10-scenario end-to-end test suite"
```

---

### Task 10: Version Increment to v2.2.0 & AGENTS.md Update

**Files:**
- Modify: `app/version.py`
- Modify: `index.html`
- Modify: `AGENTS.md`

- [ ] **Step 1: Bump version in app/version.py**

Set `__version__ = "2.2.0"` and `APP_VERSION = __version__`.

- [ ] **Step 2: Update badges in index.html**

Replace all occurrences of `v2.1.3` with `v2.2.0` in `index.html`.

- [ ] **Step 3: Update AGENTS.md**

Document the new persistent document memory architecture, models (`DocumentField`, `DocumentChunk`), and retrieval tools.

- [ ] **Step 4: Run full test suite**

Run: `pytest -q`
Expected: 210+ tests pass with 0 errors.

- [ ] **Step 5: Commit & Push**

```bash
git add app/version.py index.html AGENTS.md
git commit -m "feat(version): bump to v2.2.0 with persistent document memory engine"
git push origin main
```
