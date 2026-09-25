import asyncio
import logging
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.models.database import init_db
from app.services.crypto_service import get_vault_manager
from app.services.document_service import read_decrypted_file, migrate_unencrypted_files

from app.api.auth import router as auth_router
from app.api.chat import router as chat_router
from app.api.documents import router as documents_router
from app.api.dashboard import router as dashboard_router
from app.api.items import router as items_router
from app.api.threads import router as threads_router
from app.api.settings import router as settings_router
from app.api.deadlines import router as deadlines_router
from app.api.telemetry import router as telemetry_router
from app.api.folders import router as folders_router
from app.api.export import router as export_router
from app.api.drive import router as drive_router

logger = logging.getLogger(__name__)

async def periodic_folder_monitor_loop():
    """Loop asincrono di background per monitorare periodicamente le cartelle attive (es. Download)."""
    # Attende 3 secondi all'avvio prima della prima esecuzione
    await asyncio.sleep(3)
    from app.models.database import get_engine, get_session_maker
    from app.services.folder_service import check_all_watched_folders_for_sensitive_files

    while True:
        try:
            engine = get_engine()
            SessionLocal = get_session_maker(engine)
            with SessionLocal() as db:
                check_all_watched_folders_for_sensitive_files(db, auto_notify=True)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Errore nel loop di monitoraggio cartelle: {e}")

        try:
            # Controllo periodico ogni 20 secondi
            await asyncio.sleep(20)
        except asyncio.CancelledError:
            break


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Inizializza caveau crittografico e migra file se necessario
    mgr = get_vault_manager()
    mgr.initialize_if_needed()
    init_db()
    migrate_unencrypted_files()

    # Avvia task in background per il monitoraggio cartelle
    monitor_task = asyncio.create_task(periodic_folder_monitor_loop())

    yield

    monitor_task.cancel()
    try:
        await monitor_task
    except asyncio.CancelledError:
        pass

from app.version import APP_VERSION

app = FastAPI(
    title="Dove lo AI messo",
    description="Backend API for Dove lo AI messo",
    version=APP_VERSION,
    lifespan=lifespan
)


# ==============================================================================
# SICUREZZA / TODO HARDENING CORS:
# Per ambienti di produzione o reti condivise, raccomandato restringere allow_origins=["*"]
# a domini fidati specifici (es. ["http://localhost:8000", "http://127.0.0.1:8000"]).
# Mantenuto attualmente ad allow_origins=["*"] su richiesta per comodità di sviluppo locale
# e test cross-origin da dispositivi locali (es. smartphone / tablet su Wi-Fi).
# ==============================================================================
# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount API Routers
app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(documents_router)
app.include_router(dashboard_router)
app.include_router(items_router)
app.include_router(threads_router)
app.include_router(settings_router)
app.include_router(deadlines_router)
app.include_router(telemetry_router)
app.include_router(folders_router)
app.include_router(export_router)
app.include_router(drive_router)

settings = get_settings()

# Serve static assets (CSS, JS) from /static/
_static_dir = settings.BASE_DIR / "static"
if _static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")

def _serve_decrypted_file(filename: str):
    file_path = get_settings().STORAGE_DIR / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File non trovato")
    decrypted_bytes = read_decrypted_file(file_path)
    ext = file_path.suffix.lstrip(".").lower()
    if ext == "pdf":
        media_type = "application/pdf"
    elif ext in ["jpg", "jpeg"]:
        media_type = "image/jpeg"
    elif ext == "png":
        media_type = "image/png"
    elif ext == "webp":
        media_type = "image/webp"
    elif ext == "wav":
        media_type = "audio/wav"
    elif ext == "mp3":
        media_type = "audio/mpeg"
    elif ext in ["webm", "weba"]:
        media_type = "audio/webm"
    elif ext in ["ogg", "oga"]:
        media_type = "audio/ogg"
    elif ext == "m4a":
        media_type = "audio/mp4"
    else:
        media_type = "application/octet-stream"
    return Response(content=decrypted_bytes, media_type=media_type)

# Endpoint decifrati al volo per immagini e documenti
@app.get("/uploads/{filename}")
def get_uploaded_file(filename: str):
    return _serve_decrypted_file(filename)

@app.get("/api/files/{filename}")
def get_api_file(filename: str):
    return _serve_decrypted_file(filename)

