# 📄 WHITE PAPER: DOVE LO AI MESSO
### *Architettura, Sicurezza Crittografica, Motore Agentico e Interfaccia Duale per la Gestione Intelligente dei Documenti e delle Scadenze*

---

## 1. Executive Summary & Visione di Progetto

**"Dove lo AI messo"** è un assistente personale intelligente e caveau crittografico locale progettato per risolvere in modo definitivo il disordine documentale e la dispersione delle scadenze e degli oggetti quotidiani.

A differenza dei tradizionali sistemi di archiviazione complessi o dei cloud pubblici non protetti, **Dove lo AI messo** combina:
1. **Design Sistemico ad Alta Precisione Industriale**: un'interfaccia conversazionale e registro protocollo per azzerare la curva d'apprendimento.
2. **Executive Dashboard moderna**: una console stile SaaS/Fintech (ispirata a Linear, Stripe e Apple) per il controllo visivo di KPI, scadenze fiscali e inventario.
3. **Privacy-First & Crittografia a Riposo**: cifratura AES-128 / Fernet con PBKDF2 (600.000 iterazioni) e storage locale su SQLite, senza mai esporre i dati in chiaro.
4. **Motore Agentico Autonomo**: comprensione multimodale (PDF, Word, Excel, CSV, Immagini, ZIP), strumenti autonomi di compressione/decompressione, ricerca fuzzy con stemming italiano e scadenzario deterministico con countdown.

---

## 2. Architettura del Sistema

```text
+-------------------------------------------------------------------------+
|                  FRONTEND SPA (HTML5 / Tailwind CSS)                    |
|   +------------------------------------+  +--------------------------+  |
|   | 💬 Terminale Dattiloscritto        |  | 📊 Executive Dashboard   |  |
|   +------------------------------------+  +--------------------------+  |
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

### 3.1. Interfaccia Conversazionale = Design Sistemico ad Alta Precisione
- **Look & Feel di Registro**: Sfondo carta calda avorio (`#F8F5EE`), inchiostro grafite (`#222220`), verde salvia d'archivio (`#3C5A48`) e rosso terracotta (`#C84B31`). Schede di protocollo eleganti con timbri di convalida e timbri di stato.
- **Barra Input Meccanica**: Tasti di precisione tattile, campo testo monospace, pulsante fotocamera, menu popover allegati (File, Cartelle, Foto Oggetti), registratore vocale reale Whisper e pulsante d'invio terracotta.
- **Drag & Drop Universale con Directory Traversal Ricorsivo**: L'utente può trascinare qualsiasi file **o intera cartella** direttamente nell'area chat. Il motore `webkitGetAsEntry` esplora ricorsivamente le sottocartelle su tutti i livelli di profondità, raccogliendo ogni documento e avviando upload batch concorrente (3 worker paralleli) con barra di avanzamento in tempo reale e pulsante di interruzione immediata.
- **Sistema Notifiche In-App (Zero Alert Nativi)**: Un **Toast System floating** stile Linear/Stripe (successo 🟢, errore 🔴, avviso 🟡) e un **modale di conferma asincrono** in-app sostituiscono completamente gli alert e confirm bloccanti del browser per un'esperienza utente professionale e non invasiva.
- **Feedback Dinamico & Barra di Avanzamento**: Riconoscimento intelligente dell'azione con indicatore di stato testuale (es. *"Sto creando l'archivio ZIP..."*, *"Scansione cartelle locali in corso..."*) e barra di progressione in tempo reale per upload di cartelle e file multipli.


### 3.2. Executive Dashboard = Stile SaaS Moderno (Bento Grid)
- **Superficie Ultra-Moderna**: Sfondo slate neutro (`#F8FAFC`), Bento Grid con indicatori KPI in tempo reale:
  - *Totale Importi in Scadenza* (€) con badge dinamico del mese.
  - *Scadenze Pendenti* con alert per pagamenti urgenti.
  - *Documenti Protetti nel Caveau*.
  - *Oggetti & Posizioni Fisiche Catalogate*.
