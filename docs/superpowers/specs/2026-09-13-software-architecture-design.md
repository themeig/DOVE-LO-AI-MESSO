# Specifica Architetturale: "Dove lo AI messo" (Backend & Engine Core)

**Data**: 13 Settembre 2026  
**Autore**: Team di Sviluppo & Antigravity  
**Stato**: Approvato (Pronto per Pianificazione Operativa)

---

## 1. Visione & Obiettivi del Sistema

**"Dove lo AI messo"** è un assistente intelligente personale e professionale per archiviare e ritrovare qualsiasi cosa (documenti burocratici/fiscali, scadenze di pagamento e collocazione fisica di oggetti e beni).

### Obiettivi Chiave:
* **Esperienza Dual-View Coerente**:
  * *Schermata Chat*: look & feel Olivetti Industrial per la massima chiarezza e fruibilità immediata.
  * *Schermata Dashboard*: cruscotto ultra-moderno (stile Registro Industriale) con visualizzazione a schede Bento e tabella adempimenti.
* **Architettura Modulare a Livelli**:
  * Separazione netta tra API REST (FastAPI), logica di estrazione AI, indicizzazione semantica vettoriale e persistenza relazionale.
* **Zero Costi Infrastrutturali Iniziali**:
  * Stack embedded in locale (SQLite + ChromaDB locale) facilmente trasportabile in cloud al momento del lancio commerciale con modello ad abbonamento SaaS.
* **Affidabilità & Determinismo (TDD)**:
  * Utilizzo di schemi Pydantic rigidi (Structured Outputs) per impedire allucinazioni dell'AI.

---

## 2. Architettura di Sistema a Livelli

```
┌────────────────────────────────────────────────────────┐
│             FRONTEND: Single Page Application          │
│  • Chat Screen (Terminale Olivetti: Foto, Vocali, Testo)│
│  • Dashboard Screen (SaaS UI: Bento KPI, Tabella)      │
└───────────────────────────▲────────────────────────────┘
                            │ HTTP / JSON
┌───────────────────────────▼────────────────────────────┐
│               BACKEND: FastAPI Application             │
│                                                        │
│  [API Layer]                                           │
│  • /api/chat                  • /api/documents/upload  │
│  • /api/dashboard             • /api/documents/{id}    │
│                                                        │
│  [Business & AI Layer]                                 │
│  • AIService (Gemini Flash + Mock fallback)            │
│  • DocumentService (File storage & sanitation)         │
│  • VectorService (ChromaDB / Ricerca semantica)        │
│                                                        │
│  [Persistence Layer]                                   │
│  • SQLite Database (vault.db via SQLAlchemy)          │
│  • File Vault Locale (storage/uploads/)                │
└────────────────────────────────────────────────────────┘
```

---

## 3. Schema Dati Relazionale (SQLite / SQLAlchemy)

Il database `vault.db` memorizza le entità applicative:

### 3.1 Tabella `documents`
Memorizza i documenti fiscali, bollette e ricevute caricate tramite foto o PDF.

| Campo | Tipo | Descrizione |
| :--- | :--- | :--- |
| `id` | Integer (PK) | Identificativo univoco auto-incrementante |
| `title` | String(255) | Titolo descrittivo generato (es. *"Bolletta Enel Luce Ottobre 2026"*) |
| `file_path` | String(500) | Percorso locale del file archiviato in `storage/uploads/` |
| `file_type` | String(50) | Estensione / MIME type (`pdf`, `image/jpeg`, `image/png`) |
| `doc_type` | String(50) | Categoria: `bolletta`, `f24`, `atto`, `polizza`, `ricevuta`, `generico` |
| `issuer` | String(255) | Ente emittente o fornitore (es. *"Enel Energia"*, *"Comune di Milano"*) |
| `amount` | Float (Nullable) | Importo da pagare (se presente) |
| `due_date` | Date (Nullable) | Data perentoria di scadenza o pagamento |
| `status` | String(50) | Stato: `da_pagare`, `quietanzato`, `archiviato` (Default: `da_pagare`) |
| `summary` | Text | Spiegazione del documento in italiano semplice e comprensibile |
| `created_at` | DateTime | Timestamp di acquisizione |

### 3.2 Tabella `physical_items`
Memorizza le posizioni fisiche di beni e oggetti ("Dove lo AI messo").

| Campo | Tipo | Descrizione |
| :--- | :--- | :--- |
| `id` | Integer (PK) | Identificativo univoco |
| `item_name` | String(255) | Nome dell'oggetto (es. *"Passaporto"*, *"Seconde chiavi auto"*) |
| `category` | String(100) | Categoria (es. *"veicoli"*, *"documenti_personali"*, *"casa"*) |
| `primary_location` | String(255) | Ambiente / Stanza (es. *"Studio"*, *"Cantina"*, *"Ingresso"*) |
| `detailed_location` | String(255) | Dettaglio mobile/contenitore (es. *"Primo cassetto scrivania"*) |
| `notes` | Text (Nullable) | Eventuali annotazioni aggiuntive |
| `updated_at` | DateTime | Data e ora dell'ultimo aggiornamento della posizione |

### 3.3 Tabella `chat_messages`
Memorizza lo storico delle conversazioni per garantire continuità tra sessioni.

