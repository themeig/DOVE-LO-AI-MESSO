from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.models.database import init_db
from app.api.chat import router as chat_router
from app.api.documents import router as documents_router
from app.api.dashboard import router as dashboard_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
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
app.include_router(chat_router)
app.include_router(documents_router)
app.include_router(dashboard_router)

# Mount static files for uploads if directory exists
settings = get_settings()
if settings.STORAGE_DIR.exists():
    app.mount("/uploads", StaticFiles(directory=str(settings.STORAGE_DIR)), name="uploads")

# Root endpoint serving index.html
@app.get("/")
def serve_index():
    index_file = settings.BASE_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return HTMLResponse("<h1>Dove lo AI messo</h1>")