- **Tab Segmentate con Badge Dinamici**: Filtri istantanei (*Tutti, Da Pagare, **Quietanzati**, Oggetti*) con contatori numerici live che si aggiornano ad ogni operazione.
- **Alias Filtri API in Italiano**: I filtri `/api/dashboard?filter=` accettano alias italiani (`da_pagare`, `quietanzati`, `oggetti`, `scadenze`) per ergonomia massima nella chiamate AI e automazioni.
- **Azioni Rapide Protette**:
  - *Vista Raggruppata per Spazio/Gruppo*: schede tematiche con card animate e anteprime visive.
  - *Tabella Dettagliata*: filtri istantanei, badge di stato cromatici (*In Scadenza, Quietanzato, Conservato*), azioni rapide di download, marcatura pagamento con un click e cancellazione protetta da **modale di conferma in-app**.
- **Drag & Drop Nativo sulla Dashboard**: overlay dedicato per il rilascio di file e cartelle direttamente dall'esplora risorse sulla dashboard, con la stessa pipeline di elaborazione batch della chat.


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

### 4.1. Google Vertex AI Enterprise Security & Data Governance Perimeter

Per le elaborazioni che richiedono modelli linguistici e di visione multimodale avanzati, il sistema integra l'infrastruttura **Google Vertex AI Enterprise**, garantendo il più rigoroso perimetro di confidenzialità dei dati:

1. **Zero Data Retention for Training**: I dati dei clienti (immagini di scontrini, fatture, estratti conto, note sanitarie o documenti personali) **NON vengono mai utilizzati per addestrare o migliorare i modelli fondamentali** di Google o di terzi.
2. **Isolamento dei Dati & Crittografia End-to-End**: Tutti i flussi verso gli endpoint di inferenza sono incapsulati in connessioni TLS 1.3 con crittografia in transito e a riposo (Customer-Managed Encryption Keys / CMEK compatibili).
3. **Conformità Normativa Globale & Europea**: Piena aderenza ai requisiti **GDPR**, ISO/IEC 27001, SOC 1/2/3, e perimetro confidenziale idoneo per utilizzi bancari e medico-sanitari.
4. **SLA e Resilienza Enterprise**: Garanzia di disponibilità al 99.9% e basse latenze con pipeline deterministiche di fall-back locale.

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
- **Output**: Genera un file `INDICE_DOCUMENTI.txt` dettagliato ed emette una card interattiva di protocollo per il download immediato.
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

### 5. Cartelle Monitorate Locali (Folder Watcher) & Proposte Proattive
- **Monitoraggio Continuo in Background**: Scansione non invasiva di directory sensibili del computer (es. `Download`, `Documenti`, `Desktop`).
- **Rilevamento Intelligente File Sensibili**: L'agente analizza automaticamente i nuovi file scaricati dall'utente (buste paga, modelli 730, contratti, bollette, estratti conto bancari) escludendo i file preesistenti.
- **Proposta Proattiva nel Registro**: Quando viene intercettato un nuovo file sensibile, l'assistente invia un messaggio proattivo in chat proponendo di cifrarlo e archiviarlo nel caveau con un singolo click.
- **Integrazione Windows File Explorer**: Possibilità di aprire istantaneamente la cartella fisica nel file manager nativo del sistema operativo via API locale.

### 6. Integrazione Google Drive Completa & Sincronizzazione Cloud
- **Connessione Sicura OAuth 2.0**: Autenticazione crittografata con standard Google Cloud Identity per il collegamento istantaneo dell'account Google Drive dell'utente.
- **Tassonomia Automatica delle Cartelle**: Ogni file archiviato viene sincronizzato su Google Drive e organizzato in sottocartelle tematiche intelligenti per categoria e anno (`Bollette/2026/`, `Fisco/`, `Sanità/`, `Contratti/`).
- **Pulsante di Accesso Rapido `[Drive ↗]`**: Sulle schede interattive dei documenti nella chat è presente un tasto diretto per visualizzare o condividere il file sul cloud di Google in un istante.
- **NLU Dinamica & Consapevolezza Totale**: L'assistente AI è reso pienamente consapevole della struttura e dei file salvati su Google Drive, permettendo all'utente di chiedere informazioni e cercare documenti senza risposte predefinite o statiche.

