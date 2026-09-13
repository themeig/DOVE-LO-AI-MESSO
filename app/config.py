from pathlib import Path
from pydantic import BaseModel
import os

class Settings(BaseModel):
    BASE_DIR: Path = Path(__file__).resolve().parent.parent
    STORAGE_DIR: Path = BASE_DIR / "storage" / "uploads"
    DB_PATH: Path = BASE_DIR / "storage" / "vault.db"
    DATABASE_URL: str = f"sqlite:///{DB_PATH}"
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    DEBUG: bool = True

_settings = None

def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
        _settings.STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    return _settings
