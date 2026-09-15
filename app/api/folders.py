import os
from pathlib import Path
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.models.database import get_db, WatchedFolder, Document
from app.models.schemas import (
    WatchedFolderCreate,
    WatchedFolderResponse,
    FolderScanResult,
    FolderSelectResponse,
    OpenInExplorerRequest
)
from app.services.folder_service import (
    select_folder_dialog,
    open_path_in_explorer,
    scan_local_folder
)

router = APIRouter(prefix="/api/folders", tags=["folders"])

@router.post("/select", response_model=FolderSelectResponse)
def select_folder():
    """Apre la finestra di dialogo nativa per selezionare una cartella sul computer."""
    path = select_folder_dialog()
    if path:
        return FolderSelectResponse(selected_path=path, cancelled=False)
    return FolderSelectResponse(selected_path=None, cancelled=True)


@router.get("", response_model=List[WatchedFolderResponse])
@router.get("/", response_model=List[WatchedFolderResponse], include_in_schema=False)
def list_watched_folders(db: Session = Depends(get_db)):
    """Restituisce l'elenco delle cartelle monitorate sul computer."""
    folders = db.query(WatchedFolder).order_by(WatchedFolder.created_at.desc()).all()
    return [
        WatchedFolderResponse(
            id=f.id,
            path=f.path,
            name=f.name,
            thread_id=f.thread_id,
            is_active=f.is_active,
            auto_scan=f.auto_scan,
            last_scanned_at=f.last_scanned_at.isoformat() if f.last_scanned_at else None,
            file_count=f.file_count,
            created_at=f.created_at.isoformat() if f.created_at else None
        )
        for f in folders
    ]


@router.post("", response_model=WatchedFolderResponse, status_code=status.HTTP_201_CREATED)
@router.post("/", response_model=WatchedFolderResponse, status_code=status.HTTP_201_CREATED, include_in_schema=False)
def add_watched_folder(payload: WatchedFolderCreate, db: Session = Depends(get_db)):
    """Aggiunge una cartella locale al monitoraggio e la scansiona."""
    norm_path = os.path.normpath(payload.path.strip())
    p = Path(norm_path)
    if not p.exists() or not p.is_dir():
        raise HTTPException(status_code=400, detail=f"Percorso cartella '{norm_path}' non valido o inesistente.")

    # Verifica se già registrata
    existing = db.query(WatchedFolder).filter(WatchedFolder.path == norm_path).first()
    if existing:
        if payload.name:
            existing.name = payload.name
        if payload.thread_id:
            existing.thread_id = payload.thread_id
        db.commit()
        db.refresh(existing)
        if payload.auto_scan:
            scan_local_folder(norm_path, db, thread_id=existing.thread_id, watched_folder_id=existing.id)
            db.refresh(existing)
        return WatchedFolderResponse(
            id=existing.id,
            path=existing.path,
            name=existing.name,
            thread_id=existing.thread_id,
            is_active=existing.is_active,
            auto_scan=existing.auto_scan,
            last_scanned_at=existing.last_scanned_at.isoformat() if existing.last_scanned_at else None,
            file_count=existing.file_count,
            created_at=existing.created_at.isoformat() if existing.created_at else None
        )

    folder_name = payload.name.strip() if payload.name and payload.name.strip() else p.name
    folder = WatchedFolder(
        path=norm_path,
        name=folder_name,
        thread_id=payload.thread_id or "general",
        is_active=True,
        auto_scan=payload.auto_scan
    )
    db.add(folder)
    db.commit()
    db.refresh(folder)

    if payload.auto_scan:
        scan_local_folder(norm_path, db, thread_id=folder.thread_id, watched_folder_id=folder.id)
        db.refresh(folder)

    return WatchedFolderResponse(
        id=folder.id,
        path=folder.path,
        name=folder.name,
        thread_id=folder.thread_id,
        is_active=folder.is_active,
        auto_scan=folder.auto_scan,
        last_scanned_at=folder.last_scanned_at.isoformat() if folder.last_scanned_at else None,
        file_count=folder.file_count,
        created_at=folder.created_at.isoformat() if folder.created_at else None
    )


@router.post("/{folder_id}/scan", response_model=FolderScanResult)
def scan_folder(folder_id: int, db: Session = Depends(get_db)):
    """Avvia la scansione e l'indicizzazione dei file per la cartella specificata."""
    folder = db.query(WatchedFolder).filter(WatchedFolder.id == folder_id).first()
    if not folder:
        raise HTTPException(status_code=404, detail="Cartella non trovata")

    result = scan_local_folder(folder.path, db, thread_id=folder.thread_id, watched_folder_id=folder.id)
    return result


@router.delete("/{folder_id}")
def delete_watched_folder(folder_id: int, db: Session = Depends(get_db)):
    """Rimuove la cartella dal monitoraggio (non cancella i file dal disco del PC)."""
    folder = db.query(WatchedFolder).filter(WatchedFolder.id == folder_id).first()
    if not folder:
        raise HTTPException(status_code=404, detail="Cartella non trovata")

    name = folder.name
    db.delete(folder)
    db.commit()
    return {"success": True, "message": f"Cartella '{name}' rimossa dal monitoraggio."}


@router.post("/open-in-explorer")
def open_in_explorer(payload: OpenInExplorerRequest, db: Session = Depends(get_db)):
    """Apre il file o la cartella in Esplora File di Windows evidenziando il file."""
    target_path = None
    if payload.document_id:
        doc = db.query(Document).filter(Document.id == payload.document_id).first()
        if doc:
            target_path = doc.original_path or doc.file_path
    elif payload.path:
        target_path = payload.path

    if not target_path or not Path(target_path).exists():
        raise HTTPException(status_code=404, detail=f"Percorso o file non trovato sul computer: {target_path}")

    success = open_path_in_explorer(target_path)
    if not success:
        raise HTTPException(status_code=500, detail="Impossibile aprire Esplora File per questo percorso")

    return {"success": True, "path": target_path}