### 7. Catalogazione Oggetti Fisici & Foto Posizione
- **Mappatura Dettagliata**: Memorizzazione dell'esatta collocazione di oggetti personali (stanza, mobile, cassetto, ripiano).
- **Associazione Fotografica Diretta**: Associazione di fotografie scattate o caricate, visualizzate come card fotografiche ad alta risoluzione.

---

## 7. Modalità di Esecuzione & Modelli di Distribuzione

### 7.1. Modelli di Distribuzione: Freemium Locale vs Cloud Multi-Tenant & Gruppi

Il progetto supporta due modalità di utilizzo chiaramente differenziate:

```text
+-----------------------------------------------------------------------------------------+
|                                    DOVE LO AI MESSO                                     |
+--------------------------------------------+--------------------------------------------+
|        🟢 FREEMIUM LOCALE (Gratuito)       |       ☁️ CLOUD PRO & GRUPPI (€9,90/m)       |
+--------------------------------------------+--------------------------------------------+
| • Storage Locale 100% su proprio PC (Disk) | • Cloud Storage Cifrato Zero-Knowledge     |
| • Crittografia AES-256 / PBKDF2 locale     | • Multi-Utente & Creazione Gruppi          |
| • Singolo Dispositivo / Nessun Account     | • Sincronizzazione Real-Time Multi-Device  |
| • Interfaccia Conversazionale + Dashboard Fintech | • Google Vertex AI Enterprise Perimeter    |
| • Zero costi ricorrenti / Open Source Core | • Notifiche Push / Canali Condivisi        |
| • Ideale per singoli e privacy maximalist  | • Ideale per Famiglie, Team e Professionisti|
+--------------------------------------------+--------------------------------------------+
```

1. **Edizione Freemium Locale (100% Free & Open Source)**:
   - **Perimetro di Esecuzione**: Completamente autonomo e installabile in locale (FastAPI + SQLite + PyWebView).
   - **Privacy Assoluta**: Tutti i file cifrati risiedono nella cartella `storage/uploads/` del computer dell'utente. Nessun dato lascia la macchina locale senza esplicita richiesta.
   - **Funzionalità Complete**: Terminale Conversazionale Intelligente, Bento Grid Dashboard, ricerca fuzzy con stemming, compressione ZIP e scadenzario deterministico inclusi senza limitazioni.

2. **Edizione Cloud Pro & Spazi di Gruppo (A Pagamento — €9,90 / mese per gruppo)**:
   - **Collaborazione Multi-Utente**: Possibilità di creare spazi e gruppi condivisi (*"Spese Casa"*, *"Famiglia"*, *"Commercialista / Ufficio"*, *"Coinquilini"*).
   - **Cloud Storage Cifrato Multi-Dispositivo**: Sincronizzazione sicura tra smartphone, tablet e PC desktop con chiavi crittografiche end-to-end.
   - **Integrazione Google Vertex AI Enterprise**: Massima confidenzialità con zero data retention per il training dei modelli, alte prestazioni e conformità bancaria/GDPR.
   - **Notifiche Push & Avvisi di Gruppo**: Avvisi automatici sincronizzati a tutti i membri del gruppo quando una bolletta o un F24 si avvicina alla data di scadenza.
   - **Gestione Ruoli & Permessi**: Controllo accessi granulare (Amministratore, Membro con diritto di inserimento, Visualizzatore Sola Lettura).

