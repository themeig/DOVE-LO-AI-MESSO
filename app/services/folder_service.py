import os
import sys
import subprocess
import logging
from pathlib import Path
from datetime import datetime, timezone
import json
from typing import Optional, List, Dict, Any, Tuple
from sqlalchemy.orm import Session

from app.models.database import Document, WatchedFolder, PendingFileProposal, ChatMessage
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


IGNORED_EXTENSIONS = {
    ".tmp", ".crdownload", ".part", ".download", ".exe", ".msi", ".dmg", ".pkg",
    ".log", ".ini", ".sys", ".dll", ".bin", ".iso", ".torrent", ".bak", ".swp"
}

SENSITIVE_KEYWORDS = [
    "bolletta", "fattura", "f24", "tribut", "estratto_conto", "estratto conto",
    "stipendio", "busta_paga", "busta paga", "cud", "730", "saldo", "ricevuta",
    "contratto", "passaporto", "carta_identita", "carta identita", "cie",
    "tessera_sanitaria", "tessera sanitaria", "iban", "bonifico", "quietanza",
    "referto", "multa", "canone", "fiscale", "spese", "modello unico", "inps",
    "agenzia entrate", "agenzia delle entrate"
]

SENSITIVE_DOC_TYPES = {
    "bolletta", "f24", "fattura", "tributo", "avviso", "ricevuta",
    "contratto", "stipendio", "sanitario", "bancario", "identita",
    "tasse", "legale", "certificato"
}


def get_system_folder_presets(db: Optional[Session] = None) -> List[Dict[str, Any]]:
    """
    Restituisce le cartelle preimpostate di sistema (es. Download, Documenti, Desktop)
    con lo stato attuale di monitoraggio.
    """
    home = Path.home()
    presets_def = [
        {"key": "downloads", "name": "Cartella Download", "path": str(home / "Downloads"), "icon": "📥"},
        {"key": "documents", "name": "Documenti", "path": str(home / "Documents"), "icon": "📁"},
        {"key": "desktop", "name": "Desktop", "path": str(home / "Desktop"), "icon": "🖥️"},
    ]

    watched_paths = set()
    if db:
        folders = db.query(WatchedFolder).all()
        for f in folders:
            if f.path:
                watched_paths.add(os.path.normpath(f.path).lower())

    results = []
    for item in presets_def:
        p = Path(item["path"])
        norm_p = os.path.normpath(str(p.resolve())).lower() if p.exists() else os.path.normpath(item["path"]).lower()
        results.append({
            "key": item["key"],
            "name": item["name"],
            "path": str(p),
            "exists": p.exists(),
            "is_watched": norm_p in watched_paths,
            "icon": item["icon"]
        })
    return results


def is_sensitive_file(file_path: Path) -> Tuple[bool, str, Optional[Any]]:
    """
    Analizza un file per verificare se contiene dati sensibili (bollette, F24, fatture, contratti, scadenze, ecc.)
    Restituisce (is_sensitive, reason, extracted_document).
    """
    ext = file_path.suffix.lower()
    if ext in IGNORED_EXTENSIONS:
        return False, "", None
    if ext not in SUPPORTED_EXTENSIONS and ext not in [".docx", ".xlsx", ".csv"]:
        return False, "", None

    # Se il file supera i 30MB, evitiamo l'analisi pesante per sicurezza
    try:
        if file_path.stat().st_size > 30 * 1024 * 1024:
            return False, "", None
    except Exception:
        return False, "", None

    fn_lower = file_path.name.lower()
    has_keyword = any(k in fn_lower for k in SENSITIVE_KEYWORDS)

    ai_service = get_ai_service()
    try:
        file_bytes = file_path.read_bytes()
        mime_type = "application/pdf" if ext == ".pdf" else (
            f"image/{ext.lstrip('.')}" if ext in [".png", ".jpg", ".jpeg", ".webp"] else "application/octet-stream"
        )
        extracted = ai_service.extract_document(
            file_bytes=file_bytes,
            mime_type=mime_type,
            filename=file_path.name
        )
    except Exception as e:
        logger.warning(f"Impossibile analizzare il file {file_path}: {e}")
        if has_keyword:
            return True, f"Rilevato file sensibile in base al nome: {file_path.name}", None
        return False, "", None

    # Verifica criteri di sensitività
    is_sensitive = False
    reason_parts = []

    if extracted.amount is not None:
        is_sensitive = True
        reason_parts.append(f"Importo rilevato: {extracted.amount:.2f}€")

    if extracted.due_date is not None:
        is_sensitive = True
        reason_parts.append(f"Scadenza individuata: {extracted.due_date}")

    if extracted.doc_type in SENSITIVE_DOC_TYPES:
        is_sensitive = True
        reason_parts.append(f"Tipologia sensibile: {extracted.doc_type.capitalize()}")

    if has_keyword and not is_sensitive:
        is_sensitive = True
        reason_parts.append(f"Nome del file rilevante: {file_path.name}")

    if is_sensitive:
        if extracted.issuer:
            reason_parts.append(f"Emittente: {extracted.issuer}")
        reason = " | ".join(reason_parts) if reason_parts else f"Documento personale/fiscale ({extracted.doc_type})"
        return True, reason, extracted

    return False, "", extracted


