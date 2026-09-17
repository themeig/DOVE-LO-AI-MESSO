# Specifica Architetturale: Integrazione Google Drive (Cloud Storage Opzionale)

**Data**: 17 Settembre 2026  
**Autore**: Leo & Antigravity  
**Stato**: Approvato (In fase di pianificazione operativa)

---

## 1. Obiettivo & Visione del Prodotto

Consentire agli utenti di collegare il proprio account personale **Google Drive** come destinazione opzionale di archiviazione per i documenti caricati in chat o nella dashboard.

### Principi Guida:
1. **Zero Lock-in & Privacy Totale**: Utilizzo esclusivo dello scope `https://www.googleapis.com/auth/drive.file`. L'app accede unicamente ai file e alle cartelle creati dall'app stessa. Nessun accesso a foto personali o file preesistenti nel Drive dell'utente.
2. **Organizzazione Intelligente Automatica**: I file caricati non vengono dispersi alla rinfusa, ma catalogati automaticamente dall'AI in un albero strutturato per **Anno e Categoria**:
   ```text
   📁 DoveLoAIMesso/
      ├── 📁 2026/
      │   ├── 📁 Bollette & Utenze/
      │   │   └── 2026-10-28_Enel_64.20eur.pdf
      │   └── 📁 Fisco & Tasse/
      │       └── 2026-09-16_F24_1450eur.pdf
      └── 📁 Documenti Personali/
          └── Carta_Identita.pdf
   ```
3. **Controllo Utente sulla Conservazione**: L'utente può scegliere nelle impostazioni:
   - **Doppio salvataggio (Predefinito)**: copia locale cifrata nel caveau (per velocità e disponibilità offline) + caricamento organizzato su Google Drive.
   - **Solo Google Drive**: il file fisico risiede solo su Drive (risparmiando spazio su disco del PC), mentre in locale rimangono solo metadati, indice semantico e miniature.
4. **Resilienza e Sviluppo Offline**: Presenza di un motore `MockGoogleDriveService` che consente lo sviluppo, l'esecuzione dei test automatici e l'uso senza credenziali cloud attive, con commutazione trasparente all'API reale non appena configurati `GOOGLE_CLIENT_ID` e `GOOGLE_CLIENT_SECRET`.

---

## 2. Architettura dei Componenti

```
┌────────────────────────────────────────────────────────┐
│                   FRONTEND (index.html)                │
│  • Schermata Impostazioni: Stato Google Drive,         │
│    pulsante "Collega Google Drive" / "Disconnetti",    │
│    selettore modalità storage (Doppio / Solo Drive)    │
│  • Schede Documento Chat: pulsante [Google Drive ↗]   │
└───────────────────────────▲────────────────────────────┘
                            │ REST JSON
┌───────────────────────────▼────────────────────────────┐
│                    BACKEND (FastAPI)                   │
│                                                        │
│  [API Endpoints: app/api/drive.py]                     │
│  • GET  /api/drive/status                              │
│  • GET  /api/drive/auth-url                            │
│  • GET  /api/drive/callback                            │
│  • POST /api/drive/disconnect                          │
│  • PATCH /api/drive/settings                           │
│                                                        │
│  [Service Layer: app/services/drive_service.py]        │
│  • GoogleDriveServiceInterface (Protocollo)            │
│  • RealGoogleDriveService (Chiamate REST v3 / httpx)   │
│  • MockGoogleDriveService (Emulatore deterministico)   │
│                                                        │
│  [Storage & Upload Pipeline: app/api/documents.py]     │
│  • Upload hook: se Drive è attivo, invia file a        │
│    drive_service.upload_document_to_drive()            │
│  • Popola drive_file_id e drive_web_url su Document    │
│                                                        │
│  [Database: app/models/database.py]                    │
│  • Tabella GoogleDriveCredential (token cifrati)       │
│  • Campi drive_file_id, drive_web_url in Document      │
└────────────────────────────────────────────────────────┘
```

---

## 3. Modello Dati & Database

### 3.1 Nuova Tabella `google_drive_credentials`
Memorizza i token OAuth dell'utente in forma cifrata tramite `EncryptedText` (chiave del caveau AES-GCM):

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

### 3.2 Modifica Modello `Document`
Aggiunta dei campi per il riferimento remoto a Google Drive:
- `drive_file_id = Column(String(255), nullable=True, index=True)`
- `drive_web_url = Column(String(500), nullable=True)`

---

## 4. Servizio Google Drive (`app/services/drive_service.py`)

### 4.1 Funzionalità Principali
1. **`get_auth_url(state: str) -> str`**:
   Genera l'URL di autorizzazione OAuth per l'utente verso `https://accounts.google.com/o/oauth2/v2/auth`.
