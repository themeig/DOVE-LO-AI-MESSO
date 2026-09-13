import uuid
from pathlib import Path
from app.config import get_settings

def get_safe_filename(original_filename: str) -> str:
    suffix = Path(original_filename).suffix.lower() or ".bin"
    return f"{uuid.uuid4().hex}{suffix}"

def save_uploaded_file(file_bytes: bytes, original_filename: str, target_dir: Path = None) -> str:
    folder = target_dir or get_settings().STORAGE_DIR
    folder.mkdir(parents=True, exist_ok=True)
    filename = get_safe_filename(original_filename)
    dest = folder / filename
    dest.write_bytes(file_bytes)
    return str(dest)
