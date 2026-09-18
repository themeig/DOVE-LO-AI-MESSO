# 🧭 Dove lo AI messo

> **Il caveau intelligente per non perdere mai più un documento o un oggetto.**
> Unisce un'interfaccia chat familiare al 100% in stile **WhatsApp Web** con una **Dashboard SaaS moderna** (stile Linear/Stripe/Apple) per il controllo di scadenze, tributi e faldoni fisici.

---

## 🌟 Caratteristiche Principali

- 💬 **Chat WhatsApp al 100%**: Interfaccia fedele per azzerare la curva d'apprendimento (bolle, spunte, typing indicator animato, input rapido con fotocamera e allegati).
- 📊 **Dashboard SaaS & Bento Grid**: Indicatori KPI, scadenzario fiscale con badge dinamici (*In Scadenza*, *Quietanzato*, *Archiviato*), visualizzazione per categorie e stanze.
- ☁️ **Integrazione Google Drive Completa**: Sincronizzazione cloud automatica con autenticazione OAuth 2.0. Ogni file archiviato viene organizzato su Google Drive in sottocartelle per categoria e anno (`Bollette/2026/`, `Fisco/`), con link diretto `[Drive ↗]` in chat e ricerca agentica senza risposte predefinite.
- 📂 **Cartelle PC Monitorate (Folder Watcher)**: Monitoraggio in background delle directory locali (Download, Documenti, Desktop). Rileva in automatico nuovi documenti sensibili (buste paga, 730, contratti, bollette) e invia una proposta proattiva in chat per cifrarli e archiviarli con un click.
- 🖥️ **Desktop App Nativa**: Avvio come applicazione Windows nativa (WebView2 via `pywebview`) con accesso diretto alle cartelle del computer.
- 🔐 **Caveau Crittografato**: Protezione e crittografia dei file a riposo tramite Fernet (chiave derivata da password master).
- 📸 **Collegamento Foto a Oggetti Fisici**: Associa foto e allegati a posizioni reali (*"Dov'è il passaporto?"* $\to$ mostra posizione e foto del cassetto).
- 📦 **Esportazione & Backup ZIP**: Download con un click dell'intero archivio decifrato con metadati in formato JSON/CSV.

---

## 📋 Requisiti di Sistema

- **Python 3.12** o superiore (testato su Python 3.12 e 3.13)
- **Git** installato
- **Windows 10 / 11** (per la modalità Desktop nativa con WebView2) o qualsiasi OS (per la modalità Web/Browser)

---

## 🚀 Guida all'Installazione

### 1. Clona il Repository
```bash
git clone https://github.com/themeig/DOVE-LO-AI-MESSO.git
cd DOVE-LO-AI-MESSO
```

### 2. Crea e Attiva un Virtual Environment (Consigliato)

**Su Windows (PowerShell):**
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

**Su Linux / macOS:**
```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Installa le Dipendenze
```bash
pip install -r requirements.txt
```

---

## 🔑 Configurazione OpenRouter API Key

L'applicazione utilizza **OpenRouter** per l'intelligenza artificiale (estrazione automatica dati da PDF/foto, riconoscimento scadenze e conversazione naturale con tool-calling).

### Come ottenere la chiave API:
1. Registrati o accedi gratuitamente su [openrouter.ai](https://openrouter.ai/).
2. Vai nella sezione [Keys (openrouter.ai/keys)](https://openrouter.ai/keys).
3. Clicca su **"Create Key"**, assegna un nome (es. `Dove lo AI messo`) e copia la chiave generata (avrà un formato simile a `sk-or-v1-...`).
4. *(Opzionale)* Ricarica qualche credito (anche solo \$5 durano migliaia di richieste con i modelli Flash).

### Come impostare la chiave nel progetto:
1. Crea una copia del file `.env.example` chiamandola `.env`:

   **Su Windows:**
   ```powershell
   copy .env.example .env
   ```
   **Su Linux / macOS:**
   ```bash
   cp .env.example .env
   ```

2. Apri il file `.env` con un editor di testo (es. Blocco Note, VS Code) e inserisci la tua chiave:
   ```env
   OPENROUTER_API_KEY=sk-or-v1-tua-chiave-openrouter-qui
   OPENROUTER_MODEL=google/gemini-2.5-flash-lite
   DEBUG=True
   ```

> 💡 **Nota sui Modelli:** Di default l'app è ottimizzata per `google/gemini-2.5-flash-lite` (molto veloce ed economico). Puoi anche impostare `google/gemini-2.5-pro` o qualsiasi modello supportato da OpenRouter modificando `OPENROUTER_MODEL`.

---

## 🎮 Come Avviare l'Applicazione

Puoi utilizzare l'app in **due modalità**:

### Modalità 1: Desktop App (Consigliata su Windows)
Apre una finestra desktop dedicata e nativa:
```bash
python run_desktop.py
```

### Modalità 2: Web Server (Browser)
Avvia il server locale FastAPI accessibile da qualsiasi browser:
```bash
python -m uvicorn app.main:app --reload --port 8000
```
Quindi apri il browser su: 👉 **`http://localhost:8000`**

---

## 🔒 Password Predefinita del Caveau

Al primo accesso o per sbloccare le funzionalità protette del Caveau:
- **Password Master predefinita**: `1234`

*(La password può essere personalizzata dalle impostazioni o dal modulo di autenticazione).*

---

## 🧪 Esecuzione della Suite di Test

Il progetto include una suite completa di test automatizzati (90+ test):

```bash
python -m pytest -v
```

---

## 📁 Struttura del Progetto

```text
DOVE-LO-AI-MESSO/
├── app/
│   ├── api/             # Router REST FastAPI (chat, documents, folders, export, ...)
│   ├── models/          # Modelli SQLite SQLAlchemy e schemi Pydantic
│   ├── services/        # Logica di business (AI service, agentic service, crypto, search, ...)
│   ├── desktop.py       # Configurazione host desktop pywebview
│   └── main.py          # Entrypoint applicativo FastAPI
├── storage/             # Directory locale per DB SQLite e file cifrati
├── tests/               # Suite completa di test automatizzati (pytest)
├── index.html           # SPA frontend reattiva (HTML5, Tailwind CSS, Vanilla JS)
├── requirements.txt     # Dipendenze Python
├── run_desktop.py       # Launcher Desktop per Windows
├── .env.example         # Template variabili d'ambiente
└── README.md            # Documentazione di progetto
```

---

## 📄 Licenza

Distribuito sotto licenza MIT. Consulta il repository per ulteriori dettagli.
