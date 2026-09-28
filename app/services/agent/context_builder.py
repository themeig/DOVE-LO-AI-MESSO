"""
Modulo per la costruzione dinamica del prompt di sistema e del contesto di memoria del Caveau.
"""
import json
import logging
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
from typing import Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.models.database import (
    Document,
    PhysicalItem,
    ChatThread,
    UIEvent,
    WatchedFolder,
    GoogleDriveCredential,
)
from app.services.agent.helpers import get_current_date_info, WEEKDAYS_IT, MONTHS_IT
from app.services.agent.prompts import SYSTEM_PROMPT
from app.services.drive_service import resolve_drive_folder_path

logger = logging.getLogger(__name__)


def get_recent_ui_events(db: Session, thread_id: str = "general", minutes: int = 10) -> List[UIEvent]:
    """Recupera gli ultimi eventi di telemetria UI per il thread specificato."""
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        events = (
            db.query(UIEvent)
            .filter(UIEvent.thread_id == thread_id)
            .filter(UIEvent.created_at >= cutoff)
            .order_by(UIEvent.id.desc())
            .limit(5)
            .all()
        )
        return events
    except Exception as e:
        logger.warning(f"Errore recupero eventi UI recenti: {e}")
        return []


def build_ui_telemetry_prompt_note(db: Session, thread_id: str = "general") -> Optional[str]:
    """Genera un blocco di istruzioni contestuali basate sullo stato di salute e telemetria del client."""
    events = get_recent_ui_events(db, thread_id=thread_id, minutes=10)
    if not events:
        return None

    lines = []
    for ev in events:
        doc_id = ev.target_id
        doc_title = ev.title or "Documento"
        dl_path = f"/api/documents/{doc_id}/download" if doc_id else "/api/dashboard"
        lines.append(
            f"- Evento: {ev.event_type} per '{doc_title}' (ID: {doc_id or 'N/D'}). "
            f"Dettaglio: {ev.error_details or 'Errore rendering client'}. "
            f"Link di download diretto reale: {dl_path}"
        )

    note = (
        "================================================================================\n"
        "STATO TELEMETRIA UI CLIENT IN TEMPO REALE (FEEDBACK DAL FRONTEND):\n"
        "================================================================================\n"
        "L'interfaccia client ha registrato i seguenti eventi o errori tecnici recenti:\n"
        + "\n".join(lines) + "\n\n"
        "ISTRUZIONE SULLE SCHEDE:\n"
        "- Se l'utente ti dice che non vede il pulsante o non vede la scheda, invoca SEMPRE `show_document_card` con gli ID dei documenti per mostrare le schede ufficiali interattive!\n"
        "- Mantieni sempre un tono da Concierge rassicurante, impeccabile e professionale, senza attribuire colpe o inventare anomalie dell'interfaccia."
    )
    return note


