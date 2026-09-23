import os
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.models.database import get_db, WatchedFolder, Document, PendingFileProposal
from app.models.schemas import (
    WatchedFolderCreate,
    WatchedFolderResponse,
    FolderScanResult,
    FolderSelectResponse,
    OpenInExplorerRequest,
    FolderPresetItem,
    FolderPresetsResponse,
    PendingFileProposalResponse,
    PendingProposalsListResponse,
    ApproveProposalResponse,
    DismissProposalResponse
)
from app.services.folder_service import (
    select_folder_dialog,
    open_path_in_explorer,
    scan_local_folder,
    get_system_folder_presets,
    scan_folder_for_sensitive_proposals,
    check_all_watched_folders_for_sensitive_files,
    approve_file_proposal,
    dismiss_file_proposal
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
    """Aggiunge una cartella locale al monitoraggio, scatta la baseline dei file già presenti e avvia il monitoraggio per i nuovi file."""
    norm_path = os.path.normpath(payload.path.strip())
    p = Path(norm_path)
    if not p.exists() or not p.is_dir():
        raise HTTPException(status_code=400, detail=f"Percorso cartella '{norm_path}' non valido o inesistente.")

    # Raccogli tutti i file attualmente presenti al momento dell'attivazione per impostare la baseline
    baseline_files = []
    try:
        for f in p.iterdir():
            if f.is_file():
                baseline_files.append(os.path.normpath(str(f.resolve())))
    except Exception:
        pass

    now_utc = datetime.now(timezone.utc)

    # Verifica se già registrata
    existing = db.query(WatchedFolder).filter(WatchedFolder.path == norm_path).first()
    if existing:
        if payload.name:
            existing.name = payload.name
        if payload.thread_id:
            existing.thread_id = payload.thread_id
        if not existing.baseline_files_json:
            existing.baseline_files_json = json.dumps(baseline_files)
            existing.monitoring_started_at = now_utc
            existing.file_count = len(baseline_files)
        db.commit()
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
        auto_scan=payload.auto_scan,
        file_count=len(baseline_files),
        baseline_files_json=json.dumps(baseline_files),
        monitoring_started_at=now_utc,
        created_at=now_utc
    )
    db.add(folder)
    db.commit()
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
    """Apre il file o la cartella in Esplora File di Windows evidenziando il file decifrato."""
    from app.services.folder_service import prepare_document_for_local_open

    target_path = None
    if payload.document_id:
        doc = db.query(Document).filter(Document.id == payload.document_id).first()
        if not doc:
            raise HTTPException(status_code=404, detail="Documento non trovato nel caveau")
        try:
            target_path = prepare_document_for_local_open(doc)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Errore decifratura per apertura locale: {e}")
    elif payload.path:
        target_path = payload.path

    if not target_path or not Path(target_path).exists():
        raise HTTPException(status_code=404, detail=f"Percorso o file non trovato sul computer: {target_path}")

    success = open_path_in_explorer(target_path, open_file=True)
    if not success:
        raise HTTPException(status_code=500, detail="Impossibile aprire Esplora File per questo percorso")

    return {"success": True, "path": target_path}


@router.get("/presets", response_model=FolderPresetsResponse)
def get_folder_presets(db: Session = Depends(get_db)):
    """Restituisce le cartelle predefinite di sistema (Download, Documenti, Desktop)."""
    presets = get_system_folder_presets(db)
    return FolderPresetsResponse(
        presets=[
            FolderPresetItem(
                key=p["key"],
                name=p["name"],
                path=p["path"],
                exists=p["exists"],
                is_watched=p["is_watched"],
                icon=p["icon"]
            )
            for p in presets
        ]
    )


@router.get("/proposals", response_model=PendingProposalsListResponse)
def list_proposals(status: str = "pending", db: Session = Depends(get_db)):
    """Restituisce le proposte di file sensibili rilevati dalle cartelle monitorate."""
    query = db.query(PendingFileProposal)
    if status != "all":
        query = query.filter(PendingFileProposal.status == status)
    proposals = query.order_by(PendingFileProposal.detected_at.desc()).all()

    return PendingProposalsListResponse(
        proposals=[
            PendingFileProposalResponse(
                id=p.id,
                folder_id=p.folder_id,
                folder_name=p.folder_name,
                file_path=p.file_path,
                file_name=p.file_name,
                file_size=p.file_size,
                doc_type=p.doc_type,
                issuer=p.issuer,
                amount=p.amount,
                due_date=p.due_date.isoformat() if p.due_date else None,
                sensitivity_reason=p.sensitivity_reason,
                summary=p.summary,
                status=p.status,
                thread_id=p.thread_id,
                detected_at=p.detected_at.isoformat() if p.detected_at else None
            )
            for p in proposals
        ],
        count=len(proposals)
    )


@router.post("/proposals/{proposal_id}/approve", response_model=ApproveProposalResponse)
def approve_proposal(proposal_id: int, db: Session = Depends(get_db)):
    """Approva il salvataggio cifrato nel caveau e l'indicizzazione del file sensibile."""
    success, msg, doc = approve_file_proposal(proposal_id, db)
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    return ApproveProposalResponse(
        success=True,
        message=msg,
        document_id=doc.id if doc else None,
        title=doc.title if doc else None
    )


@router.post("/proposals/{proposal_id}/dismiss", response_model=DismissProposalResponse)
def dismiss_proposal(proposal_id: int, db: Session = Depends(get_db)):
    """Rifiuta la proposta di salvataggio del file sensibile."""
    success, msg = dismiss_file_proposal(proposal_id, db)
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    return DismissProposalResponse(
        success=True,
        message=msg,
        proposal_id=proposal_id
    )


@router.post("/scan-sensitive")
def scan_all_sensitive_files(db: Session = Depends(get_db)):
    """Avvia la scansione manuale di tutte le cartelle monitorate per rilevare nuovi file sensibili."""
    proposals = check_all_watched_folders_for_sensitive_files(db, auto_notify=True)
    return {
        "success": True,
        "new_proposals_count": len(proposals),
        "proposals": [
            {
                "id": p.id,
                "file_name": p.file_name,
                "folder_name": p.folder_name,
                "reason": p.sensitivity_reason
            }
            for p in proposals
        ]
    }