def scan_folder_for_sensitive_proposals(
    folder_path: str,
    db: Session,
    folder_id: Optional[int] = None,
    folder_name: Optional[str] = None,
    thread_id: str = "general",
    auto_notify: bool = True
) -> List[PendingFileProposal]:
    """
    Scansiona una cartella alla ricerca di nuovi file sensibili.
    I file che erano già presenti nella cartella al momento della registrazione o prima dell'avvio
    vengono ignorati e non analizzati dall'AI.
    """
    p = Path(folder_path)
    if not p.exists() or not p.is_dir():
        return []

    norm_folder = os.path.normpath(str(p.resolve()))
    fname = folder_name or p.name

    # Recupera la cartella monitorata se registrata
    watched = None
    if folder_id:
        watched = db.query(WatchedFolder).filter(WatchedFolder.id == folder_id).first()
    if not watched:
        watched = db.query(WatchedFolder).filter(
            (WatchedFolder.path == norm_folder) | (WatchedFolder.path == folder_path)
        ).first()

    baseline_set = set()
    started_ts = None
    if watched:
        if watched.baseline_files_json:
            try:
                baseline_set = set(json.loads(watched.baseline_files_json))
            except Exception:
                baseline_set = set()

        start_time = watched.monitoring_started_at or watched.created_at
        if start_time:
            started_ts = start_time.timestamp()

    new_proposals = []
    total_files_in_dir = 0
    try:
        for f in p.iterdir():
            if not f.is_file():
                continue
            total_files_in_dir += 1
            if f.suffix.lower() in IGNORED_EXTENSIONS:
                continue

            norm_file = os.path.normpath(str(f.resolve()))

            # 0. ESCLUSIONE FILE PRE-ESISTENTI:
            # I file che erano già presenti nella cartella prima del monitoraggio NON vengono analizzati.
            if norm_file in baseline_set:
                continue

            if started_ts is not None:
                try:
                    st = f.stat()
                    file_time = max(st.st_mtime, getattr(st, "st_ctime", 0))
                    # Se il file è antecedente all'inizio del monitoraggio, ignoralo
                    if file_time < (started_ts - 0.5):
                        continue
                except Exception:
                    continue

            # 1. Controlla se già proposto in passato (anche se risolto o archiviato)
            existing_proposal = db.query(PendingFileProposal).filter(
                PendingFileProposal.file_path == norm_file
            ).first()
            if existing_proposal:
                continue

            # 2. Controlla se già indicizzato come Document
            existing_doc = db.query(Document).filter(
                (Document.original_path == norm_file) |
                (Document.file_path == norm_file)
            ).first()
            if existing_doc:
                continue

            # 3. Analizza sensitività
            is_sens, reason, extracted = is_sensitive_file(f)
            if not is_sens:
                continue

            # Data di scadenza
            due_date_obj = None
            if extracted and extracted.due_date:
                try:
                    due_date_obj = datetime.strptime(extracted.due_date, "%Y-%m-%d").date()
                except ValueError:
                    due_date_obj = None

            amount_val = extracted.amount if extracted else None
            doc_type_val = extracted.doc_type if extracted else "generico"
            issuer_val = extracted.issuer if extracted else None
            summary_val = (extracted.summary if extracted else "") or f"File rilevato in {fname}"

            proposal = PendingFileProposal(
                folder_id=folder_id,
                folder_name=fname,
                file_path=norm_file,
                file_name=f.name,
                file_size=f.stat().st_size,
                doc_type=doc_type_val,
                issuer=issuer_val,
                amount=amount_val,
                due_date=due_date_obj,
                sensitivity_reason=reason,
                summary=summary_val,
                status="pending",
                thread_id=thread_id,
                detected_at=datetime.now(timezone.utc)
            )
            db.add(proposal)
            db.flush()
            new_proposals.append(proposal)

            if auto_notify:
                # Invia messaggio proattivo nella chat con metadata per pulsanti interattivi
                chat_msg = ChatMessage(
                    thread_id=thread_id,
                    sender="assistant",
                    message_type="sensitive_proposal",
                    content=(
                        f"🛡️ **Rilevato nuovo file sensibile** in `{fname}`:\n\n"
                        f"📄 **{proposal.file_name}**\n"
                        f"_{reason}_\n\n"
                        f"Vuoi che lo protegga salvandolo cifrato nel Caveau e lo indicizzi nello scadenzario?"
                    ),
                    metadata_json=json.dumps({
                        "action": "SENSITIVE_FILE_PROPOSAL",
                        "proposal_id": proposal.id,
                        "proposal": {
                            "id": proposal.id,
                            "file_name": proposal.file_name,
                            "folder_name": proposal.folder_name,
                            "file_size": proposal.file_size,
                            "doc_type": proposal.doc_type,
                            "issuer": proposal.issuer,
                            "amount": proposal.amount,
                            "due_date": proposal.due_date.isoformat() if proposal.due_date else None,
                            "sensitivity_reason": reason,
                            "summary": proposal.summary,
                            "status": "pending"
                        }
                    })
                )
                db.add(chat_msg)

        if watched:
            watched.file_count = total_files_in_dir
            watched.last_scanned_at = datetime.now(timezone.utc)

        db.commit()
    except Exception as e:
        logger.error(f"Errore scansione file sensibili per {folder_path}: {e}")
        db.rollback()

    return new_proposals


