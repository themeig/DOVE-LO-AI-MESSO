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

---

## 5. Server MCP Completo (Model Context Protocol)
Il server MCP (`app/mcp_server.py`) espone **tutti i 20 tool del caveau** per consentire a client ed agenti esterni (es. Claude Desktop, cursor, AGY, script) di operare al 100% sul sistema:
1. `get_current_date`: data, ora, giorno della settimana e formato italiano per calcolo scadenze.
2. `get_app_version`: restituisce la versione dell'applicazione (`APP_VERSION`).
3. `get_vault_stats`: statistiche generali, conteggi KPI, totale insoluti in euro e stato cloud.
4. `get_vault_context`: contesto aggiornato in tempo reale (ultimi documenti, oggetti, scadenze).
5. `search_vault`: ricerca universale con tolleranza ai refusi, sinonimi e singolari/plurali.
6. `list_vault_contents`: elenco completo documenti o oggetti fisici.
7. `get_recent_vault_documents`: ultimi documenti acquisiti nel caveau.
8. `store_physical_item`: memorizzazione, aggiornamento o spostamento oggetti fisici e stanze.
9. `link_document_to_item`: collegamento foto/documento/scontrino a oggetto fisico.
10. `get_upcoming_deadlines`: scadenzario tributi e utenze con categorizzazione urgenza.
11. `rename_vault_document`: rinomina personalizzata dei titoli documento.
12. `recategorize_vault_document`: modifica, riorganizza o crea liberamente nuove sezioni/categorie tematiche per i documenti del caveau (es. 'Canzoni & Testi Musicali', 'Ricette & Cucina', 'Appunti Universitari', 'Automobili & Manutenzione', ecc.).
13. `delete_vault_record`: eliminazione sicura singola o cumulativa (confermabile).
14. `create_zip_archive`: creazione e download archivio compresso ZIP di file selezionati.
15. `unzip_vault_archive`: decompressione e catalogazione automatica AI dei file dello ZIP.
16. `get_google_drive_status`: stato connessione Drive, modalità ('dual'/'cloud_only') e struttura cartelle.
17. `scan_local_folder`: scansione e indicizzazione cartelle del computer (es. Download).
18. `list_watched_folders`: elenco cartelle locali monitorate.
19. `open_local_file_in_explorer`: apertura nativa in Esplora File di Windows (`explorer.exe`).
20. `read_vault_document_content`: ispezione, lettura puntuale e anti-allucinazione di dati tabellari e testuali reali di file Excel (.xlsx/.xls con formule calcolate), CSV, Word (.docx) e PDF.

Prompt MCP inclusi: `vault_assistant_instructions`, `assistant_behavior_and_widget_rules`, `google_drive_sync_guidelines`.

---

## 6. Comportamento Professionale dell'Assistente & Matrice Decisionale dei Widget
* **Tono Concierge Esecutivo**: Lingua italiana naturale, educata, rassicurante e impeccabile. Nessun gergo tecnico di database verso l'utente.
* **Autonomia Decisionale sui Widget (Niente Automatismi)**:
  * L'assistente decide in totale autonomia se il contesto richiede di mostrare widget interattivi (`show_document_card` o conferme) oppure solo testo.
  * **QUANDO HA SENSO (Chiamare Widget)**:
    - Richiesta esplicita di consultazione, apertura, visualizzazione o download di documenti ("dammi", "mostrami", "apri", "scarica", "vedi", "cerca").
    - Richieste cumulative ("scaricali entrambi", "mostrali tutti e due"): emette subito le schede per ciascun file.
    - Dopo decompressione di un file ZIP: mostra le schede interattive di tutti i documenti estratti.
    - Azioni di eliminazione: mostra la card interattiva di conferma per consentire l'azione sicura.
  * **QUANDO NON HA SENSO (Vietato Chiamare Widget)**:
    - Domande meta, informative o di presentazione ("cosa puoi fare?", "chi sei?", "come funzioni?", "aiuto", saluti).
    - Esempi illustrativi nel testo (citare un documento a puro titolo di esempio).
    - Ricerca di posizioni fisiche prive di foto (rispondere con testo preciso).
    - Calcoli o totali di spesa numerici (rispondere con testo e calcoli).
    - Domande esplicative su Google Drive, cartelle PC o crittografia.

---

## 7. Categorizzazione Semantica Autonoma & Creazione Dinamica Sezioni (No Codice Rigido)
* **Nessun Elenco Chiuso né Vincoli Rigidi**: L'assistente AI comprende autonomamente il significato e lo scopo di qualsiasi file caricato (canzoni, poesie, ricette, dispense universitarie, manuali, scontrini, contratti, ecc.).
* **Discrezione Totale sulla Creazione di Nuove Sezioni**:
  * Se il file rientra naturalmente nelle sezioni standard, viene catalogato lì.
  * Se il file ha un'altra natura (es. testo di una canzone o brano musicale), l'AI crea liberamente ed elegantemente la nuova sezione tematica (es. *"Canzoni & Testi Musicali"*) con icona FontAwesome dedicata (`fa-music`), senza mai forzarlo in categorie inappropriate come utenze o bollette.
  * L'utente e l'AI possono in qualsiasi momento riorganizzare o creare nuove sezioni tramite il tool `recategorize_vault_document`.

---

## 8. Ispezione Dati Puntuali, Tabelle Excel e Divieto Assoluto di Allucinazioni
* **Zero Allucinazioni sui Dati**: Quando l'utente chiede dettagli su righe, colonne, valori, importi o celle di un foglio di calcolo (es. 'cosa c'è nella riga 5?', 'quanto ha fatturato a marzo?', 'qual è l'importo nella colonna B?'), l'AI è tassativamente vincolata all'uso di `read_vault_document_content`.
* **Decifratura e Valutazione Formule**: Il sistema decifra il file in memoria RAM ed estrae i dati reali (con formule calcolate tramite openpyxl `data_only=True`, coordinate colonne A/B/C e numeri di riga 1-indexed reali di Excel).
* **Risposta Puntuale ed Esatta**: L'assistente risponde citando la riga, la cella o la tabella reale senza mai tirare a indovinare o inventare dati non presenti nel file.




