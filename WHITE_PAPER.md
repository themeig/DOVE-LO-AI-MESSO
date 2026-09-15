# 📄 WHITE PAPER: DOVE LO AI MESSO
### *Architettura, Sicurezza Crittografica, Motore Agentico e Interfaccia Duale per la Gestione Intelligente dei Documenti e delle Scadenze*

---

## 1. Executive Summary & Visione di Progetto

**"Dove lo AI messo"** è un assistente personale intelligente e caveau crittografico locale progettato per risolvere in modo definitivo il disordine documentale e la dispersione delle scadenze e degli oggetti quotidiani.

A differenza dei tradizionali sistemi di archiviazione complessi o dei cloud pubblici non protetti, **Dove lo AI messo** combina:
1. **Curva d'apprendimento azzerata**: una chat conversazionale con look & feel identico al 100% a WhatsApp.
2. **Executive Dashboard moderna**: una console stile SaaS/Fintech (ispirata a Linear, Stripe e Apple) per il controllo visivo di KPI, scadenze fiscali e inventario.
3. **Privacy-First & Crittografia a Riposo**: cifratura AES-128 / Fernet con PBKDF2 (600.000 iterazioni) e storage locale su SQLite, senza mai esporre i dati in chiaro.
4. **Motore Agentico Autonomo**: comprensione multimodale (PDF, Word, Excel, CSV, Immagini, ZIP), strumenti autonomi di compressione/decompressione, ricerca fuzzy con stemming italiano e scadenzario deterministico con countdown.

---

## 2. Architettura del Sistema

```text
+-------------------------------------------------------------------------+
|                  FRONTEND SPA (HTML5 / Tailwind CSS)                    |
|   +--------------------------+    +----------------------------------+  |
|   | 💬 Chat WhatsApp (100%)  |    | 📊 Executive Bento Dashboard     |  |
|   +--------------------------+    +----------------------------------+  |
+-----------------------------------+-------------------------------------+
                                    |
                                    v
+-------------------------------------------------------------------------+
|                   BACKEND FASTAPI (Python 3.12+)                        |
|   /api/chat   |   /api/documents   |   /api/dashboard   |   /api/auth   |
+-----------------------------------+-------------------------------------+
                                    |
                                    v
+-------------------------------------------------------------------------+
|                      CORE SERVICES & AGENT ENGINE                       |
|   🧠 Agentic Tool Loop        |  🔍 Fuzzy Search & Stemming Engine      |
|   🗄️ Zip & Office Extractor  |  ⚡ Multimodal AI Engine (OpenRouter)   |
|   🛡️ Crypto Service (AES-128 Fernet + PBKDF2 600k iterations)          |
+-----------------------------------+-------------------------------------+
                                    |
                                    v
+-------------------------------------------------------------------------+
|                       SECURE STORAGE LAYER                              |
|   🗃️ SQLite (Encrypted Columns) | 🔒 AES Encrypted Uploads Folder       |
+-------------------------------------------------------------------------+
```

---

## 3. Filosofia del Design: Il Meglio dei Due Mondi

### 3.1. Chat Conversazionale = 100% Stile WhatsApp
- **Look & Feel Nativo**: Header verde WhatsApp (`#075E54` / `#128C7E`), sfondo con texture a grana fine (`#EFEAE2`), bolle tipiche (bianco per l'assistente, verde menta `#E7FFDB` per l'utente con doppie spunte azzurre `#53BDEB`).
- **Barra Input Fedele**: Selettore emoji, campo a pillola, pulsante fotocamera, menu popover allegati (File, Cartelle, Foto Oggetti), microfono vocale reale e pulsante d'invio circolare verde WhatsApp (`#25D366`).
- **Feedback Dinamico & Barra di Avanzamento**: Riconoscimento intelligente dell'azione con indicatore di stato testuale (es. *"Sto creando l'archivio ZIP..."*, *"Scansione cartelle locali in corso..."*) e barra di progressione in tempo reale per upload di cartelle e file multipli.

### 3.2. Executive Dashboard = Stile SaaS Moderno (Bento Grid)
- **Superficie Ultra-Moderna**: Sfondo slate neutro (`#F8FAFC`), Bento Grid con indicatori KPI in tempo reale:
  - *Totale Importi in Scadenza* (€) con badge dinamico del mese.
  - *Scadenze Pendenti* con alert per pagamenti urgenti.
  - *Documenti Protetti nel Caveau*.
  - *Oggetti & Posizioni Fisiche Catalogate*.
