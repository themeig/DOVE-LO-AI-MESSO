# DOVE LO AI MESSO - Regole di Progetto (AGENTS.md)

Questo documento definisce l'architettura, le convenzioni di design e i vincoli tecnici per lo sviluppo di **"Dove lo AI messo"**.

---

## 1. Filosofia del Prodotto: Il Meglio dei Due Mondi
* **Chat Screen = WhatsApp al 100%**:
  * Autentico look & feel WhatsApp per azzerare la curva d'apprendimento.
  * Header verde WhatsApp (`#075E54` / `#128C7E`), sfondo beige con texture a grana fine (`#EFEAE2`), bolle tipiche (bianco per l'assistente, verde menta `#E7FFDB` per l'utente con doppie spunte azzurre).
  * Barra input fedele con graffetta, fotocamera, campo testo a pillola, microfono e pulsante d'invio circolare verde WhatsApp (`#25D366`).
  * Tasto dedicato e visibile nell'header: **"Apri Dashboard"**.

* **Dashboard = Ultra-Moderna & Sofisticata**:
  * Stile SaaS/Fintech moderno (ispirato a Linear, Stripe e Apple).
  * Sfondo neutro pulito (`#F8FAFC`), Bento-grid di indicatori KPI con bordi sottili e arrotondati (`rounded-2xl` / `rounded-3xl`).
  * Selettori a schede segmentate, tabella scadenze elegante con badge di stato dinamici (In Scadenza, Quietanzato, Conservato), e azioni rapide con anteprima file.
  * Tasto immediato: **"← Torna alla Chat"**.

---

## 2. Modalità di Interazione
1. **Chat Conversazionale (WhatsApp UI)**:
   * Foto / PDF (📎): l'utente invia la foto $\to$ l'AI estrae fornitore, importo e scadenza e conferma nella bolla.
   * Vocale (🎤): trascrizione Whisper e memorizzazione posizione oggetti/documenti.
   * Testo: domande libere in linguaggio naturale.
2. **Dashboard Operativa**:
   * Visualizzazione completa dello scadenzario fiscale, bollette e inventario faldoni/oggetti con filtri e caricamento diretto da PC.

---

## 3. Architettura Tecnica
* **Frontend**: SPA reattiva (HTML5, Tailwind CSS, Vanilla JS) con transizione istantanea tra Chat e Dashboard.
* **Backend**: Python 3.12+ (FastAPI):
  * `/chat` (elaborazione messaggi e RAG)
  * `/upload` (estrazione dati da immagini e PDF con Pydantic)
  * `/transcribe` (Whisper)
  * `/dashboard-data` (feed unico per lo scadenzario e l'archivio)
* **Database**: SQLite locale + ricerca vettoriale.

---

## 4. Regola Assoluta di Versionamento (Version Increment)
* **Single Source of Truth**: Il file [`app/version.py`](app/version.py) definisce `APP_VERSION = "X.Y.Z"`.
* **Incremento Obbligatorio ad Ogni Modifica**:
  * Ad OGNI modifica apportata al codice, correzione di bug o aggiunta di funzionalità su richiesta dell'utente, l'assistente DEVE tassativamente **incrementare il numero di versione** in `app/version.py` (convenzione SemVer: PATCH per correzioni/tweaks, MINOR per nuove funzionalità/endpoint, MAJOR per refactoring strutturali).
  * La versione è esposta e propagata via:
    1. Endpoint REST `GET /api/version` e campo `app_version` in `GET /api/dashboard`.
    2. Header di FastAPI (`app.version`).
    3. UI Frontend: badge visibili nella Chat WhatsApp (sidebar e header conversazione), nella Dashboard (top bar e menu Strumenti), e nella lock screen.
  * L'assistente DEVE sempre indicare chiaramente all'utente il nuovo numero di versione attivo nel messaggio di risposta per garantire il perfetto allineamento e coordinamento tra assistenti e sviluppatori.