def check_all_watched_folders_for_sensitive_files(
    db: Session,
    auto_notify: bool = True
) -> List[PendingFileProposal]:
    """
    Esegue un controllo periodico o manuale su tutte le cartelle monitorate attive.
    """
    watched_folders = db.query(WatchedFolder).filter(WatchedFolder.is_active == True).all()
    all_new = []
    for wf in watched_folders:
        try:
            props = scan_folder_for_sensitive_proposals(
                folder_path=wf.path,
                db=db,
                folder_id=wf.id,
                folder_name=wf.name,
                thread_id=wf.thread_id,
                auto_notify=auto_notify
            )
            all_new.extend(props)
        except Exception as err:
            logger.error(f"Errore controllo cartella {wf.path}: {err}")
    return all_new


def approve_file_proposal(proposal_id: int, db: Session) -> Tuple[bool, str, Optional[Document]]:
    """
    Approva una proposta: legge il file dal disco locale, lo cifra con AES-256
    e lo salva nel Caveau, creando la voce Document e aggiornando la proposta.
    """
    proposal = db.query(PendingFileProposal).filter(PendingFileProposal.id == proposal_id).first()
    if not proposal:
        return False, "Proposta non trovata.", None
    if proposal.status != "pending":
        return False, f"Proposta già elaborata ({proposal.status}).", None

    src = Path(proposal.file_path)
    if not src.exists() or not src.is_file():
        proposal.status = "dismissed"
        proposal.resolved_at = datetime.now(timezone.utc)
        db.commit()
        return False, "Il file originale non è più presente sul disco.", None

    try:
        from app.services.document_service import save_uploaded_file
        file_bytes = src.read_bytes()
        # Salva file cifrato con AES-256 nel Caveau
        vault_path = save_uploaded_file(file_bytes, proposal.file_name)

        ext = src.suffix.lstrip(".").lower()
        is_payable = (proposal.amount is not None) and (proposal.doc_type in ["bolletta", "f24", "fattura", "tributo", "avviso"])
        doc_status = "da_pagare" if is_payable else "archiviato"

        title = f"{proposal.doc_type.capitalize()} {proposal.issuer}".strip() if proposal.issuer else proposal.file_name

        doc = Document(
            thread_id=proposal.thread_id,
            title=title,
            file_path=vault_path,
            file_type=ext,
            doc_type=proposal.doc_type,
            issuer=proposal.issuer,
            amount=proposal.amount,
            due_date=proposal.due_date,
            status=doc_status,
            summary=proposal.summary or f"File importato e cifrato nel Caveau da '{proposal.folder_name}'",
            is_local_file=False,
            original_path=proposal.file_path
        )
        db.add(doc)
        db.flush()

        proposal.status = "approved"
        proposal.resolved_at = datetime.now(timezone.utc)

        # Aggiunge notifica di conferma in chat
        chat_msg = ChatMessage(
            thread_id=proposal.thread_id,
            sender="assistant",
            message_type="text",
            content=(
                f"🔒 **Documento salvato e protetto nel Caveau!**\n\n"
                f"📄 **{proposal.file_name}** è stato cifrato con chiave AES-256 e archiviato nel Caveau (ID #{doc.id})."
                + (f"\n📅 Scadenza impostata per il **{proposal.due_date.strftime('%d/%m/%Y')}** ({proposal.amount:.2f}€)." if proposal.due_date else "")
            ),
            metadata_json=json.dumps({
                "action": "PROPOSAL_APPROVED",
                "proposal_id": proposal.id,
                "document_id": doc.id
            })
        )
        db.add(chat_msg)
        db.commit()
        db.refresh(doc)
        return True, "File salvato nel Caveau e indicizzato con successo.", doc
    except Exception as e:
        logger.error(f"Errore approvazione proposta {proposal_id}: {e}")
        db.rollback()
        return False, f"Errore durante il salvataggio nel Caveau: {str(e)}", None


def dismiss_file_proposal(proposal_id: int, db: Session) -> Tuple[bool, str]:
    """
    Rifiuta/ignora una proposta di file sensibile in modo che non venga più riproposta.
    """
    proposal = db.query(PendingFileProposal).filter(PendingFileProposal.id == proposal_id).first()
    if not proposal:
        return False, "Proposta non trovata."
    if proposal.status != "pending":
        return False, f"Proposta già elaborata ({proposal.status})."

    proposal.status = "dismissed"
    proposal.resolved_at = datetime.now(timezone.utc)
    db.commit()
    return True, "Proposta ignorata. Il file non verrà più segnalato."