- **Doppia Vista**:
  - *Vista Raggruppata per Spazio/Gruppo*: schede tematiche con card animate e anteprime visive.
  - *Tabella Dettagliata*: filtri istantanei (*Tutti, Da Pagare, Pagati, Oggetti*), badge di stato cromatici (*In Scadenza, Quietanzato, Conservato*), azioni rapide di download, marcatura pagamento con un click e cancellazione protetta.

---

## 4. Sicurezza & Crittografia a Livello Militare

La sicurezza di **Dove lo AI messo** è basata sul principio di **Zero-Knowledge Locale**:

| Componente | Algoritmo / Meccanismo | Descrizione Tecnica |
| :--- | :--- | :--- |
| **Crittografia Dati** | **AES-128 / Fernet (CBC + HMAC-SHA256)** | Testi e documenti sono cifrati prima della scrittura su disco. |
| **Derivazione Chiave** | **PBKDF2-HMAC-SHA256 (600.000 iterazioni)** | La chiave viene derivata in memoria RAM dalla password master e da un salt crittografico casuale a 16 byte. |
| **Protezione Database** | **TypeDecorator SQLAlchemy (`EncryptedString`, `EncryptedText`)** | Le colonne `title`, `summary`, `issuer`, `content`, `item_name`, `primary_location`, `notes` risiedono cifrate su SQLite. |
| **Storage Binari** | **AES File Encryption** | I file caricati in `storage/uploads/` vengono cifrati a livello di byte. |
| **Session Lifecycle** | **Token Entropici Monouso (32 byte)** | Nessuna password memorizzata in sessione. Blocco immediato con un click. |

---

## 5. Supporto Formati & Pipeline di Estrazione Multimodale

Il sistema supporta nativamente qualsiasi documento o file dell'utente:

| Formato | Estensioni | Motore di Parsing | Dati Estratti |
| :--- | :--- | :--- | :--- |
| **Documenti PDF** | `.pdf` | `pypdf` + LLM Vision/Text | Titolo, Emittente, Importo, Data Scadenza, Tipo Documento, Riassunto. |
| **Documenti Word** | `.docx`, `.doc` | `python-docx` | Testo strutturato, titoli, tabelle e clausole contrattuali. |
| **Fogli di Calcolo** | `.xlsx`, `.xls` | `openpyxl` | Intestazioni di colonna, righe contabili, prospetti spese e totali. |
| **Dati Tabellari** | `.csv`, `.tsv` | CSV Auto-Decoder multi-charset | Colonne, righe, importi e descrizioni con rilevamento automatico delimitatori. |
| **Immagini & Foto** | `.jpg`, `.jpeg`, `.png`, `.webp`, `.bmp`, `.tiff` | Multimodal Vision AI | OCR visivo, lettura bollette fotografate, riconoscimento oggetti fisici e stanze. |
| **Archivi Compressi**| `.zip`, `.rar`, `.7z`, `.tar`, `.gz` | `zipfile` & Archiver Engine | Indice interno, estrazione e indicizzazione automatica nel caveau. |

---

## 6. Strumenti Agentici & Funzionalità Autonome

L'assistente opera mediante un ciclo di decisione agentico dotato dei seguenti strumenti:

### 1. `create_zip_archive`
- **Scopo**: Comprime documenti specifici o intere categorie in un unico file `.zip` cifrato nel caveau.
- **Output**: Genera un file `INDICE_DOCUMENTI.txt` dettagliato ed emette una card interattiva WhatsApp per il download immediato.
- **Comandi di esempio**: *"creami uno zip con tutte le bollette"*, *"fai uno zip dei documenti del 2026"*.

### 2. `unzip_vault_archive`
- **Scopo**: Estrae un archivio ZIP caricato nel caveau, analizza ciascun file interno con l'AI e cataloga automaticamente i documenti.
- **Comandi di esempio**: *"scompatta l'archivio fatture.zip"*, *"estrai i file dallo zip"*.

