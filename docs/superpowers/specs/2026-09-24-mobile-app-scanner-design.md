# Design Document: Mobile App & Scanner Documentale Integrato (v2.5.0)

Data: 24 Settembre 2026  
Stato: Approvato  
Target: Android APK (WebView) e dispositivi mobile  

---

## 1. Obiettivo & Visione

Fornire un'esperienza mobile nativa ed ergonomica per l'APK Android di **"Dove lo AI messo"**, mantenendo **al 100% intatta la versione desktop** ([`index.html`](file:///c:/Users/Leo/Desktop/DOVE-LO-AI-MESSO/index.html)) senza alcun rischio di regressioni.

La versione mobile conserva l'esatta identità grafica e funzionale **Olivetti Industrial** (chat dattiloscritta, registro meccanico, transizione fluida con la dashboard), aggiungendo:
1. **Isolamento totale**: la vista mobile risiede in `mobile.html` servita su `/m` e con reindirizzamento automatico da `/` per i dispositivi mobili.
2. **Scanner documentale stile Google Drive**: mirino live a schermo intero con fotocamera posteriore, riconoscimento dei 4 bordi del foglio, raddrizzamento prospettico (dewarping), filtri di nitidezza (Magic Color e Bianco & Nero) e maniglie touch per aggiustare gli angoli.
3. **Gestione permessi robusta per WebView APK**: autorizzazioni guidate per Fotocamera (`android.permission.CAMERA`) e Microfono (`android.permission.RECORD_AUDIO`), con dialoghi esplicativi ed eleganti per evitare blocchi o crash in caso di permessi negati.
4. **Ergonomia e stabilità viewport**: supporto alla tastiera virtuale di Android con `interactive-widget=resizes-content` e `100dvh`.

---

## 2. Architettura del Sistema

```
                         [ Richiesta Utente ]
                                  │
                                  ▼
                     FastAPI: GET / (app/main.py)
                                  │
                  ┌───────────────┴───────────────┐
                  ▼                               ▼
       User-Agent = Mobile/APK           User-Agent = Desktop
                  │                               │
                  ▼                               ▼
             Reindirizza a:               Serve direttamente:
            GET /m (mobile.html)               index.html
          (Isolamento Mobile 100%)       (Desktop Intatto 100%)
```

### Componenti Principali:
1. **`mobile.html`**:
   - Replica fedele del frontend Olivetti adattato per smartphone.
   - Layout touch a tutta altezza con safe-area per la barra inferiore Android/iOS.
   - Include il modulo scanner (`static/js/mobile-scanner.js`) e il visualizzatore modale.
2. **`static/js/mobile-scanner.js`**:
   - Modulo JavaScript autonomo per gestione della fotocamera live via Web APIs (`getUserMedia`).
   - Rilevamento automatico dei contorni del foglio e calcolo dei 4 vertici.
   - Trasformazione omografica di prospettiva (perspective warp).
   - Filtri di pulizia documento: Originale, Colore Nitido (Magic Color) e Bianco & Nero.
   - Interfaccia touch con 4 maniglie magnetiche per la rifinitura manuale degli angoli.
3. **`app/main.py`**:
   - Endpoint `GET /m`: restituisce `mobile.html`.
   - Middleware/Route handler su `GET /`: rileva User-Agent mobile ed effettua redirect `307 Temporary Redirect` a `/m` (bypassabile con parametro `?desktop=true` o cookie di preferenza).
4. **Endpoint API Ingestion**:
   - Lo scanner mobile invia i documenti scansionati direttamente a `POST /api/documents/upload`, riutilizzando la pipeline multimodale AI, la cifratura locale AES-Fernet e la sincronizzazione con Google Drive (rispettando la modalità impostata, compreso il nuovo `local_only`).

---

## 3. Gestione Permessi Fotocamera & Microfono (WebView APK)

Nelle WebView Android, le chiamate a `getUserMedia` richiedono che l'APK intercetti `onPermissionRequest`. Dal punto di vista Web:

1. **Richiesta Contestuale (Just-in-Time)**:
   - Microfono: richiesto esclusivamente quando l'utente preme il tasto del registratore vocale.
   - Fotocamera: richiesta esclusivamente quando l'utente preme l'icona dello scanner.
2. **Pre-Dialogo Informativo Olivetti**:
   - Prima della richiesta a livello di sistema operativo, appare un avviso chiaro:
     - 🎤 *"Autorizzazione Microfono: necessaria per registrare e trascrivere note vocali con Whisper."*
     - 📷 *"Autorizzazione Fotocamera: necessaria per inquadrare e scansionare documenti cartacei con il mirino ottico."*
3. **Recupero da Permesso Negato**:
   - Se l'utente nega il permesso, viene mostrata una scheda esplicativa con istruzioni precise per abilitarlo nelle impostazioni di Android (`Impostazioni > App > Dove lo AI messo > Autorizzazioni`).
   - Tasto "Riprova" per riavviare la richiesta.
4. **Fallback Meccanico**:
   - Per la fotocamera è sempre garantito il fallback con `<input type="file" accept="image/*" capture="environment">` qualora il flusso video in streaming non fosse autorizzato dall'hardware.

---

## 4. Specifiche del Modulo Scanner Documentale

### 4.1 Mirino Live & Acquisizione
- Flusso video a schermo intero con fotocamera posteriore (`facingMode: { ideal: "environment" }`).
- Risoluzione richiesta: Full HD (1920x1080 o superiore).
- Reticolo guida semitrasparente a tema Olivetti salvia (`#3C5A48`).
- Pulsante di scatto meccanico circolare con feedback visivo.

### 4.2 Riconoscimento Bordi & Calcolo Vertici
- Acquisizione del fotogramma ad alta definizione in un canvas off-screen.
- Binarizzazione e rilevamento bordi (filtro Canny + ricerca contorni).
- Approssimazione del poligono convesso a 4 vertici: $P_1, P_2, P_3, P_4$.
- Se i contorni non sono netti (es. sfondo poco contrastato), posiziona automaticamente un quadrilatero standard con margine del 10% dai bordi.

### 4.3 Regolazione Manuale degli Angoli (Touch Handles)
- Schermata di revisione con l'immagine scattata e i 4 punti evidenziati.
- L'utente può trascinare ciascuno dei 4 angoli con il pollice.
- Sopra il dito compare una lente di ingrandimento (loupe a cerchio 2x) per posizionare l'angolo con precisione millimetrica.

### 4.4 Raddrizzamento Prospettico (Perspective Warp)
- Calcolo della matrice di trasformazione prospettica $3 \times 3$ tra il quadrilatero sorgente e il rettangolo di destinazione avente proporzioni A4 / proporzioni native del foglio.
- Ricampionamento bilineare per produrre un'immagine piatta, ortogonale e perfettamente rettangolare.

### 4.5 Filtri Documento
1. **Originale**: immagine raddrizzata con resa cromatica fedele.
2. **Documento a Colori (Magic Color)**:
   - Sbiancamento dello sfondo per eliminare le ombre del cellulare o dell'ambiente.
   - Aumento del contrasto cromatico del testo e dei timbri.
3. **Testo B&W (Bianco e Nero Netto)**:
   - Soglia adattiva locale per eliminare pieghe, macchie di carta e aloni.
   - Testo nitido e nero puro, ideale per scontrini termici e moduli F24.

### 4.6 Conclusione & Archiviazione
- Tasto **"Protocolla nel Caveau"**:
  - Converte il canvas in Blob JPEG ad alta risoluzione (qualità 92%).
  - Esegue la chiamata multipart `POST /api/documents/upload` con `thread_id` corrente.
  - Chiude il mirino e mostra la card documento e la risposta dell'AI nella chat.

---

## 5. Viewport, Stili e Compatibilità Tastiera Android

1. **Meta Viewport**:
   ```html
   <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, interactive-widget=resizes-content">
   ```
2. **Dimensionamento Schermo**:
   - Utilizzo di `min-h-[100dvh]` e `h-[100dvh]` per evitare il salto visivo all'apertura della barra dell'URL o della tastiera Gboard/Samsung.
3. **Safe Areas**:
   - `padding-bottom: max(0.5rem, env(safe-area-inset-bottom))` per non collidere con la pillola/gesture bar inferiore di Android.
4. **Pulsante di Ritorno a Desktop**:
   - Nell'header di `mobile.html`, icona elegante `fa-desktop` con tooltip/didascalia *"Versione Desktop"*, che imposta il cookie `force_desktop=1` e reindirizza a `/`.

---

## 6. Piano di Collaudo & Verifica

1. **Test di Routing & Isolamento**:
   - Testare che `GET /` con User-Agent desktop continui a servire `index.html`.
   - Testare che `GET /` con User-Agent Android/iPhone reindirizzi a `/m`.
   - Testare che `GET /m` serva `mobile.html` con codice HTTP 200.
   - Testare che `/?desktop=true` bypassi il redirect mobile.
2. **Test Scanner & Image Processing**:
   - Verifica del modulo `mobile-scanner.js` (funzioni di homography, warp e filtri).
   - Test del caricamento file generato dallo scanner verso l'endpoint `/api/documents/upload`.
3. **Test Permessi**:
   - Verifica dei messaggi di fallback in caso di mancata autorizzazione fotocamera/microfono.
4. **Verifica Non-Regressione**:
   - Esecuzione completa della test suite pytest (tutti i 209 test passati).
   - Verifica che `index.html` non contenga modifiche o regressioni.
