# Mobile App & Scanner Documentale Integrato Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implementare la versione mobile dedicata (`mobile.html` su `/m`) con routing automatico per smartphone/APK Android, isolando al 100% `index.html` (desktop intatto), gestendo elegantemente i permessi di fotocamera/microfono per WebView e integrando uno scanner documentale live con rilevamento bordi, raddrizzamento prospettico e filtri di nitidezza.

**Architecture:** 
- Routing e separazione in FastAPI (`app/main.py`): `GET /m` serve `mobile.html`, mentre `GET /` reindirizza i client mobile a `/m` (salvo override esplicito `?desktop=true`), lasciando `index.html` intoccato.
- Motore client-side dedicato (`static/js/mobile-scanner.js`): gestione fotocamera live ad alta risoluzione, calcolo matrice di omografia per correzione prospettica, filtri colore/B&W su canvas e regolazione touch con lente d'ingrandimento.
- Frontend mobile (`mobile.html`): replica fedele della chat dattiloscritta Olivetti e della dashboard, calibrata per viewport mobile (`100dvh`, resize tastiera virtuale Android) e dialogo permessi preventivo.

**Tech Stack:** Python 3.12+, FastAPI, TestClient, JavaScript (Canvas API, WebRTC MediaDevices, Homography Warp), HTML5, Tailwind CSS.