### 3. Motore di Ricerca Semantico-Lessicale
- **Stemming Italiano**: Riconoscimento automatico di singolari e plurali (*bolletta* $\leftrightarrow$ *bollette*, *chiave* $\leftrightarrow$ *chiavi*).
- **Sinonimi Concettuali**: Mappatura automatica (*luce* $\leftrightarrow$ *enel*, *gas* $\leftrightarrow$ *a2a*, *tributi* $\leftrightarrow$ *f24*).
- **Fuzzy Matching con Levenshtein Distance $\le 2$**: Tolleranza totale ai refusi e agli errori di battitura.
- **Zero Cross-Contamination**: Isolamento rigoroso tra categorie differenti per garantire la massima accuratezza.

### 4. Scadenzario Fiscale Deterministico & Countdown
- **Calcolo Preciso**: Determinazione esatta dei giorni mancanti rispetto alla data odierna (`Oggi`, `Domani`, `Tra X giorni`, `Scaduto da Y giorni`).
- **Urgenza Dinamica**: Badge cromatici (*Rosso* per $\le 3$ giorni o scaduti, *Ambra* per $\le 10$ giorni, *Verde* per oltre 10 giorni).

### 5. Monitoraggio Cartelle PC & Integrazione Windows Explorer
- Monitoraggio continuo di directory locali (es. `C:\Documenti\Fatture`).
- Sincronizzazione incrementale automatica dei nuovi file.
- Apertura istantanea della cartella fisica in Windows File Explorer via API locale.

### 6. Catalogazione Oggetti Fisici & Foto Posizione
- Memorizzazione dell'esatta posizione di oggetti personali (stanza, mobile, cassetto, ripiano).
- Associazione di fotografie scattate o caricate, visualizzate come card fotografiche ad alta risoluzione.

---

## 7. Modalità di Esecuzione & Desktop Launcher

- **Server Web FastAPI**: Avvio rapido con `uvicorn app.main:app --reload --port 8000`.
- **Desktop Nativo Windows (PyWebView)**: Launcher dedicato (`python run_desktop.py`) che avvia il server in background e apre una finestra desktop nativa Edge WebView2 senza bisogno del browser.
- **Multi-Modello AI**: Compatibilità con OpenRouter (`google/gemini-2.5-flash-lite`, `anthropic/claude-3.5-sonnet`, `openai/gpt-4o-mini`, `deepseek/deepseek-chat`) e motore deterministico offline Mock per ambienti senza connessione.

---

## 8. Tabella di Sintesi delle Funzionalità

| Categoria | Funzionalità | Descrizione |
| :--- | :--- | :--- |
| **Interfaccia** | **WhatsApp Look & Feel** | Chat fedele con doppie spunte, wallpaper e barra input autentica. |
| **Interfaccia** | **Executive Dashboard** | Bento Grid con KPI in tempo reale, tabelle filtrate e visualizzazione gruppi. |
| **Interfaccia** | **Feedback Dinamico** | Scritte di stato contestuali e barra di caricamento/progresso in tempo reale. |
| **Sicurezza** | **AES-128 / Fernet** | Crittografia a riposo su database e file system. |
| **Sicurezza** | **PBKDF2 600k** | Derivazione chiave crittografica con password master `1234`. |
| **Sicurezza** | **Export Backup Caveau**| Download pacchetto ZIP completo con file e indice `vault_metadata.json`. |
| **Documenti** | **Lettura PDF** | Estrazione testo, importi, scadenze ed emittenti. |
| **Documenti** | **Office Word & Excel** | Parsing completo di `.docx`, `.xlsx` e `.csv`. |
| **Documenti** | **Compressione / Decompressione** | Tool agentici `create_zip_archive` e `unzip_vault_archive`. |
| **Documenti** | **Upload Batch & Cartelle** | Caricamento simultaneo di file multipli o intere cartelle. |
| **Oggetti** | **Localizzatore Oggetti** | Memorizzazione posizione dettagliata con supporto fotografico. |
| **PC & OS** | **Cartelle Monitorate** | Auto-indexing da disco locale e apertura in Windows Explorer. |
| **Voce** | **Dettatura Vocale Reale** | Riconoscimento vocale `it-IT` istantaneo con Web Speech / Whisper. |

---

*Documento redatto e convalidato per il progetto "Dove lo AI messo".*  
*Autore: Team di Sviluppo Dove lo AI messo — Versione 2.0 (2026).*
