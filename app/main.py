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

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Inizializza caveau crittografico e migra file se necessario
    mgr = get_vault_manager()
    mgr.initialize_if_needed()
    init_db()
    migrate_unencrypted_files()
    yield

app = FastAPI(
    title="Dove lo AI messo",
    description="Backend API for Dove lo AI messo",
    version="1.0.0",
    lifespan=lifespan
)

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

settings = get_settings()

def _serve_decrypted_file(filename: str):
    file_path = settings.STORAGE_DIR / filename
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

# Root endpoint serving index.html
@app.get("/")
def serve_index():
    index_file = settings.BASE_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return HTMLResponse("<h1>Dove lo AI messo</h1>")
