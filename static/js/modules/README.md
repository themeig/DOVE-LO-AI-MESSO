# Moduli JavaScript di 'Dove lo AI messo' (Architettura Modulare)

La logica frontend dell'applicazione è organizzata secondo il principio di Separation of Concerns (SoC) in moduli tematici puliti e indipendenti:

1. **`01-core.js`**: Inizializzazione applicazione, gestione token cifrato di sessione, sincronizzazione badge versione e rilevamento ambiente (`DESKTOP` vs `MOBILE`), aggiornamenti OTA, gestione tema Industrial Modern e lock screen di sicurezza con PIN/Password Master.
2. **`02-navigation.js`**: Controller dello scorrimento a slide tra schermate (Chat, Pannello, Impostazioni di Sistema), fisica touch 1:1 per gesti di swipe su mobile, gestione popstate/tasto indietro nativo Android e switch screen responsive.
3. **`03-threads.js`**: Gestione canali conversazionali (Threads), categorie tematiche, gruppi condivisi, selettore modelli linguistici (Gemini Flash Lite gratuito vs OpenRouter Pro) e schede impostazioni di sistema stile smartphone.
4. **`04-cloud.js`**: Controller per la sincronizzazione cloud bidirezionale con Google Drive (OAuth popup, storage mode 'dual' o 'cloud_only') e integrazione Google Calendar con sincronizzazione automatica scadenze tributi/utenze.
5. **`05-chat.js`**: Motore conversazionale completo: invio messaggi e streaming, formattazione markdown per nastro dattilografico, canale telemetria feedback silenzioso, registratore vocale nativo Web Audio/Android con trascrizione Whisper, drag & drop file/cartelle e rendering schede widget protocollo interattive.
6. **`06-panel.js`**: Hub centrale del Pannello a 4 quadranti (Panoramica, Scadenze, Atti, Oggetti), metriche KPI FinTech, viste raggruppate per categoria/ambiente, tabella ledger con filtri a schede, stato quietanze e export CSV/ICS.
7. **`07-modals.js`**: Dialoghi operativi: visualizzatore avanzato documenti Office (Excel interattivo con formule, Word, CSV, PDF protetti), export/import backup completo ZIP con crittografia, monitoraggio cartelle PC locali con preset 1-click ed Esplora File, e modale Pitch Deck / White Paper.
