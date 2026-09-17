# Guida Completa: Come Rendere Pubblica l'Integrazione Google Drive (Google Cloud Console)

Questa guida illustra nel dettaglio tutti i passaggi operativi, tecnici e legali necessari per portare l'applicazione da **"Modalità di Test" (In Testing)** a **"In Produzione" (Pubblica)** su Google Cloud Platform, consentendo a qualsiasi utente di collegare il proprio account Google Drive senza errori né blocchi.

---

## 1. Stato Attuale vs Stato Pubblico

| Aspetto | Stato di Test (Attuale) | Stato Pubblico (In Produzione) |
| :--- | :--- | :--- |
| **Chi può accedere** | Solo account email aggiunti manualmente come "Utenti di test" (max 100). | Qualsiasi utente con un account Google al mondo. |
| **Scadenza Refresh Token** | Il token scade ogni **7 giorni** (l'utente deve riconnettersi settimanalmente). | Il token **non scade mai** (salvo revoca manuale o disconnessione). |
| **Avviso di Sicurezza** | Schermata rossa di avviso: *"Google non ha verificato questa app"*. | Schermata di autorizzazione standard ufficiale di Google. |
| **Verifica Google** | Non richiesta. | Richiede la revisione della schermata di consenso (OAuth Consent Screen). |

---

## 2. Il Grande Vantaggio del Nostro Progetto: Lo Scope `drive.file`

In **"Dove lo AI messo"** abbiamo scelto deliberatamente lo scope:
```text
https://www.googleapis.com/auth/drive.file
```
- **Cos'è**: Dà accesso **esclusivamente** ai file e alle cartelle creati da questa specifica applicazione (la cartella `DoveLoAIMesso`), senza alcun accesso agli altri file privati dell'utente sul suo Google Drive.
- **Perché è fondamentale**: Google classifica `drive.file` come scope **Non-Sensibile / Consigliato**.
  - **NON** è richiesta la verifica di sicurezza avanzata di terze parti (CASA Tier 2/3), che costerebbe tra i 3.000$ e i 10.000$/anno.
  - È richiesta soltanto la **Verifica standard della Schermata di Consenso OAuth (gratuita)** gestita direttamente dal team Trust & Safety di Google.

---

## 3. Prerequisiti Obbligatori prima di Inviare la Richiesta

Google richiede che prima di cliccare su "Pubblica" siano pronti e online i seguenti elementi:

1. **Un Dominio Web di Proprietà (es. `doveloaimesso.it` o `doveloaimesso.com`)**:
   - Google non permette la verifica in produzione su indirizzi `localhost` o IP numerici.
   - Il dominio deve essere configurato con certificato SSL (**HTTPS obbligatorio**).
   - Devi verificare la proprietà del dominio su [Google Search Console](https://search.google.com/search-console/) usando lo stesso account Google sviluppatore.

2. **Informativa sulla Privacy (Privacy Policy)**:
   - Pagina web pubblica raggiungibile (es. `https://doveloaimesso.it/privacy`).
   - Deve contenere una clausola esplicita sull'uso dei dati delle API di Google conforme alla *Google API Services User Data Policy*, ad esempio:
     > *"L'uso e il trasferimento ad altre applicazioni delle informazioni ricevute dalle API di Google da parte di 'Dove lo AI messo' rispetteranno le Norme sui dati utente dei servizi API di Google, inclusi i requisiti per l'uso limitato (Limited Use Requirements)."*

3. **Termini di Servizio (Terms of Service)**:
   - Pagina web pubblica (es. `https://doveloaimesso.it/terms`).

4. **Home Page Ufficiale dell'Applicazione**:
   - Pagina web che descrive chiaramente cosa fa l'applicazione e perché necessita dell'integrazione Google Drive (es. `https://doveloaimesso.it`).

5. **Video Dimostrativo su YouTube (Non in elenco / Unlisted)**:
   - Google richiede un video registrato di circa 2-3 minuti che mostri:
     1. L'avvio dell'applicazione.
     2. Il clic su "Collega Google Drive".
     3. La schermata di login di Google dove si legga **chiaramente l'URL del browser con il Client ID** dell'applicazione (`client_id=361620600017-...`).
     4. Il consenso dell'utente.
     5. L'applicazione che carica un documento e lo salva nella cartella `DoveLoAIMesso` su Google Drive.

---

## 4. Procedura Passo-Passo su Google Cloud Console

### Passo 1: Verifica del Dominio
1. Accedi a [Google Search Console](https://search.google.com/search-console/).
2. Aggiungi la proprietà del tuo dominio (es. `doveloaimesso.it`) tramite record DNS TXT presso il tuo registrar (Aruba, Cloudflare, Namecheap, ecc.).
3. Vai su [Google Cloud Console](https://console.cloud.google.com/) $\to$ **API e servizi** $\to$ **Schermata consenso OAuth** $\to$ scheda **Domini autorizzati**.
4. Inserisci il dominio verificato (es. `doveloaimesso.it`).

### Passo 2: Configurazione della Schermata di Consenso OAuth
1. Seleziona il tipo utente: **Esterno (External)**.
2. Compila le informazioni di base:
   - **Nome applicazione**: `Dove lo AI messo`
   - **Email per l'assistenza utenti**: la tua email di contatto.
   - **Logo applicazione**: logo quadrato 120x120 px in formato PNG (facoltativo ma consigliato).
   - **Home page applicazione**: `https://doveloaimesso.it`
   - **Link all'informativa sulla privacy**: `https://doveloaimesso.it/privacy`
   - **Link ai Termini di servizio**: `https://doveloaimesso.it/terms`
   - **Indirizzi email di contatto sviluppatore**: il tuo indirizzo email.
3. Clicca su **Salva e continua**.

### Passo 3: Configurazione degli Ambiti (Scopes)
1. Nella sezione **Ambiti**, clicca su **Aggiungi o rimuovi ambiti**.
2. Cerca e seleziona:
   - `.../auth/drive.file` (Visualizzazione e gestione dei file e delle cartelle di Google Drive creati dall'app).
   - `.../auth/userinfo.email` (Visualizzazione dell'indirizzo email dell'account).
3. Clicca su **Aggiorna** e poi su **Salva e continua**.

### Passo 4: Aggiornamento delle Credenziali di Reindirizzamento (Redirect URI)
1. Vai su **API e servizi** $\to$ **Credenziali**.
2. Clicca sul tuo ID client OAuth 2.0.
3. Sotto **URI di reindirizzamento autorizzati**, aggiungi sia l'URL di sviluppo che quello di produzione:
   - `http://localhost:8000/api/drive/callback` (per lo sviluppo locale)
   - `https://doveloaimesso.it/api/drive/callback` (per il dominio pubblico in produzione)
4. Salva.

### Passo 5: Spostamento da "Testing" a "In Produzione"
1. Torna in **Schermata consenso OAuth**.
2. Sotto **Stato pubblicazione**, vedrai il pulsante **"Pubblica app" (Publish App)**.
3. Clicca su **Pubblica app** e conferma.
4. Comparirà il pulsante **"Prepara per la verifica" / "Invia per la verifica" (Submit for Verification)**.

### Passo 6: Compilazione del Modulo di Verifica Google
Google ti chiederà di compilare un modulo con:
- **Giustificazione dell'uso dello scope (`drive.file`)**:
  > *"L'applicazione 'Dove lo AI messo' è un archivio intelligente e caveau digitale. Utilizza lo scope drive.file esclusivamente per creare una cartella dedicata denominata 'DoveLoAIMesso' sul Drive dell'utente e sincronizzarvi copie di backup dei documenti e delle bollette caricate dall'utente stesso, ordinate per anno e categoria. L'app non accede ad alcun altro file o cartella preesistente nel Drive dell'utente."*
- **Link al video dimostrativo di YouTube (non in elenco)**.
- Conferma dell'URL della Privacy Policy.

### Passo 7: Revisione da parte del Team Google
1. Entro 3-7 giorni lavorativi, riceverai un'email da `api-oauth-dev-verification@google.com` o simile.
2. Spesso richiedono piccoli aggiustamenti (ad esempio rendere più visibile la clausola di Limited Use nella Privacy Policy o chiarire un passaggio nel video).
3. Una volta approvata, lo stato diventa **"Verificata"**:
   - Nessun limite al numero di utenti.
   - Nessun avviso di "App non verificata".
   - Token permanenti senza scadenza settimanale.

---

## 5. Checklist Rapida per la ToDo List

- [ ] Acquistare e configurare il dominio web ufficiale con HTTPS.
- [ ] Pubblicare le pagine web: Home page, Privacy Policy e Termini di Servizio.
- [ ] Verificare il dominio su Google Search Console.
- [ ] Registrare il video demo su YouTube (in modalità 'Non in elenco') mostrando il Client ID e la creazione della cartella `DoveLoAIMesso`.
- [ ] Aggiungere il dominio autorizzato e l'URI di reindirizzamento di produzione nella Google Cloud Console.
- [ ] Cliccare su **"Pubblica app"** e **"Invia per la verifica"** nella Schermata consenso OAuth.
- [ ] Rispondere all'email di revisione del team Trust & Safety di Google fino all'approvazione finale.
