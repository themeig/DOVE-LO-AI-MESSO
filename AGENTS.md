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