| Campo | Tipo | Descrizione |
| :--- | :--- | :--- |
| `id` | Integer (PK) | Identificativo messaggio |
| `sender` | String(20) | Mittente: `user` o `assistant` |
| `message_type` | String(20) | Tipo: `text`, `voice`, `document` |
| `content` | Text | Testo del messaggio |
| `metadata_json` | Text (Nullable) | JSON con ID documento o oggetto associato |
| `timestamp` | DateTime | Orario del messaggio |

---

## 4. Pipeline AI & Ingestion Engine (`AIService`)

L'elaborazione dell'AI è definita tramite un'interfaccia astratta per supportare **sia le chiamate reali a Gemini Flash, sia un Mock locale** per i test senza dipendenze di rete.

### 4.1 Schema Pydantic per Estrazione Documenti
```python
class ExtractedDocument(BaseModel):
    doc_type: str = Field(description="Tipo: bolletta, f24, atto, polizza, ricevuta")
    issuer: str = Field(description="Ente o fornitore")
    amount: float | None = Field(default=None, description="Importo in euro")
    due_date: str | None = Field(default=None, description="Data di scadenza YYYY-MM-DD")
    summary: str = Field(description="Sintesi in 2 frasi in italiano semplice")
    tags: list[str] = Field(default_factory=list)
```

### 4.2 Schema Pydantic per Intento Conversazionale & Posizioni
```python
class MessageIntent(BaseModel):
    intent: Literal["STORE_LOCATION", "QUERY_LOCATION", "QUERY_DEADLINES", "GENERAL"]
    item_name: str | None = None
    primary_location: str | None = None
    detailed_location: str | None = None
    query_text: str | None = None
```

### 4.3 Comportamento Pluggabile:
* Se `GEMINI_API_KEY` è configurata: usa `GeminiAIService` (modello `gemini-2.5-flash` o `gemini-1.5-flash` con vision multimodale per PDF e immagini).
* Se `GEMINI_API_KEY` è assente: attiva `MockAIService` che riconosce pattern chiave tramite regex e mock deterministici, permettendo la piena esecuzione dei test offline.

---

## 5. Specifiche API REST (FastAPI)

Tutti gli endpoint rispondono con codice HTTP standard e payload JSON.

### 5.1 `POST /api/chat`
* **Richiesta**:
  ```json
  { "message": "Ho messo il passaporto nel primo cassetto della scrivania" }
  ```
* **Risposta** (`200 OK`):
  ```json
  {
    "reply": "✅ Memorizzato! 📍 Passaporto: Scrivania studio → Primo cassetto.",
    "action": "STORE_LOCATION",
    "item_id": 1
  }
  ```

### 5.2 `POST /api/documents/upload`
* **Richiesta**: `multipart/form-data` con campo `file` (PDF, JPG, PNG).
* **Risposta** (`201 Created`):
  ```json
  {
    "document_id": 1,
    "title": "Bolletta Enel Luce",
    "issuer": "Enel Energia",
    "amount": 64.20,
    "due_date": "2026-10-28",
    "status": "da_pagare",
    "chat_reply": "📄 Ho letto la bolletta: Enel Luce (64,20 €) con scadenza 28 Ottobre 2026."
  }
  ```

### 5.3 `GET /api/dashboard`
* **Query Params**: `?filter=all|deadlines|items`
* **Risposta** (`200 OK`):
  ```json
  {
    "kpi": {
      "total_upcoming_amount": 2514.20,
      "pending_deadlines_count": 2,
      "total_documents_count": 42,
      "total_items_count": 18
    },
    "records": [
      {
        "id": 1,
        "type": "document",
        "title": "Bolletta Enel Luce (Ottobre)",
        "source": "Fotocamera / Upload",
        "amount": 64.20,
        "due_date": "2026-10-28",
        "status": "da_pagare",
        "badge_color": "amber"
      }
    ]
  }
  ```

### 5.4 `PATCH /api/documents/{id}/status`
* **Richiesta**: `{ "status": "quietanzato" }`
* **Risposta**: Aggiorna lo stato del documento e restituisce il record modificato.

### 5.5 `GET /` & Static Files
* Serve direttamente [`index.html`](file:///c:/Users/Leo/Desktop/DOVE-LO-AI-MESSO/index.html).

---

## 6. Sicurezza e Protezione Dati
* **Conservazione Locale Cifrata**: I file caricati risiedono nella directory `storage/uploads/` e il database SQLite risiede in `storage/vault.db`.
* **Sanitizzazione Nomi File**: Nessun file mantiene il nome originale dell'utente per prevenire directory traversal; i file vengono salvati con nome UUID (`<uuid>.<ext>`).
* **Predisposizione Multi-Tenant per SaaS**: La struttura dei modelli include chiarezza relazionale pronta per aggiungere la foreign key `user_id` quando introdurremo l'autenticazione per l'abbonamento mensile.

---

## 7. Strategia di Test (TDD)
Ogni componente viene sviluppato seguendo il ciclo Red $\to$ Green $\to$ Refactor:
1. `tests/test_models.py`: Verifica creazione tabelle, vincoli di integrità e query di filtro scadenze.
2. `tests/test_ai_service.py`: Verifica che gli schemi Pydantic validino correttamente date, importi e categorie, e che il Mock risponda in modo deterministico.
3. `tests/test_api.py`: Verifica con `fastapi.testclient.TestClient` di tutti gli endpoint REST (`/chat`, `/upload`, `/dashboard`).