def build_system_prompt(db: Session, thread_id: str = "general") -> str:
    """Costruisce il prompt di sistema iniettando la data odierna, la memoria attiva e il contesto del Caveau (RAG)."""
    date_info = get_current_date_info()
    q_docs = db.query(Document)
    q_items = db.query(PhysicalItem)
    if thread_id and thread_id != "general" and thread_id != "all":
        q_docs = q_docs.filter(Document.thread_id == thread_id)
        q_items = q_items.filter(PhysicalItem.thread_id == thread_id)

    total_docs_count = q_docs.count()
    total_items_count = q_items.count()

    docs = q_docs.order_by(Document.id.desc()).limit(50).all()
    items = q_items.order_by(PhysicalItem.id.desc()).limit(60).all()
    unpaid = db.query(Document).filter(Document.status == "da_pagare").all()

    today = date.today()
    yesterday = today - timedelta(days=1)
    tomorrow = today + timedelta(days=1)
    yesterday_str = f"{WEEKDAYS_IT[yesterday.weekday()]} {yesterday.day} {MONTHS_IT[yesterday.month - 1]} {yesterday.year}"
    tomorrow_str = f"{WEEKDAYS_IT[tomorrow.weekday()]} {tomorrow.day} {MONTHS_IT[tomorrow.month - 1]} {tomorrow.year}"

    ground_truth_banner = f"""[GROUND TRUTH - CALENDARIO E TEMPO REALE]:
- OGGI È: {date_info['formatted_italian']} (ore {date_info['current_time']})
- DATA ISO: {date_info['date']}
- ANNO REALE ATTUALE: {date_info['year']}
- IERI ERA: {yesterday_str}
- DOMANI SARÀ: {tomorrow_str}
DIVIETO ASSOLUTO: Non sei nel 2024! Siamo nell'anno {date_info['year']}. Conosci già la data e l'ora attuale. Quando ti viene chiesta la data, l'ora, ieri o domani, rispondi SEMPRE e SOLO usando queste informazioni esatte senza MAI inventare date del passato né citare il 2024!
"""

    vault_summary = [
        f"\n[DATA E ORA ATTUALE]: {date_info['formatted_italian']}, ore {date_info['current_time']} (Data ISO: {date_info['date']}, Anno: {date_info['year']})",
        f"\n[STATO ATTUALE DEL DATABASE SQLITE]:",
        f"- Documenti archiviati nel database per questo canale: {total_docs_count}",
        f"- Oggetti fisici memorizzati nel database per questo canale: {total_items_count}",
        f"- Scadenze/bollette da pagare in sospeso: {len(unpaid)}"
    ]
    if total_docs_count == 0:
        vault_summary.append("- NOTA IMPORTANTE: Al momento ci sono 0 documenti archiviati nel database. Non inventare documenti inesistenti.")
    if total_items_count == 0:
        vault_summary.append("- NOTA IMPORTANTE: Al momento ci sono 0 oggetti fisici memorizzati nel database. Non inventare oggetti inesistenti.")

    if items:
        vault_summary.append(f"\n[INVENTARIO OGGETTI FISICI MEMORIZZATI ({len(items)})]:")
        for it in items:
            loc = it.primary_location + (f" ({it.detailed_location})" if it.detailed_location else "")
            vault_summary.append(f"- 📍 {it.item_name}: {loc}")

    if docs:
        vault_summary.append(f"\n[INVENTARIO DOCUMENTI ARCHIVIATI ({len(docs)})]:")
        for d in docs:
            amt = f" ({d.amount:.2f} €)" if d.amount is not None else ""
            due = f" [scadenza {d.due_date.strftime('%d/%m/%Y')}]" if d.due_date else ""
            vault_summary.append(f"- 📄 {d.title}{amt}{due} (stato: {d.status})")

    if unpaid:
        vault_summary.append(f"\n[PAGAMENTI/SCADENZE IN SOSPESO ({len(unpaid)})]:")
        for u in unpaid[:10]:
            amt = f"{u.amount:.2f} €" if u.amount is not None else "importo non specificato"
            due = u.due_date.strftime('%d/%m/%Y') if u.due_date else "senza data"
            vault_summary.append(f"- ⏰ {u.title}: {amt} entro {due}")

    watched_folders = db.query(WatchedFolder).all() if db else []
    if watched_folders:
        vault_summary.append(f"\n[CARTELLE PC MONITORATE ({len(watched_folders)})]:")
        for wf in watched_folders:
            vault_summary.append(f"- 📁 {wf.name}: {wf.path} ({wf.file_count} file indicizzati, ultima scansione: {wf.last_scanned_at.strftime('%d/%m/%Y %H:%M') if wf.last_scanned_at else 'Mai'})")

    # Stato Sincronizzazione Google Drive Cloud Sync
    drive_cred = db.query(GoogleDriveCredential).first() if db else None
    q_drive = db.query(Document).filter(
        or_(Document.drive_file_id.isnot(None), Document.drive_web_url.isnot(None))
    )
    if thread_id and thread_id not in ["general", "all"]:
        q_drive = q_drive.filter(Document.thread_id == thread_id)
    drive_docs = q_drive.order_by(Document.id.desc()).all() if db else []

    if drive_cred:
        if drive_cred.storage_mode == "local_only":
            mode_desc = "Solo Locale nel Caveau (i file vengono cifrati e salvati esclusivamente sul computer locale, nessun caricamento su Google Drive)"
        elif drive_cred.storage_mode == "cloud_only":
            mode_desc = "Solo Google Drive (i file fisici risiedono su Google Drive, metadati nel caveau)"
        else:
            mode_desc = "Copia locale cifrata nel caveau + Google Drive (doppia copia)"
        vault_summary.append(f"\n[STATO SINCRONIZZAZIONE GOOGLE DRIVE CLOUD SYNC]:")
        vault_summary.append(f"- Connessione: ATTIVA E COLLEGATA")
        vault_summary.append(f"- Account Google associato: {drive_cred.user_email or 'Account collegato'}")
        vault_summary.append(f"- Modalità archiviazione: {drive_cred.storage_mode} ({mode_desc})")
        vault_summary.append(f"- File totali archiviati su Google Drive per questo canale: {len(drive_docs)}")
        vault_summary.append(f"- Regola cartelle Drive: 'DoveLoAIMesso / <NomeChat> / <Categoria> / <Anno o Sottocartella> / <File>' (file organizzati e separati per ciascuna chat)")
        if drive_docs:
            vault_summary.append("  File attualmente presenti su Google Drive:")
            for dd in drive_docs[:15]:
                if getattr(dd, "drive_folder_path", None):
                    f_path = dd.drive_folder_path
                else:
                    f_parts = resolve_drive_folder_path(dd.doc_type, dd.due_date)
                    f_path = " / ".join(f_parts)
                dd_title = (dd.title or "").strip() or (Path(dd.file_path).name if dd.file_path else "") or f"Documento #{dd.id}"
                vault_summary.append(f"  * 📁 {f_path} -> 📄 {dd_title} [Drive Web URL: {dd.drive_web_url or dd.drive_file_id}]")
    else:
        vault_summary.append(f"\n[STATO SINCRONIZZAZIONE GOOGLE DRIVE CLOUD SYNC]:")
        vault_summary.append(f"- Connessione: NON COLLEGATO (l'utente può collegare il proprio account dal menu Strumenti -> Google Drive Cloud Sync)")

    vault_summary.append("\n[REGOLA SULL'USO DEI DATI DEL DATABASE]:")
    vault_summary.append("- Per conoscere, elencare o cercare documenti o oggetti, DEVI interrogare il database tramite gli appositi strumenti (`search_vault`, `list_vault_contents`, `get_upcoming_deadlines`, `scan_local_folder`, `list_watched_folders`).")
    vault_summary.append("- I dati reali restituiti dai tuoi strumenti sul database SQLite prevalgono SEMPRE e CATEGORICAMENTE su qualsiasi testo o messaggio della chat precedente.")

    thread = db.query(ChatThread).filter(ChatThread.id == thread_id).first() if db else None
    if thread:
        m_list = []
        if thread.members:
            try:
                m_list = json.loads(thread.members)
            except Exception:
                m_list = [thread.members]
        m_str = ", ".join(m_list) if m_list else "Io"
        thread_type_str = "Gruppo con altre persone" if thread.thread_type == "group" else "Area Tematica / Categoria"
        vault_summary.append(
            f"\n[CANALE CHAT ATTIVO]:\n"
            f"- Nome chat: {thread.name}\n"
            f"- Tipologia: {thread_type_str}\n"
            f"- Membri partecipanti: {m_str}\n"
            f"- Descrizione: {thread.description or 'Generale'}\n"
            f"Adatta le tue risposte e la memorizzazione sapendo che ti trovi in questo canale."
        )

    return ground_truth_banner + "\n" + SYSTEM_PROMPT + "\n" + "\n".join(vault_summary)