**Spec:** [`docs/superpowers/specs/2026-09-24-mobile-app-scanner-design.md`](file:///c:/Users/Leo/Desktop/DOVE-LO-AI-MESSO/docs/superpowers/specs/2026-09-24-mobile-app-scanner-design.md)

## Global Constraints

- `index.html` DEVE rimanere rigorosamente intatto al 100% (zero modifiche, zero rischi per la versione desktop).
- `app/version.py` DEVE essere incrementato a `2.5.0` (SemVer MINOR per nuovo sottosistema mobile e scanner).
- Nessun banner o file manifest PWA (il contesto target è un APK Android WebView esistente).
- Tutte le chiamate alle API del caveau (`/chat`, `/api/documents/upload`, `/api/transcribe`, `/dashboard-data`) devono riutilizzare i contratti esistenti senza alterare le route del backend.
- Tutti i test pytest devono passare (suite minima: 209 test attuali + nuovi test di routing e upload scanner).

## Review Focus

1. **User-Agent Detection Edge Cases**: Browser tablet (es. iPad o tablet Android) o User-Agent non convenzionali dell'APK non devono andare in loop infinito di redirect.
2. **Override Desktop**: Un utente su smartphone che clicca "Passa a Desktop" (`/?desktop=true`) non deve essere rispedito a `/m`.
3. **Android WebView Permission Denial**: Quando l'utente nega i permessi per fotocamera o microfono, l'app non deve bloccarsi o generare un'eccezione non gestita; deve mostrare la guida al ripristino e il fallback.
4. **Scanner on Weak Hardware**: Se l'algoritmo di edge detection non rileva 4 contorni nitidi, deve posizionare un quadrilatero di default sicuro senza bloccare lo scatto.
5. **Virtual Keyboard Layout Shifts**: L'apertura della tastiera Android in chat non deve nascondere l'input di digitazione né spingere la barra fuori dallo schermo.

---

### Task 1: Routing & User-Agent Detection (`/m` e auto-redirect)

**Files:**
- Modify: `app/main.py:120-150`
- Test: `tests/test_mobile_routing.py`

**Interfaces:**
- Consumes: FastAPI `Request`, `FileResponse`, `RedirectResponse`
- Produces: `GET /m -> FileResponse(mobile.html)`, `GET / -> redirect to /m if is_mobile_ua and not force_desktop`

- [ ] **Step 1: Write the failing tests in `tests/test_mobile_routing.py`**

```python
# tests/test_mobile_routing.py
from fastapi.testclient import TestClient
from app.main import app
from app.models.database import init_db

client = TestClient(app)

def setup_module():
    init_db()

def test_get_mobile_endpoint_returns_mobile_html():
    res = client.get("/m")
    assert res.status_code == 200
    assert "text/html" in res.headers.get("content-type", "")

def test_desktop_user_agent_serves_index_html():
    desktop_ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    res = client.get("/", headers={"User-Agent": desktop_ua}, follow_redirects=False)
    assert res.status_code == 200
    assert "text/html" in res.headers.get("content-type", "")

def test_mobile_user_agent_redirects_to_m():
    mobile_ua = "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
    res = client.get("/", headers={"User-Agent": mobile_ua}, follow_redirects=False)
    assert res.status_code in (302, 307)
    assert res.headers["location"] == "/m"

def test_mobile_user_agent_with_desktop_query_bypasses_redirect():
    mobile_ua = "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
    res = client.get("/?desktop=true", headers={"User-Agent": mobile_ua}, follow_redirects=False)
    assert res.status_code == 200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_mobile_routing.py -v`  
Expected: FAIL (endpoint `/m` non ancora definito, 404).

- [ ] **Step 3: Implement routing in `app/main.py` and placeholder `mobile.html`**

Crea un `mobile.html` iniziale valido e aggiungi in `app/main.py`:
- Funzione di utility `_is_mobile_user_agent(user_agent: str) -> bool`.
- Route `GET /m` che serve `mobile.html`.
- Aggiornamento di `GET /`: se `_is_mobile_user_agent` è True e `request.query_params.get("desktop") != "true"`, restituisci `RedirectResponse(url="/m", status_code=307)`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_mobile_routing.py -v`  
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add app/main.py mobile.html tests/test_mobile_routing.py
git commit -m "feat(mobile): add /m route and user-agent mobile redirect"
```

---

### Task 2: Modulo Scanner Documentale & Gestione Permessi (`static/js/mobile-scanner.js`)

**Files:**
- Create: `static/js/mobile-scanner.js`
- Test: `tests/test_mobile_scanner_module.py`

**Interfaces:**
- Produces: `window.MobileScanner = { openScanner, closeScanner, captureFrame, applyPerspectiveWarp, applyFilter, uploadCurrentScan, requestMobilePermission }`

- [ ] **Step 1: Write verification test for scanner assets and permissions endpoints**

```python
# tests/test_mobile_scanner_module.py
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_mobile_scanner_js_asset_exists():
    res = client.get("/static/js/mobile-scanner.js")
    assert res.status_code == 200
    assert "MobileScanner" in res.text
    assert "applyPerspectiveWarp" in res.text
    assert "getUserMedia" in res.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_mobile_scanner_module.py -v`  
Expected: FAIL (404 Not Found).

- [ ] **Step 3: Implement `static/js/mobile-scanner.js`**

Implementa:
1. `requestMobilePermission(type)`: dialoghi esplicativi Olivetti per Microfono e Fotocamera prima di `navigator.mediaDevices.getUserMedia`. Gestione di `NotAllowedError` con alert descrittivo e tasto riprova.
2. `startCamera(videoElement)`: attivazione `getUserMedia({ video: { facingMode: { ideal: "environment" }, width: { ideal: 1920 }, height: { ideal: 1080 } } })`.
3. `detectPaperCorners(canvas)`: binarizzazione/edge detection per estrarre i 4 vertici o fallback a margine del 10%.
4. `applyPerspectiveWarp(sourceCanvas, corners)`: calcolo matrice di omografia $3 \times 3$ e raddrizzamento del foglio in proporzioni rettangolari ortogonali.
5. `applyFilter(canvas, filterType)`:
   - `original`: resa fedele.
   - `magic_color`: contrast stretch, shadow normalization e sbiancamento sfondo.
   - `bw`: adaptive threshold per testo nero netto su sfondo bianco.
6. `uploadCurrentScan(canvas, threadId)`: esportazione in JPEG Blob e chiamata multipart a `/api/documents/upload`.
7. Interazione touch con 4 pin trascinabili e lente d'ingrandimento circolare (loupe 2x).

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_mobile_scanner_module.py -v`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add static/js/mobile-scanner.js tests/test_mobile_scanner_module.py
git commit -m "feat(scanner): implement mobile scanner engine and permission handlers"
```

---

### Task 3: Costruzione dell'Interfaccia Mobile Completa (`mobile.html`)

**Files:**
- Modify: `mobile.html`
- Test: `tests/test_mobile_html_structure.py`

**Interfaces:**
- Consumes: `static/js/app-bundle.js`, `static/js/mobile-scanner.js`, `/api/version`, `/chat`, `/api/documents/upload`
- Produces: Complete Olivetti mobile UI with full-screen typewriter chat, bottom mechanical input bar, scanner modal, dashboard drawer/view, and desktop switch.

- [ ] **Step 1: Write structural and integration tests for `mobile.html`**

```python
# tests/test_mobile_html_structure.py
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_mobile_html_contains_critical_components():
    res = client.get("/m")
    assert res.status_code == 200
    html = res.text
    # Meta tag per gestione tastiera Android
    assert "interactive-widget=resizes-content" in html
    # Inclusione dello scanner mobile
    assert "mobile-scanner.js" in html
    # Modale scanner
    assert "mobileScannerModal" in html or "scannerOverlay" in html
    # Tasto fotocamera/scanner
    assert "btnOpenScanner" in html or "openScanner" in html
    # Tasto microfono vocale Whisper
    assert "micButton" in html or "btnVoiceRecord" in html
    # Link per tornare alla versione desktop
    assert "desktop=true" in html or "prefer_desktop" in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_mobile_html_structure.py -v`  
Expected: FAIL.

- [ ] **Step 3: Implement complete `mobile.html`**

Costruisci `mobile.html` a partire dall'estetica Olivetti di `index.html`:
- Meta viewport: `width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, interactive-widget=resizes-content`.
- Safe area CSS: `padding-bottom: max(0.5rem, env(safe-area-inset-bottom))`.
- Header compatto: Brand "Dove lo AI messo", pulsante "DASHBOARD", indicatore stato Caveau e pulsante "Passa a Desktop".
- Chat log con nastro bicolore e schede protocollo ad altezza dinamica (`h-[100dvh]`).
- Barra di input meccanica con pulsanti touch maggiorati:
  - 📷 Tasto Scanner integrato (apre `#mobileScannerModal`).
  - 📎 Tasto Allegati tradizionali (PDF/file da memoria telefono).
  - 🎤 Tasto Microfono per dettatura Whisper con animazione impulso.
  - ↵ Tasto Invio.
- Modale Scanner a schermo intero:
  - Vista 1: Mirino live con reticolo e pulsante di scatto circolare.
  - Vista 2: Schermata di regolazione 4 angoli con maniglie touch e lente d'ingrandimento.
  - Vista 3: Selezione filtri (Originale / ✨ Magic Color / 📄 B&W) e pulsante "Protocolla nel Caveau".
- Inclusione degli script necessari (`app-bundle.js` e `mobile-scanner.js`).

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_mobile_html_structure.py -v`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add mobile.html tests/test_mobile_html_structure.py
git commit -m "feat(mobile): build complete Olivetti mobile interface and scanner modal"
```

---

### Task 4: Incremento di Versione & Verifica Rigorosa Non-Regressione

**Files:**
- Modify: `app/version.py`
- Modify: `AGENTS.md`
- Test: Full pytest test suite

- [ ] **Step 1: Increment SemVer in `app/version.py` to `2.5.0`**

Aggiorna `__version__ = "2.5.0"` in `app/version.py`.

- [ ] **Step 2: Update `AGENTS.md`**

Documenta la presenza del sottosistema mobile isolato (`mobile.html`, endpoint `/m`, modulo `mobile-scanner.js`).

- [ ] **Step 3: Run targeted tests and full suite**

Run: `pytest tests/test_version.py tests/test_mobile_routing.py tests/test_mobile_scanner_module.py tests/test_mobile_html_structure.py -v`  
Run: `pytest --tb=short -q`  
Expected: Tutti i test (oltre 212 test) passati senza errori.

- [ ] **Step 4: Verify `index.html` is 100% UNTOUCHED**

Run: `git diff index.html`  
Expected: Empty diff (nessuna modifica al desktop).

- [ ] **Step 5: Commit & Push to GitHub**

```bash
git add app/version.py AGENTS.md
git commit -m "feat(v2.5.0): release mobile app view, permissions handling, and document scanner"
git push origin main
```
