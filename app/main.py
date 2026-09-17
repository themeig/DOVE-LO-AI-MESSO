import asyncio
import logging
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response

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

app = FastAPI(
    title="Dove lo AI messo",
    description="Backend API for Dove lo AI messo",
    version="1.0.0",
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

# Endpoint White Paper
@app.get("/api/whitepaper")
def get_whitepaper():
    wp_file = settings.BASE_DIR / "WHITE_PAPER.md"
    if not wp_file.exists():
        raise HTTPException(status_code=404, detail="White Paper non trovato")
    return Response(
        content=wp_file.read_text(encoding="utf-8"),
        media_type="text/markdown; charset=utf-8"
    )

# Root endpoint serving index.html
@app.get("/")
def serve_index():
    index_file = settings.BASE_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return HTMLResponse("<h1>Dove lo AI messo</h1>")

# Showcase & Interactive Pitch Deck endpoints
@app.get("/showcase")
@app.get("/demo")
def serve_showcase():
    showcase_file = settings.BASE_DIR / "showcase.html"
    if showcase_file.exists():
        return FileResponse(showcase_file)
    return HTMLResponse("<h1>Dove lo AI messo — Showcase</h1>")