# Endpoint Versione App
@app.get("/api/version")
def get_app_version():
    return {
        "version": APP_VERSION,
        "app_name": "Dove lo AI messo",
        "description": "Executive AI Vault & Organizzatore Intelligente"
    }

# Endpoint White Paper (HTML Styled con CSS, fallback a raw Markdown)
@app.get("/whitepaper")
@app.get("/api/whitepaper")
def get_whitepaper(request: Request):
    fmt = request.query_params.get("format", "").lower()
    accept = request.headers.get("accept", "").lower()

    wp_file = settings.BASE_DIR / "WHITE_PAPER.md"
    wp_html = settings.BASE_DIR / "whitepaper.html"

    # Se richiesto esplicitamente raw markdown o client CLI (curl con text/markdown puro)
    if fmt in ("raw", "md", "markdown") or ("text/markdown" in accept and "text/html" not in accept):
        if not wp_file.exists():
            raise HTTPException(status_code=404, detail="White Paper non trovato")
        return Response(
            content=wp_file.read_text(encoding="utf-8"),
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": 'inline; filename="WHITE_PAPER.md"'}
        )

    # Navigazione da browser: pagina HTML completa di CSS Tailwind e tipografia
    if wp_html.exists():
        return FileResponse(
            wp_html,
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )
    elif wp_file.exists():
        return Response(
            content=wp_file.read_text(encoding="utf-8"),
            media_type="text/markdown; charset=utf-8"
        )
    raise HTTPException(status_code=404, detail="White Paper non trovato")

def _is_mobile_user_agent(ua: str) -> bool:
    if not ua:
        return False
    ua_lower = ua.lower()
    mobile_keywords = [
        "android", "iphone", "ipod", "ipad", "mobile", "blackberry", "iemobile", "opera mini", "webos"
    ]
    return any(k in ua_lower for k in mobile_keywords)

# Endpoint Mobile dedicato
@app.get("/m")
def serve_mobile():
    mobile_file = settings.BASE_DIR / "mobile.html"
    if mobile_file.exists():
        return FileResponse(
            mobile_file,
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )
    return HTMLResponse("<h1>Dove lo AI messo — Mobile</h1>")

# Root endpoint serving index.html (con redirect a /m per dispositivi mobili)
@app.get("/")
def serve_index(request: Request):
    desktop_override = (
        request.query_params.get("desktop") == "true" or
        request.cookies.get("prefer_desktop") == "true"
    )
    ua = request.headers.get("user-agent", "")
    if not desktop_override and _is_mobile_user_agent(ua):
        return RedirectResponse(url="/m", status_code=307)

    index_file = settings.BASE_DIR / "index.html"
    if index_file.exists():
        return FileResponse(
            index_file,
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )
    return HTMLResponse("<h1>Dove lo AI messo</h1>")

# Showcase & Interactive Pitch Deck endpoints
@app.get("/showcase")
@app.get("/demo")
@app.get("/m/showcase")
def serve_showcase():
    showcase_file = settings.BASE_DIR / "showcase.html"
    if showcase_file.exists():
        return FileResponse(
            showcase_file,
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )
    return HTMLResponse("<h1>Dove lo AI messo — Showcase</h1>")


# =========================================================================
# ENDPOINT AGGIORNAMENTI OTA APPLICAZIONE ANDROID (LOCALE / LAN)
# =========================================================================

@app.get("/api/app/version")
def get_mobile_app_version():
    """Restituisce i metadati di versione per l'auto-updater dell'app Android."""
    import json
    from app.version import APP_VERSION
    version_file = settings.BASE_DIR / "android-release" / "version.json"
    if version_file.exists():
        try:
            return json.loads(version_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "version_code": 281,
        "version_name": APP_VERSION,
        "apk_url": "/api/app/latest-apk",
        "release_notes": "Aggiornamento applicazione"
    }


@app.get("/api/app/latest-apk")
def download_latest_apk():
    """Fornisce il download diretto dell'ultimo APK per aggiornamento locale/LAN."""
    from app.version import APP_VERSION
    release_apk = settings.BASE_DIR / "android-release" / "app-debug.apk"
    build_apk = settings.BASE_DIR / "android" / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"

    target_apk = release_apk if release_apk.exists() else build_apk
    if not target_apk.exists():
        raise HTTPException(status_code=404, detail="File APK non ancora compilato sul server.")

    return FileResponse(
        target_apk,
        media_type="application/vnd.android.package-archive",
        filename=f"doveloaimesso-v{APP_VERSION}.apk"
    )

