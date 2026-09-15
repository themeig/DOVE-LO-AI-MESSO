import os
import sys
import subprocess
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session

from app.models.database import Document, WatchedFolder
from app.models.schemas import FolderScanResult
from app.services.ai_service import get_ai_service

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff"}

def select_folder_dialog(initial_dir: Optional[str] = None) -> Optional[str]:
    """
    Apre la finestra nativa di dialogo per la selezione di una cartella sul computer.
    Utilizza Tkinter in modalità headless/senza finestra principale.
    """
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        folder = filedialog.askdirectory(
            initialdir=initial_dir or str(Path.home()),
            title="Seleziona la cartella del tuo computer da monitorare"
        )
        root.destroy()
        if folder:
            return os.path.normpath(folder)
        return None
    except Exception as e:
        logger.error(f"Errore durante l'apertura della finestra di dialogo: {e}")
        return None


def open_path_in_explorer(target_path: str) -> bool:
    """
    Apre il percorso specificato in Esplora Risorse di Windows (o gestore file di sistema).
    Se è un file, lo evidenzia (/select). Se è una cartella, la apre.
    """
    p = Path(target_path)
    if not p.exists():
        logger.warning(f"Percorso non trovato: {target_path}")
        return False

    norm_path = os.path.normpath(str(p.resolve()))
    try:
        if sys.platform == "win32" or os.name == "nt":
            if p.is_file():
                subprocess.Popen(["explorer.exe", f"/select,{norm_path}"])
            else:
                os.startfile(norm_path)
            return True
        elif sys.platform == "darwin":
            if p.is_file():
                subprocess.Popen(["open", "-R", norm_path])
            else:
                subprocess.Popen(["open", norm_path])
            return True
        else:
            # Linux fallback
            subprocess.Popen(["xdg-open", norm_path if p.is_dir() else str(p.parent)])
            return True
    except Exception as e:
        logger.error(f"Errore durante l'apertura del percorso {target_path}: {e}")
        return False


def scan_local_folder(
    folder_path: str,
    db: Session,
    thread_id: str = "general",
    recursive: bool = True,
    watched_folder_id: Optional[int] = None
) -> FolderScanResult:
    """
    Esegue la scansione di una cartella del PC, estrae i dati tramite AI e indicizza
    tutti i nuovi documenti PDF e immagini nel database senza duplicare i file.
    """
    p = Path(folder_path)
    if not p.exists() or not p.is_dir():
        return FolderScanResult(
            folder_id=watched_folder_id,
            folder_path=folder_path,
            scanned_files_count=0,
            new_indexed_count=0,
            skipped_count=0,
            error_count=1,
            details=[f"Cartella '{folder_path}' inesistente o non valida."]
        )

    ai_service = get_ai_service()
    details = []
    scanned_count = 0
    new_count = 0
    skipped_count = 0
    error_count = 0

    # 1. Trova tutti i file supportati
    pattern = "**/*" if recursive else "*"
    candidate_files = []
    try:
        for f in p.glob(pattern):
            if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS:
                candidate_files.append(f)
    except Exception as e:
        logger.error(f"Errore scansione directory {folder_path}: {e}")
        return FolderScanResult(
            folder_id=watched_folder_id,
            folder_path=folder_path,
            scanned_files_count=0,
            new_indexed_count=0,
            skipped_count=0,
            error_count=1,
            details=[f"Errore lettura cartella: {str(e)}"]
        )

    scanned_count = len(candidate_files)

    # 2. Processa ciascun file
    for file_path in candidate_files:
        norm_file_str = os.path.normpath(str(file_path.resolve()))
        # Verifica se già indicizzato (confronta percorsi normalizzati)
        existing = (
            db.query(Document)
            .filter(
                (Document.file_path == norm_file_str) |
                (Document.original_path == norm_file_str) |
                (Document.file_path == str(file_path)) |
                (Document.original_path == str(file_path))
            )
            .first()
        )
        if existing:
            skipped_count += 1
            continue

        # Nuovo file: leggi byte ed estrai
        try:
            file_bytes = file_path.read_bytes()
            ext = file_path.suffix.lstrip(".").lower()
            mime_type = "application/pdf" if ext == "pdf" else f"image/{ext}"

            extracted = ai_service.extract_document(
                file_bytes=file_bytes,
                mime_type=mime_type,
                filename=file_path.name
            )

            # Parse data di scadenza
            due_date_obj = None
            if extracted.due_date:
                try:
                    due_date_obj = datetime.strptime(extracted.due_date, "%Y-%m-%d").date()
                except ValueError:
                    due_date_obj = None

            # Titolo
            title = (extracted.title or "").strip()
            if not title:
                if extracted.issuer:
                    title = f"{extracted.doc_type.capitalize()} {extracted.issuer}".strip()
                else:
                    clean_stem = file_path.stem.replace("_", " ").replace("-", " ").strip()
                    title = f"Foto {clean_stem}" if ext in ["jpg", "jpeg", "png", "webp"] else (clean_stem or file_path.name)

            is_payable = (extracted.amount is not None) and (extracted.doc_type in ["bolletta", "f24", "fattura", "tributo", "avviso"])
            doc_status = "da_pagare" if is_payable else "archiviato"

            doc = Document(
                thread_id=thread_id,
                title=title,
                file_path=norm_file_str,
                file_type=ext,
                doc_type=extracted.doc_type,
                issuer=extracted.issuer,
                amount=extracted.amount,
                due_date=due_date_obj,
                status=doc_status,
                summary=extracted.summary or f"File indicizzato dalla cartella locale: {p.name}",
                is_local_file=True,
                original_path=norm_file_str
            )
            db.add(doc)
            new_count += 1
            details.append(f"Indicizzato: {file_path.name} -> '{title}' ({doc_status})")
        except Exception as err:
            logger.error(f"Errore indicizzazione file {file_path}: {err}")
            error_count += 1
            details.append(f"Errore su {file_path.name}: {str(err)}")

    # 3. Aggiorna o crea WatchedFolder
    db.flush()
    norm_folder_str = os.path.normpath(str(p.resolve()))
    watched = None
    if watched_folder_id:
        watched = db.query(WatchedFolder).filter(WatchedFolder.id == watched_folder_id).first()
    if not watched:
        watched = db.query(WatchedFolder).filter(
            (WatchedFolder.path == norm_folder_str) | (WatchedFolder.path == folder_path)
        ).first()

    if watched:
        watched.last_scanned_at = datetime.now(timezone.utc)
        # Calcola numero totale di documenti associati a questa cartella (in modo sicuro per i percorsi Windows)
        all_docs = db.query(Document).all()
        norm_folder_lower = norm_folder_str.lower()
        total_in_folder = sum(
            1 for d in all_docs
            if (d.original_path and os.path.normpath(d.original_path).lower().startswith(norm_folder_lower))
            or (d.file_path and os.path.normpath(d.file_path).lower().startswith(norm_folder_lower))
        )
        watched.file_count = total_in_folder

    db.commit()

    return FolderScanResult(
        folder_id=watched.id if watched else watched_folder_id,
        folder_path=norm_folder_str,
        scanned_files_count=scanned_count,
        new_indexed_count=new_count,
        skipped_count=skipped_count,
        error_count=error_count,
        details=details
    )