2. **`exchange_code(code: str) -> dict`**:
   Scambia il codice di autorizzazione con `access_token` e `refresh_token` tramite `https://oauth2.googleapis.com/token`.
3. **`get_or_create_folder(folder_name: str, parent_id: Optional[str]) -> str`**:
   Cerca o crea la cartella su Google Drive e restituisce il suo `folder_id`.
4. **`upload_file(file_bytes: bytes, filename: str, mime_type: str, folder_id: str) -> dict`**:
   Esegue l'upload multipart su Google Drive e restituisce `{ "file_id": "...", "web_view_link": "..." }`.
5. **`resolve_folder_path(doc_type: str, due_date: Optional[date]) -> list[str]`**:
   Determina la gerarchia corretta:
   - Se c'è una data di scadenza o anno: `["DoveLoAIMesso", str(due_date.year), category_name]`
   - Altrimenti: `["DoveLoAIMesso", "Documenti & Altro"]`

### 4.2 Mappatura Categorie Cartelle
| `doc_type` | Nome Cartella su Drive |
| :--- | :--- |
| `bolletta`, `utenza` | `Bollette & Utenze` |
| `f24`, `tributo`, `fiscale`, `modello_unico` | `Fisco & Tasse` |
| `fattura`, `ricevuta`, `scontrino` | `Fatture & Spese` |
| `contratto`, `certificato`, `polizza` | `Contratti & Polizze` |
| `foto`, `screenshot`, `generico` | `Documenti & Foto` |

---

## 5. Endpoints REST API (`app/api/drive.py`)

* **`GET /api/drive/status`**:
  Restituisce `{ "connected": bool, "user_email": str, "storage_mode": str, "mode": "real" | "mock" }`.
* **`GET /api/drive/auth-url`**:
  Restituisce `{ "auth_url": "https://accounts.google.com/..." }`.
* **`GET /api/drive/callback?code=...`**:
  Riceve il redirect da Google OAuth, salva i token cifrati nel DB e restituisce redirect o stato di successo.
* **`PATCH /api/drive/settings`**:
  Aggiorna `storage_mode` (`"dual"` o `"cloud_only"`).
* **`POST /api/drive/disconnect`**:
  Cancella le credenziali locali e disconnette il cloud storage.

---

## 6. Integrazione nel Flusso di Upload Documenti (`app/api/documents.py`)

All'interno di `_process_and_save_single_doc()` o subito dopo l'analisi AI:
1. Verifica se esiste una credenziale `GoogleDriveCredential` attiva.
2. Se attiva:
   - Chiama `drive_service.upload_document_to_drive(...)`.
   - Popola `doc.drive_file_id` e `doc.drive_web_url`.
   - Se `storage_mode == "cloud_only"`: evita di salvare il file duplicato sul disco locale (o mantiene solo un puntatore leggero), salvando comunque tutti i metadati estratti per le ricerche istantanee in chat e dashboard.
3. Nel dizionario di ritorno per il frontend include `drive_web_url`.

---

## 7. Interfaccia Utente (WhatsApp Chat & Dashboard)

1. **Card del Documento in Chat**:
   - Accanto al link di anteprima e download, compare il pulsante:
     `[ Apri su Google Drive ↗ ]` con icona verde/rossa/gialla di Drive.
2. **Pannello Impostazioni (Modal o Scheda dedicata)**:
   - Stato: *"Connesso come nome@gmail.com"* con badge verde.
   - Pulsante *"Disconnetti"*.
   - Selettore Radio:
     - 🔘 *Conserva copia locale cifrata + Google Drive (Consigliato)*
     - 🔘 *Solo Google Drive (Risparmia spazio disco sul PC)*

---

## 8. Piano di Test & Validazione

1. **Test Unitari Servizio (`tests/test_drive_service.py`)**:
   - Verifica risoluzione percorsi cartelle e nomi file.
   - Verifica mock upload e ritorno di `file_id` e `web_view_link`.
2. **Test Endpoints API (`tests/test_drive_api.py`)**:
   - `GET /api/drive/status` (disconnesso e connesso).
   - Scambio codice callback e salvataggio credenziali cifrate.
   - `PATCH /api/drive/settings` con cambio modalità.
   - `POST /api/drive/disconnect`.
3. **Test Integrazione Upload (`tests/test_documents_drive.py`)**:
   - Upload file in chat con Drive attivo $\to$ verifica associazione `drive_file_id` e `drive_web_url`.
   - Verifica modalità `cloud_only` vs `dual`.
4. **Esecuzione Suite Completa**:
   - Tutti i 116 test esistenti devono continuare a passare senza alcuna regressione.