### 7.2. Launcher & Tecnologie di Esecuzione
- **Server Web FastAPI**: Avvio rapido con `uvicorn app.main:app --reload --port 8000`.
- **Desktop Nativo Windows (PyWebView)**: Launcher dedicato (`python run_desktop.py`) che avvia il server in background e apre una finestra desktop nativa Edge WebView2 senza bisogno del browser.
- **Motore AI Ibrido**: Integrazione Google Vertex AI Enterprise, gateway OpenRouter multimodale e motore deterministico offline Mock per testing senza connettività.

---

## 8. Tabella di Sintesi delle Funzionalità

| Categoria | Funzionalità | Descrizione |
| :--- | :--- | :--- |
| **Interfaccia** | **Design ad Alta Precisione** | Terminale conversazionale con schede protocollo, timbri e precisione visiva. |
| **Interfaccia** | **Executive Dashboard** | Bento Grid con KPI in tempo reale, tabelle filtrate e visualizzazione gruppi. |
| **Interfaccia** | **Feedback Dinamico** | Scritte di stato contestuali e barra di caricamento/progresso in tempo reale. |
| **Piani & Storage** | **Freemium Locale (€0)** | 100% Locale, storage su PC, crittografia AES-256, nessun canone. |
| **Piani & Storage** | **Cloud Pro & Gruppi** | Spazi condivisi (Famiglie, PMI), Cloud Storage cifrato multi-device, notifiche di gruppo. |
| **Sicurezza & AI** | **Google Vertex AI** | Perimetro Enterprise con zero-training retention, GDPR e ISO 27001. |
| **Sicurezza** | **AES-128 / Fernet** | Crittografia a riposo su database e file system locale. |
| **Sicurezza** | **PBKDF2 600k** | Derivazione chiave crittografica con password master `1234`. |
| **Sicurezza** | **Export Backup Caveau**| Download pacchetto ZIP completo con file e indice `vault_metadata.json`. |
| **Documenti** | **Lettura PDF** | Estrazione testo, importi, scadenze ed emittenti. |
| **Documenti** | **Office Word & Excel** | Parsing completo di `.docx`, `.xlsx` e `.csv`. |
| **Documenti** | **Compressione / Decompressione** | Tool agentici `create_zip_archive` e `unzip_vault_archive`. |
| **Documenti** | **Upload Batch & Cartelle** | Caricamento simultaneo di file multipli o intere cartelle. |
| **Oggetti** | **Localizzatore Oggetti** | Memorizzazione posizione dettagliata con supporto fotografico. |
| **PC & OS** | **Cartelle Monitorate (Folder Watcher)** | Monitoraggio background (Download/Desktop), rilevamento file sensibili e proposta proattiva in chat. |
| **Cloud & Sync** | **Google Drive Cloud Sync** | Sincronizzazione automatica OAuth 2.0 su tassonomia cartelle, link diretto `[Drive ↗]` e NLU dinamica. |
| **Voce** | **Dettatura Vocale Reale** | Riconoscimento vocale `it-IT` istantaneo con Web Speech / Whisper. |
| **Drag & Drop** | **Directory Traversal Ricorsivo** | Trascina intere cartelle: `webkitGetAsEntry` esplora sottocartelle multi-livello e avvia upload batch da chat e dashboard. |
| **UX / Notifiche** | **Toast System In-App** | Toast floating (successo/errore/avviso) e modale di conferma async. Zero alert bloccanti del browser. |
| **Dashboard** | **Tab Quietanzati + Badge Dinamici** | Tab segmentata con contatore live dei documenti quietanzati. Alias filtri API italiani (`da_pagare`, `quietanzati`, `oggetti`). |
| **Mobile & A11y** | **Touch Target 44 px + `100dvh` + ARIA** | Tutti i bottoni icona superano la soglia WCAG 2.1 di 44 px. Altezza pagina corretta su iOS con tastiera virtuale. Labels ARIA complete. |

---

*Documento redatto e convalidato per il progetto "Dove lo AI messo".*  
*Autore: Team di Sviluppo Dove lo AI messo — Versione 2.0 (2026).*
