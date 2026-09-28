"""
Modulo Orchestrator per l'Agente Conversazionale Intelligente del Caveau (AgenticChatService).
"""
import json
import logging
import re
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
import httpx
from typing import Optional, Dict, Any, List
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.config import get_settings
from app.models.database import (
    Document,
    PhysicalItem,
    ChatMessage,
    ChatThread,
    get_app_setting,
    UIEvent,
    WatchedFolder,
    GoogleDriveCredential,
)
from app.models.schemas import ChatResponse
from app.services.ai_service import get_ai_service, MockAIService
from app.services.drive_service import resolve_drive_folder_path, sanitize_drive_folder_name
from app.services.search_service import (
    search_vault_documents,
    search_vault_items,
    ITALIAN_STOPWORDS,
    GENERIC_ATTRIBUTE_TERMS,
    it_stem,
    token_matches,
)
from app.services.agent.helpers import (
    WEEKDAYS_IT,
    MONTHS_IT,
    get_current_date_info,
    categorize_deadline,
    is_tool_payload,
    strip_tool_tags,
    filter_relevant_documents,
    extract_rename_title,
    extract_item_and_location,
    extract_bulk_delete_target,
    extract_link_photo_item,
)
from app.services.agent.tools_spec import TOOLS_DEFINITION
from app.services.agent.prompts import SYSTEM_PROMPT
from app.services.agent.context_builder import (
    get_recent_ui_events,
    build_ui_telemetry_prompt_note,
    build_system_prompt,
)
from app.services.agent.tools_executor import execute_vault_tool

logger = logging.getLogger(__name__)

class AgenticChatService:
    def __init__(self):
        self.settings = get_settings()

    def get_recent_ui_events(self, db: Session, thread_id: str = "general", minutes: int = 10) -> List[UIEvent]:
        """Recupera gli ultimi eventi di telemetria UI per il thread specificato."""
        return get_recent_ui_events(db, thread_id=thread_id, minutes=minutes)

    def _build_ui_telemetry_prompt_note(self, db: Session, thread_id: str = "general") -> Optional[str]:
        """Genera un blocco di istruzioni contestuali basate sullo stato di salute e telemetria del client."""
        return build_ui_telemetry_prompt_note(db, thread_id=thread_id)

    def _extract_rename_title(self, text: str) -> Optional[str]:
        """Estrae il nuovo titolo da espressioni naturali dell'utente per rinominare documenti o foto."""
        return extract_rename_title(text)

    def _extract_item_and_location(self, text: str, last_item_in_context: Optional[str] = None) -> tuple[Optional[str], Optional[str]]:
        """Estrae con precisione il nome dell'oggetto e la posizione (per salvataggio, modifica, spostamento)."""
        return extract_item_and_location(text, last_item_in_context)

    def _extract_bulk_delete_target(self, text: str) -> tuple[bool, Optional[str]]:
        """Determina se la cancellazione multipla richiesta è un azzeramento totale del caveau o specifica."""
        return extract_bulk_delete_target(text)

    def _extract_link_photo_item(self, text: str) -> Optional[str]:
        """Estrae il nome dell'oggetto fisico a cui associare una foto/documento."""
        return extract_link_photo_item(text)

    def execute_tool(self, name: str, args: Dict[str, Any], db: Session, thread_id: str = "general") -> Dict[str, Any]:
        """Esegue uno strumento registrato contro il database SQLite locale delegando al tools_executor."""
        return execute_vault_tool(name=name, args=args, db=db, thread_id=thread_id)

    def build_system_prompt(self, db: Session, thread_id: str = "general") -> str:
        """Costruisce il prompt di sistema iniettando la data odierna, la memoria attiva e il contesto del Caveau."""
        return build_system_prompt(db=db, thread_id=thread_id)

    def _handle_temporal_intent(self, user_text: str, lower_t: str) -> Optional[ChatResponse]:
        """Risponde istantaneamente e con certezza matematica alle domande sulla data e l'ora attuale, ieri o domani."""
        # Se la domanda riguarda scadenze o documenti specifici, lascia che proceda con i tool di ricerca
        if any(k in lower_t for k in ["scadenz", "da pagare", "bollett", "f24", "document", "cosa scade"]):
            return None

        # Normalizza accenti uniti (es. "giornoè" -> "giorno è", "dataè" -> "data è", "oraè" -> "ora è")
        normalized = re.sub(r"([a-z])(è|e'|é)", r"\1 \2", lower_t)
        clean = re.sub(r"[?!.,;]", " ", normalized)
        clean = re.sub(r"\s+", " ", clean).strip()

        # 1. Domani
        is_tomorrow = any(k in clean for k in ["domani", "prossimo giorno"]) and any(k in clean for k in ["che giorno", "che data", "quanti ne abbiamo", "sarà", "sara", "quando è", "quando e"])
        if is_tomorrow or clean in [
            "domani che giorno è", "domani che giorno e", "che giorno è domani", "che giorno e domani",
            "che giorno sara domani", "che giorno sarà domani", "domani che data è", "domani che data e",
            "domani quanti ne abbiamo"
        ]:
            tomorrow = date.today() + timedelta(days=1)
            weekday = WEEKDAYS_IT[tomorrow.weekday()]
            month = MONTHS_IT[tomorrow.month - 1]
            formatted = f"{weekday} {tomorrow.day} {month} {tomorrow.year}"
            return ChatResponse(
                reply=f"📅 Domani sarà **{formatted}**.",
                action="get_current_date",
                data={"date": tomorrow.isoformat(), "formatted_italian": formatted, "target": "tomorrow"}
            )

        # 2. Ieri
        is_yesterday = any(k in clean for k in ["ieri", "giorno prima"]) and any(k in clean for k in ["che giorno", "che data", "quanti ne avevamo", "era", "quando era"])
        if is_yesterday or clean in [
            "ieri che giorno era", "che giorno era ieri", "ieri che data era", "ieri quanti ne avevamo",
            "che data era ieri"
        ]:
            yesterday = date.today() - timedelta(days=1)
            weekday = WEEKDAYS_IT[yesterday.weekday()]
            month = MONTHS_IT[yesterday.month - 1]
            formatted = f"{weekday} {yesterday.day} {month} {yesterday.year}"
            return ChatResponse(
                reply=f"📅 Ieri era **{formatted}**.",
                action="get_current_date",
                data={"date": yesterday.isoformat(), "formatted_italian": formatted, "target": "yesterday"}
            )

        # 3. Oggi / Data attuale / Giorno attuale / Ora attuale
        is_today = (
            any(k in clean for k in [
                "che giorno è", "che giorno e", "che data è", "che data e",
                "data di oggi", "data odierna", "quanti ne abbiamo", "giorno odierno",
                "che ore sono", "ora attuale", "ora esatta", "orario attuale",
                "dimmi che giorno è", "dimmi che giorno e", "dimmi la data", "dimmi l'ora"
            ])
            or clean in [
                "che giorno è", "che giorno e", "che data è", "che data e", "data oggi",
                "quanti ne abbiamo oggi", "quanti ne abbiamo", "che ora è", "che ora e",
                "oggi che giorno è", "oggi che giorno e", "oggi"
            ]
        )
        if is_today:
            d_info = get_current_date_info()
            return ChatResponse(
                reply=f"📅 Oggi è **{d_info['formatted_italian']}** (ore {d_info['current_time']}).",
                action="get_current_date",
                data=d_info
            )

        return None

    def _handle_listing_intent(self, user_text: str, lower_t: str, db: Session, thread_id: str = "general") -> Optional[ChatResponse]:
        """Restituisce l'elenco reale, veritiero e aggiornato dei documenti presenti nel database, eliminando allucinazioni."""
        is_deletion = any(k in lower_t for k in [
            "elimina", "cancella", "rimuovi", "butta", "eliminami", "cancellami", "svuota", "eliminali", "cancellali", "rimuovili"
        ])
        if is_deletion:
            return None

        clean = re.sub(r"[?!.,;]", " ", lower_t)
        clean = re.sub(r"\s+", " ", clean).strip()

        is_listing = (
            any(k in clean for k in [
                "fai la lista", "fammi la lista", "fai una lista", "fai prima la lista",
                "elenca tutti", "elencami tutti", "elenca i documenti", "elencami i documenti",
                "elenco documenti", "elenco dei documenti", "lista documenti", "lista dei documenti",
                "quali documenti hai", "quali documenti ci sono", "cosa hai nel caveau",
                "cosa c'è nel caveau", "cosa ce nel caveau", "mostrami tutti i documenti",
                "mostra tutti i documenti", "vedere tutti i documenti", "cosa hai archiviato",
                "cosa c'è di archiviato", "tutti i documenti che hai"
            ])
            or clean in ["documenti", "i miei documenti", "tutti i documenti", "elenco", "lista"]
        )
        if not is_listing:
            return None

        query = db.query(Document)
        if thread_id and thread_id != "general" and thread_id != "all":
            query = query.filter(Document.thread_id == thread_id)
        docs = query.order_by(Document.id.desc()).all()

        if not docs:
            return ChatResponse(
                reply="Nel caveau non sono presenti documenti archiviati al momento.",
                action="list_documents",
                data={"count": 0, "documents": []}
            )

        lines = []
        doc_items = []
        for d in docs:
            amt = f" - {d.amount:.2f} €" if d.amount is not None else ""
            due = f" - Scadenza: {d.due_date.strftime('%d/%m/%Y')}" if d.due_date else ""
            iss = f" ({d.issuer}{amt}{due})" if (d.issuer or amt or due) else ""
            lines.append(f"- 📄 **{d.title}**{iss}")
            fn = Path(d.file_path).name if d.file_path else ""
            doc_items.append({
                "document_id": d.id,
                "title": d.title,
                "issuer": d.issuer,
                "amount": d.amount,
                "due_date": d.due_date.isoformat() if d.due_date else None,
                "summary": d.summary,
                "file_url": f"/uploads/{fn}" if fn else None,
                "download_url": f"/api/documents/{d.id}/download",
                "file_type": d.file_type
            })

        reply = f"Certo! Ecco l'elenco completo dei **{len(docs)} documenti** attualmente presenti nel caveau:\n\n" + "\n".join(lines)
        return ChatResponse(
            reply=reply,
            action="list_documents",
            data={"count": len(docs), "documents": doc_items},
            documents=doc_items[:5]
        )

    def _handle_deletion_intent(self, user_text: str, lower_t: str, db: Session, thread_id: str = "general") -> Optional[ChatResponse]:
        """Gestisce in modo sicuro le richieste di eliminazione (singola o multipla/totale) chiedendo conferma prima di qualsiasi azione."""
        is_deletion = any(re.search(rf"\b{re.escape(k)}\b", lower_t) for k in [
            "elimina", "cancella", "rimuovi", "eliminarlo", "cancellarlo", 
            "rimuoverlo", "butta", "cancellami", "eliminami", "eliminali", "cancellali", "rimuovili"
        ])
        if not is_deletion:
            return None

        # Escludi frasi negative, domande meta o riferimenti a quotazioni
        if any(re.search(rf"\b{re.escape(k)}\b", lower_t) for k in [
            "non eliminare", "non cancellare", "senza eliminare", "senza cancellare",
            "sto quotando", "quotando un messaggio", "ti ricordi", "questo messaggio", "a questo messaggio"
        ]):
            return None

        clean_prompt = re.sub(r"[?!.,;]", " ", lower_t)
        clean_prompt = re.sub(r"\s+", " ", clean_prompt).strip()

        # 1. Rileva eliminazione multipla o totale
        is_bulk = (
            any(k in clean_prompt for k in [
                "elimina tutti", "elimina tutte", "cancella tutti", "cancella tutte",
                "rimuovi tutti", "rimuovi tutte", "svuota", "elimina tutto", "cancella tutto",
                "eliminali tutti", "cancellali tutti", "rimuovili tutti", "elimina ogni"
            ])
            or clean_prompt in ["eliminali", "cancellali", "rimuovili", "elimina tutto", "cancella tutto", "elimina tutti", "cancella tutti"]
        )

        if is_bulk:
            query = db.query(Document)
            if thread_id and thread_id != "general" and thread_id != "all":
                query = query.filter(Document.thread_id == thread_id)

            is_total, target_kw = self._extract_bulk_delete_target(clean_prompt)
            if not is_total and target_kw:
                s_matches = search_vault_documents(db, target_kw, thread_id=thread_id)
                matched_ids = [m["id"] for m in s_matches]
                stem_kw = it_stem(target_kw)
                like_matches = query.filter(or_(
                    Document.title.ilike(f"%{target_kw}%"),
                    Document.doc_type.ilike(f"%{target_kw}%"),
                    Document.issuer.ilike(f"%{target_kw}%"),
                    Document.summary.ilike(f"%{target_kw}%"),
                    Document.title.ilike(f"%{stem_kw}%"),
                    Document.doc_type.ilike(f"%{stem_kw}%"),
                    Document.summary.ilike(f"%{stem_kw}%")
                )).all()
                for lm in like_matches:
                    if lm.id not in matched_ids:
                        matched_ids.append(lm.id)

                if not matched_ids:
                    return ChatResponse(
                        reply=f"Non ho trovato documenti corrispondenti a '{target_kw}' nel caveau da eliminare.",
                        action="REPLY"
                    )
                query = query.filter(Document.id.in_(matched_ids))
                cat_name = f"documenti corrispondenti a '{target_kw}'"
            else:
                cat_name = "tutti i documenti"

            docs_to_delete = query.all()
            if not docs_to_delete:
                return ChatResponse(
                    reply=f"Non ho trovato documenti da eliminare nel caveau ({cat_name}).",
                    action="REPLY"
                )

            doc_ids = [d.id for d in docs_to_delete]
            doc_titles = [d.title for d in docs_to_delete]

            conf = {
                "type": "delete_confirmation",
                "target_type": "bulk_documents",
                "target_id": doc_ids[0],
                "target_ids": doc_ids,
                "title": f"TUTTI i {len(doc_ids)} documenti ({cat_name})" if (is_total and len(doc_ids) > 1) else (f"I {len(doc_ids)} {cat_name}" if len(doc_ids) > 1 else doc_titles[0]),
                "details": f"Verranno eliminati definitivamente {len(doc_ids)} file dal caveau."
            }

            list_preview = "\n".join([f"- 📄 **{t}**" for t in doc_titles[:6]])
            if len(doc_titles) > 6:
                list_preview += f"\n- ... e altri {len(doc_titles) - 6} documenti"

            return ChatResponse(
                reply=f"⚠️ Stai per eliminare definitivamente **{len(doc_ids)} documenti** ({cat_name}):\n\n{list_preview}\n\nSei sicuro di voler procedere?",
                action="REQUEST_DELETE",
                data={"target_type": "bulk_documents", "document_ids": doc_ids},
                confirmation=conf,
                documents=[{
                    "document_id": d.id,
                    "title": d.title,
                    "issuer": d.issuer,
                    "amount": d.amount,
                    "due_date": d.due_date.isoformat() if d.due_date else None,
                    "summary": d.summary,
                    "file_url": f"/uploads/{Path(d.file_path).name}" if d.file_path else None,
                    "download_url": f"/api/documents/{d.id}/download",
                    "file_type": d.file_type
                } for d in docs_to_delete[:4]]
            )

        # 2. Eliminazione di un singolo documento o oggetto specifico
        target_query = re.sub(
            r"^(?:per favore|puoi|vorrei|potresti|ti prego di|elimina|cancella|rimuovi|cancellami|eliminami|butta)\s*(?:il|la|lo|le|i|l'|un|una|uno)?\s*",
            "", lower_t
        ).strip(" ?.")
        target_query = re.sub(
            r"^(?:documenti\s+delle|documenti\s+dei|documenti\s+di|documenti\s+del|documenti|documento\s+delle|documento\s+del|documento\s+di|documento|file\s+delle|file\s+di|file\s+del|file)\s*",
            "", target_query
        ).strip(" ?.")
        target_query = re.sub(r"\s*(?:per favore|per cortesia|grazie|per piacere)$", "", target_query).strip()
        target_query = re.sub(r"\s*(?:dal caveau|dall'archivio|dal database|dalla memoria|dal sistema)$", "", target_query).strip()

        if not target_query or len(target_query) < 2:
            target_query = user_text

        search_res = self.execute_tool("search_vault", {"query": target_query}, db, thread_id=thread_id)
        f_docs = search_res.get("found_documents", [])
        f_items = search_res.get("found_physical_items", [])

        prefers_doc = any(k in lower_t for k in ["document", "file", "bollett", "f24", "certificat", "ricevut", "fattur", "pdf"])
        prefers_item = any(k in lower_t for k in ["oggett", "posizion", "posto", "chiav", "passaport", "patente"])

        chosen_doc = None
        chosen_item = None

        if prefers_doc and f_docs:
            chosen_doc = f_docs[0]
        elif prefers_item and f_items:
            chosen_item = f_items[0]
        elif f_docs and not f_items:
            chosen_doc = f_docs[0]
        elif f_items and not f_docs:
            chosen_item = f_items[0]
        elif f_docs and f_items:
            chosen_doc = f_docs[0] if not prefers_item else None
            chosen_item = f_items[0] if prefers_item else None

        if chosen_doc:
            conf = {
                "type": "delete_confirmation",
                "target_type": "document",
                "target_id": chosen_doc["document_id"],
                "title": chosen_doc["title"],
                "details": chosen_doc.get("summary") or chosen_doc.get("issuer")
            }
            return ChatResponse(
                reply=f"⚠️ Ho trovato il documento **{chosen_doc['title']}** ({chosen_doc.get('issuer', 'Documento')}).\nSei sicuro di volerlo eliminare dal caveau?",
                action="REQUEST_DELETE",
                data={"target_type": "document", "target_id": chosen_doc["document_id"]},
                confirmation=conf,
                documents=[chosen_doc]
            )
        elif chosen_item:
            loc_str = chosen_item["primary_location"] + (f" ({chosen_item['detailed_location']})" if chosen_item.get("detailed_location") else "")
            conf = {
                "type": "delete_confirmation",
                "target_type": "physical_item",
                "target_id": chosen_item["item_id"],
                "title": chosen_item["item_name"],
                "details": f"Posizione: {loc_str}"
            }
            return ChatResponse(
                reply=f"⚠️ Ho trovato l'oggetto **{chosen_item['item_name']}** (registrato in: {loc_str}).\nSei sicuro di voler eliminare questa posizione dal caveau?",
                action="REQUEST_DELETE",
                data={"target_type": "physical_item", "target_id": chosen_item["item_id"]},
                confirmation=conf
            )
        else:
            return None

    def _handle_drive_intent(self, user_text: str, lower_t: str, db: Session, thread_id: str = "general") -> Optional[ChatResponse]:
        """Intercetta e risponde in modo deterministico nei test offline alle domande generali sull'integrazione Google Drive."""
        is_specific_doc_search = any(k in lower_t for k in [
            "polizza", "bollett", "fattur", "f24", "730", "patente", "passaporto", "carta",
            "ricevut", "scontrino", "contratt", "certificat", "mutuo", "multa", "verbale"
        ])
        if is_specific_doc_search:
            return None

        has_drive_mention = any(k in lower_t for k in ["google drive", "su drive", "in drive", "mio drive", "tuo drive", "nostro drive"]) or (
            "drive" in lower_t and any(k in lower_t for k in ["cartell", "salvat", "organizzat", "cosa", "dove", "file", "stato", "sincronizz", "come hai", "come funziona", "spiegami"])
        )
        if not has_drive_mention:
            return None

        status_data = self.execute_tool("get_google_drive_status", {}, db=db, thread_id=thread_id)
        if not status_data.get("connected"):
            return ChatResponse(
                reply=(
                    "☁️ **Google Drive non è attualmente collegato.**\n\n"
                    "L'integrazione con Google Drive Cloud Sync è pronta e funzionante: puoi collegare il tuo account Google in qualsiasi momento "
                    "aprendo il menu **Strumenti $\to$ ☁️ Google Drive Cloud Sync** e cliccando su **'Collega Google Drive'**."
                ),
                action="get_google_drive_status",
                data=status_data
            )

        email = status_data.get("user_email") or "Account collegato"
        mode = status_data.get("storage_mode", "dual")
        if mode == "local_only":
            mode_label = "**Solo Locale nel Caveau** (i file vengono cifrati e salvati esclusivamente sul tuo computer locale, nessun caricamento su Google Drive)"
        elif mode == "cloud_only":
            mode_label = "**Solo Google Drive** (i file fisici risiedono unicamente sul cloud Google Drive, nessun file memorizzato sul disco locale)"
        else:
            mode_label = "**Copia locale cifrata nel caveau + Google Drive** (doppio salvataggio sicuro)"
        total_files = status_data.get("total_files_on_drive", 0)
        folders_overview = status_data.get("folders_overview") or {}
        matching_files = status_data.get("matching_files") or []

        folder_explanation = (
            "📂 **Come organizzo le cartelle su Google Drive**:\n"
            "Tutti i tuoi file vengono archiviati in modo strutturato dentro la cartella principale **`DoveLoAIMesso`** sul tuo Google Drive:\n"
            "• **Documenti con scadenza**: `DoveLoAIMesso / <Anno> / <Categoria> / <File>` (es. `DoveLoAIMesso/2026/Bollette & Utenze/...`)\n"
            "• **Documenti senza scadenza**: `DoveLoAIMesso / <Categoria> / <File>` (es. `DoveLoAIMesso/Documenti & Foto/...`)\n\n"
            "Le categorie automatiche create sono:\n"
            "- ⚡ *Bollette & Utenze* (luce, gas, acqua)\n"
            "- 🏛️ *Fisco & Tasse* (modelli F24, tributi, tasse)\n"
            "- 💳 *Fatture & Spese* (fatture d'acquisto, scontrini, ricevute)\n"
            "- 📑 *Contratti & Polizze* (contratti d'affitto, polizze assicurative)\n"
            "- 📁 *Documenti & Foto* (credenziali, file generici, foto personali)"
        )

        if total_files == 0:
            files_explanation = "📄 **File attualmente archiviati su Google Drive**: Al momento non ci sono file sincronizzati. Non appena carichi un file qui nella chat (📎 o 📷), lo caricherò automaticamente nella sua cartella dedicata su Drive!"
        else:
            files_lines = []
            for f_path, f_titles in folders_overview.items():
                files_lines.append(f"• 📁 **{f_path}**:")
                for t in f_titles:
                    files_lines.append(f"  - 📄 {t}")
            files_explanation = f"📄 **File attualmente archiviati su Google Drive ({total_files} file)**:\n" + "\n".join(files_lines)

        reply_text = (
            f"☁️ **Google Drive Cloud Sync è attivo e collegato** all'account **`{email}`**!\n\n"
            f"⚙️ **Modalità di archiviazione attiva**: {mode_label}.\n\n"
            f"{folder_explanation}\n\n"
            f"{files_explanation}\n\n"
            "💡 *Puoi aprire direttamente qualsiasi file su Google Drive cliccando sul pulsante **[Drive ↗]** presente sulla scheda del documento qui sotto!*"
        )

        return ChatResponse(
            reply=reply_text,
            action="get_google_drive_status",
            data=status_data,
            documents=matching_files[:5]
        )

    def resolve_agent_model(self, user_text: str, lower_t: str, configured_model: str, has_audio: bool = False) -> str:
        """
        Risolve dinamicamente il modello da utilizzare:
        - Se configured_model != 'auto', rispetta la scelta manuale dell'utente.
        - Se configured_model == 'auto':
            - Se è presente audio vocale multimodale -> 'google/gemini-2.5-pro' (comprensione audio nativa via API)
            - Se l'intento è di immagazzinamento/salvataggio/caricamento rapido:
                -> 'google/gemini-2.5-flash-lite'
            - Se l'intento è di ricerca, calcolo, scadenze, domande complesse o spiegazioni:
                -> 'google/gemini-2.5-pro'
            - Default per richieste generiche: 'google/gemini-2.5-pro' (massima intelligenza)
        """
        cfg = (configured_model or "").strip()
        if not cfg:
            cfg = "auto"

        if cfg != "auto":
            return cfg

        if has_audio:
            return "google/gemini-2.5-pro"

        # 1. Ricerche, calcoli, scadenze, domande e spiegazioni -> PRO (Thinking Process)
        search_calc_patterns = [
            "dov'è", "dov'e", "dove è", "dove sono", "dove si trova", "dove ho messo", "dove sta", "dove ",
            "cerca", "trova", "trovami", "mostrami", "fammi vedere",
            "scadenz", "bollett", "fattur", "polizz", "mutuo", "assicuraz",
            "quanto", "quant'è", "quant'e", "somma", "totale", "calcola", "spesa", "spese",
            "spiega", "spiegami", "chiarisci", "cosa copre", "cosa c'è", "cosa ce", "cosa contiene",
            "come funziona", "dimmi", "elenca", "quali", "?"
        ]
        is_search_or_reasoning = any(p in lower_t for p in search_calc_patterns)

        # 2. Immagazzinamento rapido / posizioni / allegati foto -> FLASH LITE
        storage_patterns = [
            "ho messo", "ho riposto", "ho posato", "ho infilato", "ho lasciato", "ho salvato",
            "salva", "salvami", "memorizza", "memorizzami", "registra",
            "riponi", "posiziona", "sposta", "spostato", "aggiorna la posizione",
            "ti allego", "allego foto", "ecco la foto", "foto per", "foto della",
            "messo nel", "messa nel", "messo in", "messa in", "messo sulla", "messo sullo"
        ]
        is_storage = any(p in lower_t for p in storage_patterns)

        if is_storage and not is_search_or_reasoning:
            return "google/gemini-2.5-flash-lite"

        if is_search_or_reasoning:
            return "google/gemini-2.5-pro"

        pos_preps = [" nel ", " nello ", " nella ", " nei ", " negli ", " nelle ", " sul ", " sullo ", " sulla ", " in "]
        if any(prep in lower_t for prep in pos_preps) and not is_search_or_reasoning:
            return "google/gemini-2.5-flash-lite"

        return "google/gemini-2.5-pro"

    def run_turn(
        self,
        user_text: str,
        db: Session,
        thread_id: str = "general",
        quoted_message: Optional[dict] = None,
        audio_base64: Optional[str] = None,
        audio_format: Optional[str] = "wav"
    ) -> ChatResponse:
        """Esegue un turno conversazionale applicando la risoluzione del modello tramite Router Intelligente."""
        lower_t = (user_text or "").lower()
        configured_model = get_app_setting(db, "ai_model", default=self.settings.OPENROUTER_MODEL) or "auto"
        effective_model = self.resolve_agent_model(user_text, lower_t, configured_model, has_audio=bool(audio_base64))

        resp = self._run_turn_impl(
            user_text=user_text,
            db=db,
            thread_id=thread_id,
            quoted_message=quoted_message,
            audio_base64=audio_base64,
            audio_format=audio_format,
            effective_model=effective_model
        )

        if resp:
            resp.routed_model = effective_model
            if resp.data is None:
                resp.data = {"routed_model": effective_model}
            elif isinstance(resp.data, dict) and "routed_model" not in resp.data:
                resp.data["routed_model"] = effective_model

        return resp

    def _run_turn_impl(
        self,
        user_text: str,
        db: Session,
        thread_id: str = "general",
        quoted_message: Optional[dict] = None,
        audio_base64: Optional[str] = None,
        audio_format: Optional[str] = "wav",
        effective_model: Optional[str] = None
    ) -> ChatResponse:
        """Esegue l'elaborazione interna di un turno conversazionale con tool-calling dell'agente."""
        lower_t = (user_text or "").lower()

        # Se il testo utente è letteralmente solo il placeholder vocale SENZA audio allegato
        clean_user_voice = re.sub(r"[🎤\s]+", "", lower_t)
        if not audio_base64 and clean_user_voice in ["messaggiovocale", "vocale"]:
            return ChatResponse(
                reply="🎤 Non ho rilevato alcun comando vocale comprensibile in questo messaggio. Prova a ripetere registrando con il microfono o a scrivermi nella chat!",
                action="REPLY"
            )

        # Rileva ultimo oggetto citato nel thread per eventuale risoluzione pronomi (es. "mettila in...")
        last_item_name = None
        last_asst_msg = (
            db.query(ChatMessage)
            .filter(ChatMessage.thread_id == thread_id, ChatMessage.sender == "assistant")
            .order_by(ChatMessage.id.desc())
            .first()
        )
        if last_asst_msg and last_asst_msg.content:
            m_it = re.search(r"\*\*(.+?)\*\*", last_asst_msg.content)
            if m_it:
                last_item_name = m_it.group(1).strip()

        # Rileva intenzione di memorizzazione, modifica o spostamento posizione fisica
        is_store_or_update = (
            any(re.search(rf"\b{re.escape(k)}\b", lower_t) for k in [
                "messo", "riposto", "salvato", "lasciato", "conservato", "posizionato", "sistemato",
                "modifica la posizione", "cambia la posizione", "aggiorna la posizione",
                "sposta", "spostato", "spostata", "spostare",
                "mettilo", "mettila", "mettili", "mettile", "metti",
                "ora è in", "ora si trova in", "adesso è in", "adesso si trova in"
            ])
            and not any(re.search(rf"\b{re.escape(k)}\b", lower_t) for k in ["dov'è", "dov'e", "dove ho", "dove si trova", "dove sono", "dove sta", "dove è", "dove"])
            and not any(re.search(rf"\b{re.escape(k)}\b", lower_t) for k in ["ti ricordi", "ti ricordi di", "ti ricordi questo", "ricordi", "sto quotando"])
        )

        is_cards_request = any(k in lower_t for k in [
            "non vedo le schede", "non vedo la scheda", "non vedo i documenti", "non vedo il documento",
            "non vedo le card", "non vedo la card", "non le vedo", "non li vedo", "non la vedo", "non lo vedo",
            "non vedo", "dove sono le schede", "non ci sono le schede", "non si vedono le schede",
            "mancano le schede", "mostra le schede", "mostrami le schede", "fammi vedere le schede",
            "fammeli vedere", "fammela vedere", "fammeli scaricare", "fammi scaricare",
            "rimandami le schede", "riapri le schede", "mostrale", "mostrali", "mostrameli", "mostramela", "mostramelo"
        ])

        is_where_request = (
            any(k in lower_t for k in [
                "dov'è", "dov'e", "dove è", "dove sono", "dove si trova", "dove si trovano",
                "dove ho messo", "dove ho riposto", "dove ho lasciato", "dove sta", "dove stanno",
                "dove trovo"
            ])
            and not is_store_or_update
            and not is_cards_request
        )

        is_listing_request = (
            any(k in lower_t for k in [
                "lista", "elenco", "elencami", "quali documenti", "quali oggetti",
                "mostrami tutti", "mostrami tutte", "mostra tutti", "mostra tutte",
                "cosa c'è nel caveau", "cosa ce nel caveau", "cosa ho nel caveau", "cosa hai nel caveau",
                "vedere tutti", "vedere tutte", "tutti i documenti", "tutti gli oggetti", "che oggetti", "che documenti"
            ])
            or lower_t.strip(" !.?") in ["documenti", "oggetti", "tutti i documenti", "tutti gli oggetti", "tutto", "i miei documenti", "i miei oggetti"]
        )
        # Rileva se la richiesta menziona un documento o entità specifica (es. patente, garanzia, persona)
        has_specific_subject = any(k in lower_t for k in [
            "patente", "garanzia", "iphone", "apple", "carta", "passaporto", "contratto", "polizza",
            "assicurazione", "visura", "certificato", "tessera", "730", "f24", "mutuo", "multa", "verbale",
            "mario", "rossi", "andrea", "conti", "hera", "enel", "eni", "amazon", "scontrino",
            "della ", "del ", "dell'", "dei ", "delle ", "di ", "per "
        ]) or any(k in lower_t for k in ["rinnovo", "rinnovare", "valida fino", "validità", "fino a quando"])

        is_deadline_request = (
            any(k in lower_t for k in [
                "scadenz", "da pagare", "bollette da pagare", "tributi da pagare",
                "cosa devo pagare", "quanto devo pagare", "prossime scadenze", "scadenze in sospeso"
            ])
            and not is_listing_request
            and not is_store_or_update
            and not has_specific_subject
        )

        is_rename_request = (
            any(k in lower_t for k in [
                "chiamalo", "chiamala", "rinominalo", "rinominala", "rinomina",
                "salvalo come", "salvala come", "dagli il nome", "dalle il nome", "dai il nome", "dagli come nome", "dalle come nome"
            ])
            and not is_store_or_update
            and not is_where_request
        )

        # Rileva intenzione di collegare foto ad oggetto fisico (es. "ti allego una foto per il piano", "ecco la foto delle chiavi")
        linked_photo_item = self._extract_link_photo_item(user_text)
        is_link_photo_intent = bool(linked_photo_item)

        is_download_or_show = (
            (
                any(k in lower_t for k in [
                    "scarica", "scaricarla", "scaricarlo", "scaricalo", "scaricala", "scaricarli", "scaricali", "scaricare",
                    "download", "fare il download", "voglio scaricare", "voglio il download", "voglio fare il download",
                    "apri il documento", "apri il file", "mostramelo", "mostramela", "mostrameli",
                    "fammi vedere il file", "fammi vedere il documento", "voglio vederlo", "voglio vederla", "voglio vederli",
                    "apri il pdf", "mostra la scheda", "vedi il documento", "mandami il pdf"
                ])
                or is_cards_request
            )
            and not is_store_or_update
            and not is_where_request
            and not is_link_photo_intent
        )

        is_delete_request = any(re.search(rf"\b{re.escape(k)}\b", lower_t) for k in [
            "elimina", "cancella", "rimuovi", "butta", "eliminami", "cancellami", "svuota", "eliminali", "cancellali", "rimuovili"
        ]) and not any(re.search(rf"\b{re.escape(k)}\b", lower_t) for k in [
            "non eliminare", "non cancellare", "senza eliminare", "senza cancellare", "sto quotando", "quotando un messaggio", "ti ricordi", "questo messaggio"
        ])

        is_doc_search_request = (
            any(k in lower_t for k in [
                "document", "file", "bollett", "fattur", "contratt", "certificat", "ricevut",
                "cedolin", "busta paga", "patente", "passaporto", "carta", "f24", "730", "estratto",
                "identit", "identificazion", "mutuo", "visura", "tessera", "tasse", "tribut",
                "garanzia", "iphone", "scontrino", "multa", "verbale", "polizza", "polizze", "assicurazion"
            ])
            and (
                any(k in lower_t for k in [
                    "dammi", "mostra", "mostrami", "cerca", "trova", "trovami", "apri", "vedi", "prendi",
                    "fammi vedere", "visualizza", "voglio", "scarica",
                    "quando scade", "data di scadenza", "scadenza di", "scadenza del", "scadenza della", "scadenza dell",
                    "rinnovo", "rinnovare", "valida fino", "fino a quando", "quanto ho pagato", "quanti"
                ])
                or has_specific_subject
            )
            and not is_where_request
            and not is_store_or_update
            and not is_listing_request
            and not is_delete_request
            and not is_link_photo_intent
        ) or (
            lower_t.strip(" !.?") in [
                "documenti di identità", "documenti di identita", "documenti personali",
                "documenti identità", "documenti identita", "tessera sanitaria", "ricevute", "bollette",
                "i documenti di identità", "i documenti di identita", "documenti"
            ]
        )

        is_content_inspect_request = (
            any(k in lower_t for k in [
                "foglio excel", "file excel", "foglio di calcolo", "riga ", "righe", "colonna ", "colonne",
                "cella ", "celle", "tabella", "leggi il file", "leggi il foglio", "leggimi il file",
                "cosa c'è nel file", "cosa ce nel file", "cosa c'è nel foglio", "cosa ce nel foglio",
                "cosa contiene il file", "cosa contiene il foglio", "dati del foglio", "dati di excel",
                ".xlsx", ".xls", ".csv"
            ]) or (any(k in lower_t for k in ["riga", "colonna", "cella", "importo", "fatturato", "valore"]) and any(k in lower_t for k in ["excel", "xlsx", "xls", "tabella", "foglio"]))
        ) and not is_delete_request and not is_rename_request

        is_unzip_request = any(k in lower_t for k in [
            "scompatta", "scompattami", "scompattalo", "scompattare",
            "decomprimi", "decomprimimi", "decomprimilo", "decomprimere",
            "unzip", "fai l'unzip", "fai unzip",
            "estrai lo zip", "estrai l'archivio", "estrai archivio", "estrai i file dallo zip", "estrai tutti i file dallo zip"
        ])

        stored_item_result = None

        # Se non c'è chiave API, fallback deterministico per test offline
        if not self.settings.OPENROUTER_API_KEY:
            # Fallback deterministico per messaggi vocali nei test offline
            if audio_base64 and (not user_text or user_text.strip() in ["🎤 Messaggio vocale", "Messaggio vocale", "🎤", ""]):
                return ChatResponse(
                    reply="🎤 Ho ricevuto il tuo messaggio vocale. (Modalità offline/test: per consentire al modello Gemini Pro di ascoltare ed eseguire la richiesta via API, configura la chiave OpenRouter).",
                    action="REPLY"
                )

            # Fallback deterministico per richieste temporali nei test offline
            temp_resp = self._handle_temporal_intent(user_text, lower_t)
            if temp_resp:
                return temp_resp

            # Fallback deterministico per richieste di eliminazione nei test offline
            del_resp = self._handle_deletion_intent(user_text, lower_t, db, thread_id=thread_id)
            if del_resp:
                return del_resp

            # Fallback deterministico per richieste di estrazione ZIP nei test offline
            if is_unzip_request:
                from app.services.archive_service import unzip_document_to_vault
                m_id = re.search(r"\b(?:id\s*[:=]?\s*|numero\s+)?(\d+)\b", lower_t)
                target_id = int(m_id.group(1)) if m_id else None
                m_name = re.search(r"[\"']([a-zA-Z0-9_\-.]+\.zip)[\"']", lower_t)
                target_name = m_name.group(1) if m_name else None

                extracted = unzip_document_to_vault(
                    db=db,
                    document_id=target_id,
                    document_title=target_name,
                    thread_id=thread_id
                )
                if extracted:
                    doc_lines = []
                    for idx, d in enumerate(extracted, 1):
                        details = []
                        if d.category_label:
                            details.append(f"📁 *{d.category_label}*")
                        elif d.doc_type:
                            details.append(f"*{d.doc_type.capitalize()}*")
                        if d.amount is not None:
                            details.append(f"💶 **€ {d.amount:.2f}**")
                        if d.due_date:
                            details.append(f"📅 Scadenza: **{d.due_date.strftime('%d/%m/%Y')}**")
                        detail_str = f" ({' • '.join(details)})" if details else ""
                        summary_line = f"\n   _{d.summary}_" if d.summary else ""
                        doc_lines.append(f"**{idx}.** 📄 **{d.title}**{detail_str}{summary_line}")

                    reply = (
                        f"📦 Ho scompattato con successo l'archivio ed esaminato ciascun file singolarmente con l'AI. "
                        f"Ecco il dettaglio dei **{len(extracted)} documenti** estratti e catalogati nel Caveau:\n\n"
                        + "\n\n".join(doc_lines) +
                        "\n\nHo inserito ciascun documento nella sezione corrispondente e aggiornato lo scadenzario. Puoi aprirli, visualizzarli o scaricarli direttamente dalle schede qui sotto! ⬇️"
                    )
                    docs_info = [
                        {
                            "id": d.id,
                            "document_id": d.id,
                            "title": d.title,
                            "issuer": d.issuer,
                            "doc_type": d.doc_type,
                            "category": d.category,
                            "category_label": d.category_label,
                            "category_icon": d.category_icon,
                            "amount": d.amount,
                            "due_date": d.due_date.isoformat() if d.due_date else None,
                            "status": d.status,
                            "summary": d.summary,
                            "file_url": f"/uploads/{Path(d.file_path).name}" if d.file_path else None,
                            "download_url": f"/api/documents/{d.id}/download",
                            "file_type": d.file_type
                        }
                        for d in extracted
                    ]
                    return ChatResponse(
                        reply=reply,
                        action="show_document_card",
                        data={"extracted_count": len(extracted), "documents": docs_info},
                        documents=docs_info
                    )
                else:
                    return ChatResponse(
                        reply="⚠️ Non ho trovato alcun archivio ZIP nel caveau da decomprimere, oppure l'archivio non contiene file validi. Puoi caricare un file .zip con l'icona della graffetta 📎 in basso!",
                        action="unzip_vault_archive",
                        data={"success": False}
                    )

            # Fallback deterministico per risposte affermative e selezioni nei test offline
            is_listing_phrase = any(k in lower_t for k in [
                "lista", "elenco", "elencami", "quali documenti", "quali oggetti",
                "cosa c'è", "cosa ce", "cosa ho", "cosa hai", "che documenti", "che oggetti"
            ])

            is_download_intent = any(k in lower_t for k in [
                "download", "scarica", "scaricarla", "scaricarlo", "scaricalo", "scaricala", "scaricarli", "scaricali", "scaricare",
                "fare il download", "voglio scaricare", "voglio il download", "voglio fare il download", "scaricale", "scaricali"
            ])
            is_multi_select = (
                lower_t.strip(" !.?") in [
                    "entrambi", "entrambe", "tutti", "tutte", "tutti e due", "tutte e due", "tutti quanti",
                    "si di entrambi", "sì di entrambi", "si entrambi", "sì entrambi", "tutti e 2", "tutte e 2",
                    "scaricali", "scaricale", "scaricali entrambi", "scarica entrambi", "scaricali tutti", "scarica tutti",
                    "scarica tutte", "scaricale tutte", "mostrali tutti", "mostrameli tutti", "mostrale tutte", "mostramele tutte",
                    "apri entrambi", "apri tutti", "visualizzali entrambi", "visualizzali tutti", "vedili entrambi", "vedili tutti"
                ]
                or any(k in lower_t for k in [
                    "entrambi", "entrambe", "tutti e due", "tutte e due", "tutti e 2", "tutte e 2",
                    "mostrameli tutti", "mostrali tutti", "mostrale tutte", "mostramele tutte",
                    "scarica tutti", "scarica tutte", "scarica entrambi", "scaricali entrambi", "scaricali tutti", "scaricale tutte",
                    "scaricali", "scaricale", "si di entrambi", "sì di entrambi", "apri entrambi", "visualizzali entrambi"
                ])
            ) and not is_listing_phrase

            is_affirmative = (
                lower_t.strip(" !.?") in [
                    "si", "sì", "ok", "va bene", "certo", "mostramelo", "mostramela", "mostrameli", "mostrali", "mostrale",
                    "fammi vedere", "apri", "yes", "vai", "entrambi", "entrambe", "tutti e due", "tutte e due",
                    "si di entrambi", "sì di entrambi", "si entrambi", "sì entrambi", "tutti", "tutte",
                    "scaricali", "scaricale", "scaricalo", "scaricala", "scarica", "download", "apri entrambi", "mostrali tutti"
                ]
                or is_multi_select
                or (is_download_intent and len(lower_t.split()) <= 6)
            ) and not is_listing_phrase
            if is_affirmative:
                last_asst = (
                    db.query(ChatMessage)
                    .filter(ChatMessage.thread_id == thread_id, ChatMessage.sender == "assistant")
                    .order_by(ChatMessage.id.desc())
                    .first()
                )
                if last_asst and last_asst.content:
                    all_docs = db.query(Document).order_by(Document.created_at.desc()).all()
                    matched_docs = []

                    # 1. Trova documenti il cui titolo compare direttamente nel testo del messaggio precedente
                    for d in all_docs:
                        if d.title and len(d.title) >= 3 and d.title.lower() in last_asst.content.lower():
                            if d not in matched_docs:
                                matched_docs.append(d)

                    # 2. Cerca nomi esplicitamente citati tra virgolette, grassetto o punti elenco (* 📄 Titolo)
                    cand_names = (
                        re.findall(r"['\"]([^'\"]{2,})['\"]", last_asst.content) +
                        re.findall(r"\*\*([^*]{2,})\*\*", last_asst.content) +
                        re.findall(r"[*•-]\s*(?:📄\s*)?([^\n:]+?)(?:\s*:|\s*—|\s*\(|$)", last_asst.content)
                    )

                    for cand in cand_names:
                        c_clean = cand.strip(" *📄\"'")
                        if c_clean and len(c_clean) >= 3:
                            s_matches = search_vault_documents(db, c_clean, thread_id=thread_id)
                            if s_matches:
                                top_d = db.query(Document).filter(Document.id == s_matches[0]["id"]).first()
                                if top_d and top_d not in matched_docs:
                                    matched_docs.append(top_d)
                            for d in all_docs:
                                if d.title and (d.title.lower() == c_clean.lower() or c_clean.lower() in d.title.lower() or d.title.lower() in c_clean.lower()):
                                    if d not in matched_docs:
                                        matched_docs.append(d)

                    # 3. Se non trovati per titolo intero, controlla sovrapposizione parole chiave
                    if not matched_docs:
                        for d in all_docs:
                            d_words = [w for w in re.split(r"[^\w]+", d.title.lower()) if len(w) > 3 and w not in ITALIAN_STOPWORDS]
                            if d_words and sum(1 for w in d_words if w in last_asst.content.lower()) >= max(1, len(d_words) * 0.5):
                                if d not in matched_docs:
                                    matched_docs.append(d)

                    # 4. Controlla se fa riferimento a un oggetto fisico
                    matched_item = None
                    if not matched_docs:
                        all_items = db.query(PhysicalItem).order_by(PhysicalItem.updated_at.desc()).all()
                        for it in all_items:
                            if it.item_name and len(it.item_name) >= 3 and it.item_name.lower() in last_asst.content.lower():
                                matched_item = it
                                break
                        if not matched_item and cand_names:
                            for cand in cand_names:
                                c_clean = cand.strip(" *📄\"'")
                                for it in all_items:
                                    if it.item_name and (it.item_name.lower() == c_clean.lower() or c_clean.lower() in it.item_name.lower()):
                                        matched_item = it
                                        break

                    # Se ci sono documenti trovati:
                    if matched_docs:
                        # Se l'utente non ha chiesto 'entrambi' o 'tutti' e ha specificato parole di uno solo:
                        specific_doc = None
                        if not is_multi_select and not any(k in lower_t for k in ["entrambi", "tutti", "tutte", "scaricali", "scaricale", "mostrali", "mostrameli"]):
                            for d in matched_docs:
                                d_words = [w for w in re.split(r"[^\w]+", d.title.lower()) if len(w) > 2 and w not in ITALIAN_STOPWORDS]
                                if any(w in lower_t for w in d_words):
                                    specific_doc = d
                                    break

                        docs_to_show = [specific_doc] if specific_doc else matched_docs
                        doc_ids_to_call = [d.id for d in docs_to_show]
                        card_res = self.execute_tool("show_document_card", {"document_ids": doc_ids_to_call}, db=db, thread_id=thread_id)
                        docs_info = card_res.get("documents") or []
                        if docs_info:
                            if len(docs_info) > 1:
                                lines = [f"- 📄 **{d['title']}** ({d.get('issuer') or d.get('doc_type', '')})" for d in docs_info]
                                reply_text = (
                                    f"📄 Certamente! Ecco le schede per i {len(docs_info)} documenti:\n\n" +
                                    "\n".join(lines) +
                                    "\n\nPuoi visualizzarli con il pulsante 'Vedi' o scaricarli direttamente con il pulsante 'Scarica' nelle rispettive schede qui sotto! ⬇️"
                                )
                            else:
                                d = docs_info[0]
                                reply_text = f"📄 Eccolo! Ho recuperato il documento **{d['title']}** ({d.get('issuer') or d.get('doc_type', '')}):\n💡 {d.get('summary', '')}"

                            return ChatResponse(
                                reply=reply_text,
                                action="show_document_card",
                                data=card_res,
                                documents=docs_info
                            )

                    elif matched_item:
                        loc_str = matched_item.primary_location + (f" ({matched_item.detailed_location})" if matched_item.detailed_location else "")
                        return ChatResponse(
                            reply=f"📍 Ho verificato la posizione di **{matched_item.item_name}**: si trova in **{loc_str}**.",
                            action="search_vault",
                            data={"item": {"item_id": matched_item.id, "item_name": matched_item.item_name, "location_str": loc_str}}
                        )

            # Fallback deterministico per memorizzazione posizione nei test offline
            if is_store_or_update:
                item_n, loc_n = self._extract_item_and_location(user_text, last_item_in_context=last_item_name)
                if item_n and loc_n:
                    stored_item_result = self.execute_tool("store_physical_item", {"item_name": item_n, "primary_location": loc_n}, db=db, thread_id=thread_id)
                else:
                    is_store_or_update = False

            # Fallback deterministico per richieste Google Drive nei test offline
            drive_resp = self._handle_drive_intent(user_text, lower_t, db, thread_id=thread_id)
            if drive_resp:
                return drive_resp

            # Fallback deterministico per ispezione tabelle/Excel nei test offline
            if is_content_inspect_request:
                c_out = self.execute_tool("read_vault_document_content", {"query": user_text}, db=db, thread_id=thread_id)
                if c_out.get("success"):
                    tbl = c_out.get("markdown_table") or c_out.get("content_text") or ""
                    doc_title = c_out.get("document_title") or "Documento"
                    sheet_info = f" (Foglio: **{c_out.get('active_sheet')}**)" if c_out.get("active_sheet") else ""
                    return ChatResponse(
                        reply=f"📊 **Dati estratti dal file '{doc_title}'**{sheet_info}:\n\n{tbl}\n\n💡 *{c_out.get('summary', '')}*",
                        action="read_vault_document_content",
                        data=c_out
                    )

            clean_test = lower_t.replace("?", "").strip()

            if is_link_photo_intent:
                tool_out = self.execute_tool("link_document_to_item", {"item_name": linked_photo_item}, db=db, thread_id=thread_id)
                if tool_out.get("success"):
                    it_name = tool_out.get("item_name", linked_photo_item)
                    return ChatResponse(
                        reply=f"✅ Ho associato la foto alla posizione di **{it_name}**! Quando mi chiederai dove si trova, ti mostrerò subito la foto della sua posizione. 📸",
                        action="link_document_to_item",
                        data=tool_out,
                        documents=tool_out.get("documents")
                    )
                else:
                    return ChatResponse(
                        reply=tool_out.get("error", "Non sono riuscito ad associare la foto all'oggetto."),
                        action="link_document_to_item",
                        data=tool_out
                    )

            if is_download_or_show or is_doc_search_request:
                last_asst_msg = (
                    db.query(ChatMessage)
                    .filter(ChatMessage.thread_id == thread_id, ChatMessage.sender == "assistant")
                    .order_by(ChatMessage.id.desc())
                    .first()
                )
                target_docs = []
                if is_download_or_show and last_asst_msg:
                    # 1. Prova da metadata_json
                    if last_asst_msg.metadata_json:
                        try:
                            m_data = json.loads(last_asst_msg.metadata_json)
                            m_docs = m_data.get("documents") or (m_data.get("data") or {}).get("deadlines") or (m_data.get("data") or {}).get("upcoming_documents")
                            if m_docs:
                                for md in m_docs:
                                    md_id = md.get("id") or md.get("document_id")
                                    if md_id:
                                        d_obj = db.query(Document).filter(Document.id == int(md_id)).first()
                                        if d_obj and d_obj not in target_docs:
                                            target_docs.append(d_obj)
                        except Exception:
                            pass
                    # 2. Match su titoli, mittenti o importi nel testo del messaggio precedente
                    if last_asst_msg.content:
                        all_docs = db.query(Document).order_by(Document.created_at.desc()).all()
                        for d in all_docs:
                            if d.title and len(d.title) >= 3 and d.title.lower() in last_asst_msg.content.lower():
                                if d not in target_docs:
                                    target_docs.append(d)
                            elif d.issuer and len(d.issuer) >= 3 and d.issuer.lower() in last_asst_msg.content.lower():
                                if d not in target_docs:
                                    target_docs.append(d)
                            elif d.amount and (f"{d.amount:.2f}".replace('.', ',') in last_asst_msg.content or f"{d.amount:.2f}" in last_asst_msg.content):
                                if d not in target_docs:
                                    target_docs.append(d)
                        if not target_docs:
                            cand_lines = [line.strip(" *🏛️📄:-") for line in last_asst_msg.content.split("\n") if any(k in line.lower() for k in ["f24", "bolletta", "ricevuta", "contratto", "estratto", "certificato", "tessera", "mutuo"])]
                            for cl in cand_lines:
                                s_res = search_vault_documents(db, cl, thread_id=thread_id)
                                if s_res:
                                    td = db.query(Document).filter(Document.id == s_res[0]["id"]).first()
                                    if td and td not in target_docs:
                                        target_docs.append(td)
                        if not target_docs and any(k in last_asst_msg.content.lower() for k in ["scadenz", "bollett", "da pagare", "f24", "tribut"]):
                            unpaid = db.query(Document).filter(Document.status == "da_pagare").order_by(Document.due_date.asc().nulls_last()).all()
                            for ud in unpaid:
                                if ud not in target_docs:
                                    target_docs.append(ud)

                if not target_docs:
                    clean_query = re.sub(
                        r"^(?:dammi|mostrami|mostra|apri|visualizza|prendi|vedi|scarica|trovami|trova|voglio\s+vedere|fammi\s+vedere|cerca)\s*(?:il|la|lo|le|i|l'|un|una|uno)?\s*",
                        "", lower_t
                    ).strip(" ?.")
                    clean_query = re.sub(
                        r"\s*(?:nel\s+drive|su\s+drive|in\s+drive|sul\s+drive|su\s+google\s+drive|in\s+google\s+drive|dal\s+drive|da\s+drive|nel\s+caveau|in\s+caveau)$",
                        "", clean_query, flags=re.IGNORECASE
                    ).strip(" ?.")
                    s_matches = search_vault_documents(db, clean_query or user_text, thread_id=thread_id)
                    for m in s_matches[:4]:
                        td = db.query(Document).filter(Document.id == m["id"]).first()
                        if td and td not in target_docs:
                            target_docs.append(td)

                # Se richiesta singolare esplicita ("il", "la") e non plurale/collettiva
                is_sing = any(re.search(rf"\b{w}\b", lower_t) for w in ["il", "lo", "la", "l'", "un", "una"]) and not any(re.search(rf"\b{w}\b", lower_t) for w in ["i", "gli", "le", "tutti", "tutte", "entrambi", "entrambe", "documenti", "ricevute", "bollette"])
                if is_sing and len(target_docs) > 1:
                    for d in target_docs:
                        d_words = [w for w in re.split(r"[^\w]+", d.title.lower()) if len(w) > 2 and w not in ITALIAN_STOPWORDS]
                        if any(w in lower_t for w in d_words):
                            target_docs = [d]
                            break

                args_card = {"document_ids": [d.id for d in target_docs]} if target_docs else {}
                tool_out = self.execute_tool("show_document_card", args_card, db=db, thread_id=thread_id)
                docs = tool_out.get("documents", [])
                if docs:
                    if len(docs) > 1:
                        lines = [f"- 📄 **{d['title']}** ({d.get('issuer') or d.get('doc_type', '')})" for d in docs]
                        rep = (
                            f"📄 Ho trovato i seguenti **{len(docs)} documenti** nel caveau:\n\n" +
                            "\n".join(lines) +
                            "\n\nEcco le schede con i pulsanti 'Vedi' e 'Scarica' per ciascun file qui sotto! ⬇️"
                        )
                    else:
                        rep = f"📄 Ecco la scheda per **{docs[0]['title']}**! Puoi visualizzarlo o scaricarlo direttamente con il pulsante qui sotto. ⬇️"
                    return ChatResponse(
                        reply=rep,
                        action="show_document_card",
                        data=tool_out,
                        documents=docs
                    )

            if is_rename_request:
                new_title = self._extract_rename_title(user_text)
                if new_title:
                    tool_out = self.execute_tool("rename_vault_document", {"new_title": new_title}, db=db, thread_id=thread_id)
                    if tool_out.get("success"):
                        return ChatResponse(
                            reply=f"✅ Ho rinominato il file in '**{tool_out['new_title']}**'!",
                            action="rename_vault_document",
                            data=tool_out,
                            documents=tool_out.get("documents")
                        )
                    else:
                        return ChatResponse(
                            reply=tool_out.get("error", "Non sono riuscito a rinominare il file."),
                            action="rename_vault_document",
                            data=tool_out
                        )

            if is_store_or_update and stored_item_result:
                return ChatResponse(
                    reply=f"✅ Memorizzato! Ho aggiornato la posizione di **{stored_item_result['item_name']}** in: {stored_item_result['location_str']}.",
                    action="store_physical_item",
                    data=stored_item_result
                )

            if is_where_request:
                q = re.sub(r"^(?:dov'è|dov'e|dove è|dove sono|dove si trova|dove ho messo|dove sta|dove)\s+(?:il|lo|la|i|gli|le|l')?\s*", "", lower_t).strip(" ?.")
                tool_out = self.execute_tool("search_vault", {"query": q}, db=db, thread_id=thread_id)
                items = tool_out.get("found_physical_items", [])
                docs = tool_out.get("found_documents", [])
                if items:
                    it = items[0]
                    loc_desc = it.get("location_str") or (it.get("primary_location", "") + (f" ({it['detailed_location']})" if it.get("detailed_location") else ""))
                    linked_d = None
                    if it.get("document_id"):
                        d_rec = db.query(Document).filter(Document.id == it["document_id"]).first()
                        if d_rec:
                            fn = Path(d_rec.file_path).name if d_rec.file_path else ""
                            linked_d = {
                                "id": d_rec.id, "document_id": d_rec.id, "title": d_rec.title,
                                "file_url": f"/uploads/{fn}" if fn else None,
                                "download_url": f"/api/documents/{d_rec.id}/download",
                                "file_type": d_rec.file_type
                            }
                    elif it.get("image_url"):
                        linked_d = {
                            "id": it.get("item_id"), "document_id": it.get("item_id"), "title": f"Foto {it['item_name']}",
                            "file_url": it["image_url"], "download_url": it["image_url"], "file_type": "image"
                        }
                    photo_note = "\n📸 Ho allegato la foto della posizione qui sotto!" if (it.get("has_photo") or linked_d) else ""
                    return ChatResponse(
                        reply=f"📍 **{it['item_name']}** si trova in: {loc_desc}.{photo_note}",
                        action="search_vault",
                        data=tool_out,
                        documents=[linked_d] if linked_d else None
                    )
                elif docs:
                    d = docs[0]
                    return ChatResponse(
                        reply=f"📄 Ho trovato il documento **{d['title']}** ({d.get('issuer', '')}).",
                        action="search_vault",
                        data=tool_out,
                        documents=[d]
                    )
                else:
                    return ChatResponse(
                        reply=f"Ho cercato nel caveau, ma non ho trovato '{q}'. Potrebbe essere stato eliminato o non ancora memorizzato.",
                        action="search_vault",
                        data=tool_out
                    )

            if is_listing_request or any(k in clean_test for k in ["lista", "elenco", "quali documenti", "quali oggetti"]):
                target = "physical_items" if any(k in clean_test for k in ["oggett", "cose"]) else ("documents" if any(k in clean_test for k in ["document", "file", "bollett"]) else "all")
                tool_out = self.execute_tool("list_vault_contents", {"target_type": target}, db=db, thread_id=thread_id)
                if target == "physical_items":
                    items = tool_out.get("physical_items", [])
                    if items:
                        lines = [f"- 📍 **{it['item_name']}**: {it['location_str']}" for it in items]
                        rep = "Ecco gli oggetti fisici memorizzati nel caveau:\n\n" + "\n".join(lines)
                    else:
                        rep = "Nel caveau non sono presenti oggetti fisici memorizzati al momento. Dimmi pure dove riponi i tuoi oggetti e li registrerò subito! 📍"
                    return ChatResponse(reply=rep, action="list_vault_contents", data=tool_out)
                elif target == "documents":
                    docs = tool_out.get("documents", [])
                    if docs:
                        lines = [f"- 📄 **{d['title']}** ({d['issuer']})" for d in docs]
                        rep = f"Ecco l'elenco dei {len(docs)} documenti presenti nel caveau:\n\n" + "\n".join(lines)
                    else:
                        rep = "Nel caveau non sono presenti documenti archiviati al momento."
                    return ChatResponse(reply=rep, action="list_vault_contents", data=tool_out, documents=docs[:5])
                else:
                    items = tool_out.get("physical_items", [])
                    docs = tool_out.get("documents", [])
                    parts = []
                    if docs:
                        lines = [f"- 📄 **{d['title']}** ({d.get('issuer', '')})" for d in docs]
                        parts.append("📄 **Documenti:**\n" + "\n".join(lines))
                    if items:
                        lines = [f"- 📍 **{it['item_name']}**: {it['location_str']}" for it in items]
                        parts.append("📍 **Oggetti fisici:**\n" + "\n".join(lines))
                    rep = "\n\n".join(parts) if parts else "Nel caveau non sono presenti documenti o oggetti memorizzati al momento."
                    return ChatResponse(reply=rep, action="list_vault_contents", data=tool_out, documents=docs[:5])

            if is_deadline_request:
                t_out = self.execute_tool("get_upcoming_deadlines", {}, db, thread_id=thread_id)
                docs = t_out.get("deadlines") or t_out.get("upcoming_documents", [])
                if docs:
                    lines = []
                    for d in docs[:5]:
                        urg = f" - ⚠️ {d['urgency_label']}" if d.get('urgency_label') else ""
                        lines.append(f"- 📄 **{d['title']}** — {d.get('amount','?')} € scad. {d.get('due_date','?')}{urg}")
                    return ChatResponse(reply="📅 Ecco le tue scadenze in sospeso:\n\n" + "\n".join(lines), action="get_upcoming_deadlines", data=t_out, documents=docs)
                return ChatResponse(reply="✅ Non ci sono scadenze o pagamenti in sospeso al momento.", action="get_upcoming_deadlines", data=t_out)

            if audio_base64 and (not user_text or user_text.strip() in ["🎤 Messaggio vocale", "Messaggio vocale", "🎤"]):
                return ChatResponse(
                    reply="🎤 Ho ascoltato il tuo messaggio vocale! Tutto chiaro, richiesta registrata con successo.",
                    action="REPLY"
                )

            ai = MockAIService()
            intent = ai.classify_and_extract_intent(user_text)
            reply = ai.generate_conversational_reply(user_text)
            return ChatResponse(reply=reply, action="REPLY")

        # Recupera la cronologia recente della chat (fino a 100 messaggi) per massima consapevolezza conversazionale e contesto continuo
        system_content = self.build_system_prompt(db, thread_id=thread_id)
        recent_msgs = (
            db.query(ChatMessage)
            .filter(ChatMessage.thread_id == thread_id)
            .order_by(ChatMessage.id.desc())
            .limit(100)
            .all()
        )
        history_messages: List[Dict[str, Any]] = [{"role": "system", "content": system_content}]
        for m in reversed(recent_msgs):
            if m.content != user_text:
                # Evita di contaminare il contesto con vecchi messaggi contenenti tag tool grezzi
                if "<tool_call>" in m.content or "<function=" in m.content:
                    continue
                history_messages.append({
                    "role": "assistant" if m.sender == "assistant" else "user",
                    "content": m.content
                })

        # Iniezione telemetria UI client (se ci sono stati errori recenti di visualizzazione o download)
        ui_telemetry_note = self._build_ui_telemetry_prompt_note(db, thread_id=thread_id)
        if ui_telemetry_note:
            history_messages.append({"role": "system", "content": ui_telemetry_note})

        if quoted_message and quoted_message.get("text"):
            q_sender = quoted_message.get("sender") or "Messaggio precedente"
            q_text = str(quoted_message.get("text", "")).strip()
            user_llm_content = f'[In risposta a {q_sender}: "{q_text}"]\n{user_text}'
        else:
            user_llm_content = user_text

        if audio_base64:
            clean_fmt = (audio_format or "wav").lower().lstrip(".")
            if user_llm_content and user_llm_content not in ["🎤 Messaggio vocale", "Messaggio vocale", "🎤"]:
                voice_prompt = f"[Messaggio Vocale Trascritto]: {user_llm_content}"
                history_messages.append({"role": "user", "content": voice_prompt})
            else:
                voice_prompt = "Ascolta attentamente questo messaggio vocale dell'utente in italiano ed esegui le azioni necessarie tramite gli strumenti o rispondi in modo naturale e preciso."
                history_messages.append({
                    "role": "user",
                    "content": [
                        {"type": "text", "text": voice_prompt},
                        {
                            "type": "input_audio",
                            "input_audio": {
                                "data": audio_base64,
                                "format": clean_fmt
                            }
                        }
                    ]
                })
        else:
            history_messages.append({"role": "user", "content": user_llm_content})

        headers = {
            "Authorization": f"Bearer {self.settings.OPENROUTER_API_KEY.strip()}",
            "HTTP-Referer": "http://localhost:8000",
            "X-Title": "Dove lo AI messo",
            "Content-Type": "application/json"
        }

        tool_action = "REPLY"
        tool_data = None

        agent_model = effective_model or get_app_setting(db, "ai_model", default=self.settings.OPENROUTER_MODEL) or "google/gemini-2.5-flash-lite"


        is_drive_status_request = (
            (
                any(k in lower_t for k in ["google drive", "su drive", "in drive", "mio drive", "tuo drive", "nostro drive"])
                or ("drive" in lower_t and any(k in lower_t for k in ["stato", "conness", "collegat", "cartell", "organizzat", "cosa c'è", "cosa ce", "quali file", "come funziona", "spiegami", "come hai"]))
            )
            and not is_doc_search_request
            and not is_where_request
            and not is_listing_request
        )

        # Standard Agentic Prompt-Driven: il modello opera con tool_choice='auto'
        # e sceglie liberamente gli strumenti più appropriati in base al contesto e al prompt
        tool_choice_cfg = "auto"

        try:
            r1 = httpx.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json={
                    "model": agent_model,
                    "messages": history_messages,
                    "tools": TOOLS_DEFINITION,
                    "tool_choice": tool_choice_cfg,
                    "max_tokens": 8192,
                    "temperature": 0.2
                },
                timeout=60.0
            )

            # Retry automatico: se la prima chiamata fallisce (es. "model output must contain
            # either output text or tool calls" con tool_choice forzato), riproviamo con "auto"
            if r1.status_code != 200 and tool_choice_cfg != "auto":
                err_body = ""
                try:
                    err_body = r1.json().get("error", {}).get("message", r1.text[:200])
                except Exception:
                    err_body = r1.text[:200]
                logger.warning(
                    f"OpenRouter r1 non-200 (status={r1.status_code}) con tool_choice={tool_choice_cfg!r}: {err_body}. "
                    "Retry con tool_choice='auto'..."
                )
                r1 = httpx.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers=headers,
                    json={
                        "model": agent_model,
                        "messages": history_messages,
                        "tools": TOOLS_DEFINITION,
                        "tool_choice": "auto",
                        "max_tokens": 8192,
                        "temperature": 0.2
                    },
                    timeout=60.0
                )

            if r1.status_code == 200:
                data1 = r1.json()
                msg1 = data1.get("choices", [{}])[0].get("message", {})
                tool_calls1 = msg1.get("tool_calls")
                
                if tool_calls1 and len(tool_calls1) > 0:
                    call1 = tool_calls1[0]
                    call_func = call1.get("function", {})
                    name1 = call_func.get("name")
                    try:
                        args1 = json.loads(call_func.get("arguments", "{}"))
                    except Exception:
                        args1 = {}

                    logger.info(f"Agentic calling tool: {name1} with args: {args1}")
                    tool_data = self.execute_tool(name1, args1, db, thread_id=thread_id)
                    tool_action = name1

                    history_messages.append(msg1)
                    history_messages.append({
                        "role": "tool",
                        "tool_call_id": call1.get("id", "call_1"),
                        "name": name1,
                        "content": json.dumps(tool_data, ensure_ascii=False)
                    })

                    r2 = httpx.post(
                        "https://openrouter.ai/api/v1/chat/completions",
                        headers=headers,
                        json={
                            "model": agent_model,
                            "messages": history_messages,
                            "max_tokens": 8192,
                            "temperature": 0.2
                        },
                        timeout=60.0
                    )

                    if r2.status_code == 200:
                        final_msg = r2.json().get("choices", [{}])[0].get("message", {})
                        final_text = (final_msg.get("content") or "").strip()
                        final_text = strip_tool_tags(final_text)

                        docs_found = None
                        if isinstance(tool_data, dict):
                            docs_found = (
                                tool_data.get("found_documents")
                                or tool_data.get("recent_documents")
                                or tool_data.get("documents")
                                or tool_data.get("extracted_documents")
                                or tool_data.get("upcoming_documents")
                                or tool_data.get("deadlines")
                            )

                        if not final_text:
                            if tool_action == "search_vault":
                                if docs_found:
                                    d = docs_found[0]
                                    final_text = f"📄 Ho trovato: **{d['title']}**\n💡 {d['summary']}"
                                else:
                                    final_text = "Ho cercato nel caveau ma non ho trovato corrispondenze nel database."
                            elif tool_action == "show_document_card":
                                d_tit = (docs_found[0]["title"] if docs_found else "documento")
                                final_text = f"📄 Ecco la scheda per **{d_tit}**! Puoi visualizzarlo o scaricarlo direttamente dalla scheda qui sotto. ⬇️"
                            elif tool_action == "link_document_to_item":
                                it_name = (tool_data or {}).get("item_name") or "oggetto"
                                final_text = f"✅ Ho associato la foto alla posizione di **{it_name}**! Quando mi chiederai dove si trova, ti mostrerò subito la foto della sua posizione. 📸"
                            elif tool_action == "list_vault_contents":
                                if (tool_data or {}).get("target_type") == "physical_items":
                                    items = (tool_data or {}).get("physical_items", [])
                                    if items:
                                        lines = [f"- 📍 **{it['item_name']}**: {it['location_str']}" for it in items]
                                        final_text = f"📍 Ecco gli oggetti fisici memorizzati nel caveau:\n\n" + "\n".join(lines)
                                    else:
                                        final_text = "Nel caveau non sono presenti oggetti fisici memorizzati al momento. Dimmi pure dove riponi i tuoi oggetti e li registrerò subito! 📍"
                                elif (tool_data or {}).get("target_type") == "documents":
                                    docs = (tool_data or {}).get("documents", [])
                                    if docs:
                                        lines = [f"- 📄 **{d['title']}** ({d['issuer']})" for d in docs]
                                        final_text = f"📄 Ecco i documenti archiviati nel caveau:\n\n" + "\n".join(lines)
                                    else:
                                        final_text = "Nel caveau non sono presenti documenti archiviati al momento."
                                else:
                                    items = (tool_data or {}).get("physical_items", [])
                                    docs = (tool_data or {}).get("documents", [])
                                    parts = []
                                    if docs:
                                        lines = [f"- 📄 **{d['title']}** ({d.get('issuer', '')})" for d in docs]
                                        parts.append("📄 **Documenti:**\n" + "\n".join(lines))
                                    if items:
                                        lines = [f"- 📍 **{it['item_name']}**: {it['location_str']}" for it in items]
                                        parts.append("📍 **Oggetti fisici:**\n" + "\n".join(lines))
                                    final_text = "\n\n".join(parts) if parts else "Nel caveau non sono presenti documenti o oggetti memorizzati al momento."
                            elif tool_action == "get_upcoming_deadlines":
                                up = (tool_data or {}).get("deadlines") or (tool_data or {}).get("upcoming_documents", [])
                                if up:
                                    lines = []
                                    for d in up[:5]:
                                        urg = f" - ⚠️ {d['urgency_label']}" if d.get('urgency_label') else ""
                                        lines.append(f"- 📄 **{d['title']}**: {d.get('amount', '?')} € (scad. {d.get('due_date', '?')}{urg})")
                                    final_text = "📅 Ecco le tue scadenze in sospeso:\n\n" + "\n".join(lines)
                                else:
                                    final_text = "✅ Non ci sono scadenze o pagamenti in sospeso al momento."
                            elif tool_action == "get_current_date":
                                final_text = f"📅 Oggi è **{tool_data.get('formatted_italian')}** (ore {tool_data.get('current_time')})."
                            elif tool_action == "store_physical_item":
                                it_name = (tool_data or {}).get("item_name")
                                loc_str = (tool_data or {}).get("location_str")
                                final_text = f"✅ Memorizzato! Ho aggiornato la posizione di **{it_name}** in: {loc_str}."
                            elif tool_action == "rename_vault_document":
                                n_title = (tool_data or {}).get("new_title", "nuovo nome")
                                final_text = f"✅ Ho rinominato il file in '**{n_title}**'!"
                            elif tool_action == "delete_vault_record":
                                t_tit = (tool_data or {}).get("title") or "elemento"
                                final_text = f"⚠️ Ho preparato la richiesta per eliminare **{t_tit}** dal caveau. Clicca sul pulsante qui sotto per confermare o annullare l'operazione."
                            elif tool_action == "read_vault_document_content":
                                doc_title = (tool_data or {}).get("document_title") or "documento"
                                tbl = (tool_data or {}).get("markdown_table") or (tool_data or {}).get("content_text") or ""
                                sheet_info = f" (Foglio: **{(tool_data or {}).get('active_sheet')}**)" if (tool_data or {}).get('active_sheet') else ""
                                final_text = f"📊 **Dati estratti dal file '{doc_title}'**{sheet_info}:\n\n{tbl}\n\n💡 *{(tool_data or {}).get('summary', '')}*"
                            elif tool_action == "unzip_vault_archive":
                                ext_cnt = (tool_data or {}).get("extracted_count", 0)
                                final_text = f"📦 Ho scompattato con successo l'archivio ed estratto {ext_cnt} documenti nel Caveau!"
                            else:
                                final_text = "Operazione completata con successo nel caveau."
                        else:
                            # Validazione e ancoraggio stretto della risposta del modello al database SQLite reale:
                            if tool_action == "show_document_card":
                                final_text = re.sub(r"\[(?:Link per scaricare|Scarica|Download)[^\]]*\]", "la scheda del documento allegata qui sotto", final_text, flags=re.IGNORECASE)
                                if not final_text:
                                    d_tit = (docs_found[0]["title"] if docs_found else "documento")
                                    final_text = f"📄 Ecco la scheda per **{d_tit}**! Puoi visualizzarlo o scaricarlo direttamente dalla scheda qui sotto. ⬇️"

                            elif tool_action == "link_document_to_item":
                                it_name = (tool_data or {}).get("item_name") or "oggetto"
                                if "associat" not in final_text.lower() and "collegat" not in final_text.lower():
                                    final_text = f"✅ Ho associato la foto alla posizione di **{it_name}**! {final_text}"

                            elif tool_action == "list_vault_contents":
                                target = (tool_data or {}).get("target_type")
                                items = (tool_data or {}).get("physical_items", [])
                                docs = (tool_data or {}).get("documents", [])
                                if target == "physical_items" and len(items) == 0:
                                    final_text = "Nel caveau non sono presenti oggetti fisici memorizzati al momento. Dimmi pure dove riponi i tuoi oggetti e li registrerò subito! 📍"
                                elif target == "documents" and len(docs) == 0:
                                    final_text = "Nel caveau non sono presenti documenti archiviati al momento."
                                elif target == "all" and len(items) == 0 and len(docs) == 0:
                                    final_text = "Nel caveau non sono presenti documenti o oggetti memorizzati al momento."

                            elif tool_action == "search_vault":
                                found_i = (tool_data or {}).get("found_physical_items", [])
                                found_d = (tool_data or {}).get("found_documents", [])
                                if not found_i and not found_d:
                                    final_text = "Ho cercato nel caveau ma non ho trovato corrispondenze nel database. Potrebbe essere stato eliminato o non ancora memorizzato."
                                elif found_i and not found_d:
                                    it = found_i[0]
                                    if it.get("primary_location", "").lower() not in final_text.lower():
                                        final_text = f"📍 **{it['item_name']}** si trova in: {it['location_str']}."
                                    if it.get("has_photo") or it.get("document_id"):
                                        if "📸" not in final_text:
                                            final_text += "\n📸 Ho allegato la foto della posizione qui sotto!"
                                        if not docs_found:
                                            d_rec = None
                                            if it.get("document_id"):
                                                d_rec = db.query(Document).filter(Document.id == it["document_id"]).first()
                                            elif it.get("image_path"):
                                                d_rec = db.query(Document).filter(Document.file_path == it["image_path"]).first()
                                            if d_rec:
                                                fn = Path(d_rec.file_path).name if d_rec.file_path else ""
                                                docs_found = [{
                                                    "id": d_rec.id, "document_id": d_rec.id, "title": d_rec.title,
                                                    "issuer": d_rec.issuer, "amount": d_rec.amount,
                                                    "due_date": d_rec.due_date.isoformat() if d_rec.due_date else None,
                                                    "summary": d_rec.summary,
                                                    "file_url": f"/uploads/{fn}" if fn else None,
                                                    "download_url": f"/api/documents/{d_rec.id}/download",
                                                    "file_type": d_rec.file_type
                                                }]

                            elif tool_action == "get_upcoming_deadlines":
                                up = (tool_data or {}).get("deadlines") or (tool_data or {}).get("upcoming_documents", [])
                                if len(up) == 0:
                                    final_text = "✅ Non ci sono scadenze o pagamenti in sospeso al momento."

                            elif tool_action == "store_physical_item":
                                it_n = (tool_data or {}).get("item_name")
                                loc_s = (tool_data or {}).get("location_str")
                                if loc_s and (tool_data or {}).get("primary_location", "").lower() not in final_text.lower():
                                    final_text = f"✅ Memorizzato! Ho salvato la posizione di **{it_n}** in: {loc_s}."
                                elif "memorizzato" not in final_text.lower() and "salvat" not in final_text.lower() and "aggiornat" not in final_text.lower():
                                    final_text = f"✅ Memorizzato! {final_text}"

                            elif tool_action == "rename_vault_document":
                                n_title = (tool_data or {}).get("new_title")
                                if n_title and n_title.lower() not in final_text.lower():
                                    final_text = f"✅ Ho rinominato il file in '**{n_title}**'!\n{final_text}"

                            elif tool_action == "unzip_vault_archive":
                                if "scompattat" not in final_text.lower() and "estratti" not in final_text.lower():
                                    ext_cnt = (tool_data or {}).get("extracted_count", len(docs_found) if docs_found else 0)
                                    final_text = f"📦 Ho scompattato con successo l'archivio ZIP ({ext_cnt} documenti estratti)!\n\n{final_text}"

                        # Sanitizzazione anti-esitazione:
                        final_text = re.sub(r"per scaricare entrambi i documenti,?\s*dovrai farlo singolarmente\.?", "", final_text, flags=re.IGNORECASE).strip()
                        is_meta_or_help = any(
                            p in user_text.lower() for p in [
                                "cosa puoi fare", "cosa sai fare", "chi sei", "come funzioni", "come ti chiami",
                                "cosa posso chiederti", "a cosa servi", "cosa fai", "spiegami cosa puoi fare",
                                "aiuto", "help", "funzionalità", "istruzioni", "presentati"
                            ]
                        ) or user_text.strip(" ?.!").lower() in ["ciao", "buongiorno", "buonasera", "salve", "ehi", "hey", "help", "aiuto", "info"]

                        hesitation_pattern = r"(?:desideri\s+che\s+ti\s+mostri\s+la\s+scheda\s+di\s+uno\s+(?:di\s+questi\s+documenti\s+)?in\s+particolare\??|quale\s+(?:di\s+questi\s+)?(?:vuoi|desideri|preferisci)\s*(?:vedere|scaricare|aprire)?\??|vuoi\s+che\s+ti\s+mostri\s+la\s+scheda\??|quale\s+vuoi\??|quale\s+preferisci\??)"
                        if not is_meta_or_help and docs_found and len(docs_found) > 0 and re.search(hesitation_pattern, final_text, flags=re.IGNORECASE):
                            final_text = re.sub(
                                hesitation_pattern,
                                "Ecco le schede con i pulsanti 'Vedi' e 'Scarica' per ciascun documento qui sotto! ⬇️",
                                final_text,
                                flags=re.IGNORECASE
                            ).strip()
                            filtered_docs = docs_found[:4]
                            tool_action = "show_document_card"

                        mentions_cards_in_text = any(k in final_text.lower() for k in [
                            "sched", "scarica", "scaricarlo", "scaricarla", "scaricarli", "scaricarle",
                            "visualizza", "visualizzarlo", "visualizzarla", "visualizzarli", "visualizzarle",
                            "qui sotto", "apri il documento", "apri il file"
                        ])

                        # Regola deterministica e affidabile per l'allegato delle schede:
                        # 1) show_document_card o unzip_vault_archive -> mostra sempre le schede
                        # 2) get_upcoming_deadlines -> se ci sono scadenze e il testo menziona schede/visualizzazione/download o l'utente le cerca, allega SEMPRE le schede!
                        # 3) search_vault -> filtra la pertinenza dei documenti
                        # 4) Se final_text menziona schede e docs_found è presente -> allega sempre le schede!
                        if tool_action in ["show_document_card", "unzip_vault_archive"]:
                            filtered_docs = docs_found
                            tool_action = "show_document_card"
                        elif tool_action == "get_upcoming_deadlines":
                            if docs_found and (mentions_cards_in_text or is_download_or_show or not is_meta_or_help):
                                filtered_docs = docs_found[:5]
                                tool_action = "show_document_card"
                            else:
                                filtered_docs = None
                        elif tool_action == "search_vault":
                            filtered_docs = filter_relevant_documents(docs_found, final_text, user_text)
                            if mentions_cards_in_text and docs_found and not filtered_docs:
                                filtered_docs = docs_found[:4]
                        elif mentions_cards_in_text and docs_found:
                            filtered_docs = docs_found[:4]
                            tool_action = "show_document_card"
                        else:
                            filtered_docs = None

                        # Se lo strumento è show_document_card e filtered_docs è presente,
                        # sanifica eventuali scuse allucinate su anomalie dell'interfaccia
                        if tool_action == "show_document_card" and filtered_docs:
                            if any(k in final_text.lower() for k in ["anomalia", "malfunzionamento", "errore di visualizzazione", "inconveniente tecnico"]):
                                if len(filtered_docs) > 1:
                                    lines_d = [f"- 📄 **{d['title']}** ({d.get('issuer') or d.get('doc_type', '')})" for d in filtered_docs]
                                    final_text = (
                                        f"📄 Ecco subito le schede interattive per ciascun documento qui sotto:\n\n" +
                                        "\n".join(lines_d) +
                                        "\n\nPuoi visualizzarli o scaricarli direttamente con i pulsanti 'Vedi' e 'Scarica'! ⬇️"
                                    )
                                else:
                                    final_text = f"📄 Ecco subito la scheda per **{filtered_docs[0]['title']}** qui sotto con i pulsanti per visualizzarlo o scaricarlo direttamente! ⬇️"

                        conf_box = None
                        if isinstance(tool_data, dict) and "confirmation" in tool_data:
                            conf_box = tool_data["confirmation"]
                            tool_action = "REQUEST_DELETE"

                        return ChatResponse(reply=strip_tool_tags(final_text), action=tool_action, data=tool_data, documents=filtered_docs, confirmation=conf_box)
                
                direct_reply = (msg1.get("content") or "").strip()
                lower_t = user_text.lower()
                
                # 0. Intercetta ed esegue tag di tool-call emessi come testo dal modello (es. <tool_call>...)
                tc_match = re.search(r"<tool_call>\s*(.*?)\s*</tool_call>", direct_reply, re.DOTALL | re.IGNORECASE)
                if tc_match:
                    raw_tc = tc_match.group(1).strip()
                    logger.info(f"Intercettata chiamata di tool nel testo del modello: {raw_tc}")
                    
                    # Prova ad estrarre il nome del tool e la query dall'XML testuale
                    tool_name_m = re.search(r"(\w+)\s*\n|^(\w+)\s", raw_tc)
                    arg_val_m = re.search(r"<arg_value>(.*?)</arg_value>", raw_tc, re.DOTALL)
                    extracted_query = (arg_val_m.group(1).strip() if arg_val_m else "").lower() or re.sub(r"<[^>]+>", "", raw_tc).strip()

                    is_store_tc = "store_physical_item" in raw_tc or (any(k in lower_t for k in ["messo", "riposto", "salvato", "lasciato", "conservato"]) and not any(k in lower_t for k in ["dov'è", "dov'e", "dove"]))
                    if is_store_tc:
                        m = re.search(r"(?:messo|riposto|salvato|lasciato|conservato)\s+(?:il\s+|la\s+|le\s+|i\s+|l\')?(.+?)\s+(?:nel|nella|in|su|sul|sotto|a)\s+(.+)", lower_t)
                        item = m.group(1).strip() if m else "Oggetto"
                        loc = m.group(2).strip() if m else "posto specificato"
                        db_res = self.execute_tool("store_physical_item", {"item_name": item, "primary_location": loc}, db, thread_id=thread_id)
                        return ChatResponse(reply=f"✅ Memorizzato! Ho salvato la posizione di '{item}' in: {loc}.", action="store_physical_item", data=db_res)

                    # Per tutti gli altri tool call testuali (search_vault, get_upcoming_deadlines, get_current_date, ecc.)
                    # esegui la ricerca più appropriata in base al contenuto
                    if "get_current_date" in raw_tc:
                        d_info = self.execute_tool("get_current_date", {}, db, thread_id=thread_id)
                        return ChatResponse(
                            reply=f"📅 Oggi è **{d_info['formatted_italian']}** (ore {d_info['current_time']}).",
                            action="get_current_date",
                            data=d_info
                        )

                    if "get_upcoming_deadlines" in raw_tc:
                        t_out = self.execute_tool("get_upcoming_deadlines", {}, db, thread_id=thread_id)
                        docs = t_out.get("deadlines") or t_out.get("upcoming_documents", [])
                        if docs:
                            lines = []
                            for d in docs[:5]:
                                urg = f" - ⚠️ {d['urgency_label']}" if d.get('urgency_label') else ""
                                lines.append(f"- 📄 **{d['title']}** — {d.get('amount','?')} € scad. {d.get('due_date','?')}{urg}")
                            return ChatResponse(reply="📅 Ecco le tue scadenze in sospeso:\n\n" + "\n".join(lines), action="get_upcoming_deadlines", data=t_out, documents=docs)

                    if "read_vault_document_content" in raw_tc:
                        c_out = self.execute_tool("read_vault_document_content", {"query": extracted_query or user_text}, db=db, thread_id=thread_id)
                        if c_out.get("success"):
                            tbl = c_out.get("markdown_table") or c_out.get("content_text") or ""
                            return ChatResponse(
                                reply=f"📊 **Dati estratti dal file '{c_out.get('document_title', 'Documento')}'**:\n\n{tbl}\n\n💡 *{c_out.get('summary', '')}*",
                                action="read_vault_document_content",
                                data=c_out
                            )

                    # search_vault o qualsiasi altro caso: cerca col termine estratto o con il testo utente
                    search_q = extracted_query or re.sub(r"^(?:cerca|trovami|trova|dov'è|dov'e|dove|quant'è|quanto)\s*", "", lower_t).strip(" ?.")
                    t_out = self.execute_tool("search_vault", {"query": search_q or user_text}, db, thread_id=thread_id)
                    docs = t_out.get("found_documents", [])
                    items_found = t_out.get("found_physical_items", [])
                    if docs:
                        d = docs[0]
                        filtered_d = filter_relevant_documents(docs, d['title'], user_text) or [d]
                        return ChatResponse(
                            reply=f"📄 Ho trovato il documento '{d['title']}':\n💡 {d['summary']}",
                            action="search_vault",
                            data=t_out,
                            documents=filtered_d
                        )
                    if items_found:
                        it = items_found[0]
                        loc = it['primary_location'] + (f" ({it['detailed_location']})" if it['detailed_location'] else "")
                        return ChatResponse(reply=f"📍 Il tuo {it['item_name']} si trova in: {loc}.", action="search_vault", data=t_out)

                    # Se non è stato trovato nulla, rispondi con un messaggio negativo onesto e pulito (nessuna allucinazione o file recente casuale)
                    return ChatResponse(
                        reply="Ho cercato nel caveau, ma non ho trovato nessun documento o dato corrispondente alla tua richiesta.",
                        action="search_vault",
                        data=t_out
                    )

                # Pulisci sempre il testo diretto prima di usarlo (rimuove eventuali tag residui)
                direct_reply = strip_tool_tags(direct_reply)

                if direct_reply:
                    if is_delete_request:
                        is_bulk_phrase = any(k in lower_t for k in ["tutti", "tutte", "tutto"])
                        t_type = "bulk_documents" if is_bulk_phrase else ("physical_item" if any(k in lower_t for k in ["patente", "passaporto", "chiav", "oggett"]) else "document")
                        del_tool_res = self.execute_tool("delete_vault_record", {"target_type": t_type, "title": user_text}, db=db, thread_id=thread_id)
                        conf_b = del_tool_res.get("confirmation")
                        c_docs = del_tool_res.get("documents")
                        return ChatResponse(
                            reply=direct_reply,
                            action="REQUEST_DELETE" if conf_b else "REPLY",
                            data=del_tool_res,
                            documents=c_docs,
                            confirmation=conf_b
                        )

                    if is_rename_request:
                        new_title = self._extract_rename_title(user_text)
                        if new_title:
                            r_out = self.execute_tool("rename_vault_document", {"new_title": new_title}, db=db, thread_id=thread_id)
                            if r_out.get("success"):
                                return ChatResponse(
                                    reply=f"✅ Ho rinominato il file in '**{r_out['new_title']}**'!",
                                    action="rename_vault_document",
                                    data=r_out,
                                    documents=r_out.get("documents")
                                )

                    if is_store_or_update:
                        if not stored_item_result:
                            item_n, loc_n = self._extract_item_and_location(user_text, last_item_in_context=last_item_name)
                            if item_n and loc_n:
                                stored_item_result = self.execute_tool("store_physical_item", {"item_name": item_n, "primary_location": loc_n}, db=db, thread_id=thread_id)
                        if stored_item_result:
                            if "memorizzato" not in direct_reply.lower() and "salvat" not in direct_reply.lower() and "aggiornat" not in direct_reply.lower():
                                direct_reply = f"✅ Posizione aggiornata! {direct_reply}"
                            return ChatResponse(
                                reply=direct_reply,
                                action="store_physical_item",
                                data=stored_item_result
                            )

                    # Se l'utente chiedeva dove si trova qualcosa (is_where_request),
                    # ancoriamo sempre la risposta al database reale SQLite (nessuna allucinazione da cronologia chat)
                    if is_where_request:
                        search_q = re.sub(r"^(?:dov'è|dov'e|dove è|dove sono|dove si trova|dove ho messo|dove sta|dove)\s+(?:il|lo|la|i|gli|le|l')?\s*", "", lower_t).strip(" ?.")
                        s_res = self.execute_tool("search_vault", {"query": search_q or user_text}, db=db, thread_id=thread_id)
                        found_items = s_res.get("found_physical_items", [])
                        found_docs = s_res.get("found_documents", [])
                        if found_items:
                            it = found_items[0]
                            loc_desc = it.get("location_str") or (it.get("primary_location", "") + (f" ({it['detailed_location']})" if it.get("detailed_location") else ""))
                            clean_rep = f"📍 **{it['item_name']}** si trova in: {loc_desc}."
                            docs_to_attach = []
                            if it.get("has_photo") or it.get("document_id"):
                                clean_rep += "\n\n📸 Ho allegato la foto della posizione qui sotto!"
                                if it.get("document_id"):
                                    d_rec = db.query(Document).filter(Document.id == it["document_id"]).first()
                                    if d_rec:
                                        fn = Path(d_rec.file_path).name if d_rec.file_path else ""
                                        docs_to_attach.append({
                                            "id": d_rec.id, "document_id": d_rec.id, "title": d_rec.title,
                                            "issuer": d_rec.issuer, "amount": d_rec.amount,
                                            "due_date": d_rec.due_date.isoformat() if d_rec.due_date else None,
                                            "summary": d_rec.summary, "file_url": f"/uploads/{fn}" if fn else None,
                                            "download_url": f"/api/documents/{d_rec.id}/download", "file_type": d_rec.file_type
                                        })
                            reply_out = direct_reply if direct_reply else clean_rep
                            if (it.get("has_photo") or it.get("document_id")) and "📸" not in reply_out:
                                reply_out += "\n\n📸 Ho allegato la foto della posizione qui sotto!"
                            return ChatResponse(reply=reply_out, action="search_vault", data=s_res, documents=docs_to_attach if docs_to_attach else None)
                        elif found_docs:
                            d = found_docs[0]
                            clean_rep = f"📄 Ho trovato il documento **{d['title']}** ({d.get('issuer', '')}).\n💡 {d.get('summary', '')}"
                            reply_out = direct_reply if direct_reply else clean_rep
                            return ChatResponse(reply=reply_out, action="search_vault", data=s_res, documents=[d])
                        else:
                            clean_rep = f"Ho cercato nel caveau, ma non ho trovato '{search_q}'. Potrebbe essere stato eliminato o non ancora registrato."
                            reply_out = direct_reply if direct_reply else clean_rep
                            return ChatResponse(reply=reply_out, action="search_vault", data=s_res)

                    if is_listing_request:
                        target = "physical_items" if any(k in lower_t for k in ["oggett", "cose"]) else ("documents" if any(k in lower_t for k in ["document", "file", "bollett", "fattur"]) else "all")
                        l_res = self.execute_tool("list_vault_contents", {"target_type": target}, db=db, thread_id=thread_id)
                        if target == "physical_items":
                            items = l_res.get("physical_items", [])
                            if items:
                                lines = [f"- 📍 **{it['item_name']}**: {it['location_str']}" for it in items]
                                rep = "📍 Ecco gli oggetti fisici memorizzati nel caveau:\n\n" + "\n".join(lines)
                            else:
                                rep = "Nel caveau non sono presenti oggetti fisici memorizzati al momento. Dimmi pure dove riponi i tuoi oggetti e li registrerò subito! 📍"
                            reply_out = direct_reply if direct_reply else rep
                            return ChatResponse(reply=reply_out, action="list_vault_contents", data=l_res)
                        elif target == "documents":
                            docs = l_res.get("documents", [])
                            if docs:
                                lines = [f"- 📄 **{d['title']}** ({d.get('issuer', '')})" for d in docs]
                                rep = f"📄 Ecco i {len(docs)} documenti presenti nel caveau:\n\n" + "\n".join(lines)
                            else:
                                rep = "Nel caveau non sono presenti documenti archiviati al momento."
                            reply_out = direct_reply if direct_reply else rep
                            return ChatResponse(reply=reply_out, action="list_vault_contents", data=l_res, documents=docs[:5])
                        else:
                            items = l_res.get("physical_items", [])
                            docs = l_res.get("documents", [])
                            parts = []
                            if docs:
                                lines = [f"- 📄 **{d['title']}** ({d.get('issuer', '')})" for d in docs]
                                parts.append("📄 **Documenti:**\n" + "\n".join(lines))
                            if items:
                                lines = [f"- 📍 **{it['item_name']}**: {it['location_str']}" for it in items]
                                parts.append("📍 **Oggetti fisici:**\n" + "\n".join(lines))
                            rep = "\n\n".join(parts) if parts else "Nel caveau non sono presenti documenti o oggetti memorizzati al momento."
                            reply_out = direct_reply if direct_reply else rep
                            return ChatResponse(reply=reply_out, action="list_vault_contents", data=l_res, documents=docs[:5])

                    if is_deadline_request:
                        d_res = self.execute_tool("get_upcoming_deadlines", {}, db=db, thread_id=thread_id)
                        docs = d_res.get("deadlines") or d_res.get("upcoming_documents", [])
                        if docs:
                            lines = []
                            for d in docs[:5]:
                                urg = f" - ⚠️ {d['urgency_label']}" if d.get('urgency_label') else ""
                                lines.append(f"- 📄 **{d['title']}** — {d.get('amount','?')} € scad. {d.get('due_date','?')}{urg}")
                            rep = "📅 Ecco le tue scadenze in sospeso:\n\n" + "\n".join(lines)
                        else:
                            rep = "✅ Non ci sono scadenze o pagamenti in sospeso al momento."
                        reply_out = direct_reply if direct_reply else rep
                        return ChatResponse(reply=reply_out, action="get_upcoming_deadlines", data=d_res, documents=docs)

                    if is_download_or_show:
                        last_asst_msg = (
                            db.query(ChatMessage)
                            .filter(ChatMessage.thread_id == thread_id, ChatMessage.sender == "assistant")
                            .order_by(ChatMessage.id.desc())
                            .first()
                        )
                        target_docs = []
                        if last_asst_msg:
                            # 1. Prova da metadata_json
                            if last_asst_msg.metadata_json:
                                try:
                                    m_data = json.loads(last_asst_msg.metadata_json)
                                    m_docs = m_data.get("documents") or (m_data.get("data") or {}).get("deadlines") or (m_data.get("data") or {}).get("upcoming_documents")
                                    if m_docs:
                                        for md in m_docs:
                                            md_id = md.get("id") or md.get("document_id")
                                            if md_id:
                                                d_obj = db.query(Document).filter(Document.id == int(md_id)).first()
                                                if d_obj and d_obj not in target_docs:
                                                    target_docs.append(d_obj)
                                except Exception:
                                    pass
                            # 2. Match su titoli, mittenti o importi nel testo del messaggio precedente
                            if last_asst_msg.content:
                                all_docs = db.query(Document).order_by(Document.created_at.desc()).all()
                                for d in all_docs:
                                    if d.title and len(d.title) >= 3 and d.title.lower() in last_asst_msg.content.lower():
                                        if d not in target_docs:
                                            target_docs.append(d)
                                    elif d.issuer and len(d.issuer) >= 3 and d.issuer.lower() in last_asst_msg.content.lower():
                                        if d not in target_docs:
                                            target_docs.append(d)
                                    elif d.amount and (f"{d.amount:.2f}".replace('.', ',') in last_asst_msg.content or f"{d.amount:.2f}" in last_asst_msg.content):
                                        if d not in target_docs:
                                            target_docs.append(d)
                                if not target_docs:
                                    cand_lines = [line.strip(" *🏛️📄:-") for line in last_asst_msg.content.split("\n") if any(k in line.lower() for k in ["f24", "bolletta", "ricevuta", "contratto", "estratto", "certificato", "tessera", "mutuo"])]
                                    for cl in cand_lines:
                                        s_res = search_vault_documents(db, cl, thread_id=thread_id)
                                        if s_res:
                                            td = db.query(Document).filter(Document.id == s_res[0]["id"]).first()
                                            if td and td not in target_docs:
                                                target_docs.append(td)
                                if not target_docs and any(k in last_asst_msg.content.lower() for k in ["scadenz", "bollett", "da pagare", "f24", "tribut"]):
                                    unpaid = db.query(Document).filter(Document.status == "da_pagare").order_by(Document.due_date.asc().nulls_last()).all()
                                    for ud in unpaid:
                                        if ud not in target_docs:
                                            target_docs.append(ud)

                        if len(target_docs) > 1 and not any(k in lower_t for k in ["entrambi", "tutti", "tutte", "download", "scarica", "schede", "non vedo", "dove sono"]):
                            for d in target_docs:
                                d_words = [w for w in re.split(r"[^\w]+", d.title.lower()) if len(w) > 2 and w not in ITALIAN_STOPWORDS]
                                if any(w in lower_t for w in d_words):
                                    target_docs = [d]
                                    break

                        args_card = {"document_ids": [d.id for d in target_docs]} if target_docs else {}
                        card_res = self.execute_tool("show_document_card", args_card, db=db, thread_id=thread_id)
                        c_docs = card_res.get("documents", [])
                        if c_docs:
                            clean_reply = re.sub(r"\[(?:Link per scaricare|Scarica|Download)[^\]]*\]", "la scheda del documento allegata qui sotto", direct_reply, flags=re.IGNORECASE)
                            clean_reply = re.sub(r"per scaricare entrambi i documenti,?\s*dovrai farlo singolarmente\.?", "", clean_reply, flags=re.IGNORECASE).strip()
                            clean_reply = re.sub(r"mi dispiace.*?(?:interfaccia|anomalia|visualizzazione|malfunzionamento).*?(?:\.|\n|$)", "", clean_reply, flags=re.IGNORECASE).strip()
                            clean_reply = re.sub(r"(?:a causa di un|a causa di un'|per via di un).*?(?:interfaccia|anomalia|visualizzazione|malfunzionamento).*?(?:\.|\n|$)", "", clean_reply, flags=re.IGNORECASE).strip()
                            is_apology_or_raw_links = (
                                not clean_reply
                                or len(clean_reply) < 15
                                or any(k in clean_reply.lower() for k in [
                                    "anomalia", "malfunzionamento", "errore di visualizzazione",
                                    "inconveniente", "interfaccia", "problema tecnico", "scaricare direttamente",
                                    "/api/documents", "link di download"
                                ])
                            )
                            if is_apology_or_raw_links:
                                if len(c_docs) > 1:
                                    lines_d = [f"- 📄 **{d['title']}** ({d.get('issuer') or d.get('doc_type', '')})" for d in c_docs]
                                    clean_reply = (
                                        f"📄 Certamente! Ecco subito le schede interattive per ciascun documento qui sotto:\n\n" +
                                        "\n".join(lines_d) +
                                        "\n\nPuoi visualizzarli o scaricarli direttamente con i pulsanti 'Vedi' e 'Scarica'! ⬇️"
                                    )
                                else:
                                    clean_reply = f"📄 Certamente! Ecco subito la scheda per **{c_docs[0]['title']}** qui sotto con i pulsanti per visualizzarlo o scaricarlo direttamente! ⬇️"
                            return ChatResponse(
                                reply=clean_reply,
                                action="show_document_card",
                                data=card_res,
                                documents=c_docs
                            )

                    # Se il modello ha risposto direttamente con testo senza chiamare strumenti:
                    # NIENTE AUTOMATISMI: l'assistente ha scelto autonomamente di rispondere con testo.
                    direct_clean = (direct_reply or "").strip()
                    return ChatResponse(
                        reply=direct_clean,
                        action="REPLY",
                        data=None,
                        documents=None
                    )

        except Exception as e:
            logger.error(f"Errore Agentic loop: {e}")
            return self._fallback_deterministic_response(user_text, lower_t, db, thread_id)

        # Se la chiamata non ha restituito 200 o non è riuscita
        return self._fallback_deterministic_response(user_text, lower_t, db, thread_id)

    def _fallback_deterministic_response(self, user_text: str, lower_t: str, db: Session, thread_id: str) -> ChatResponse:
        """Fallback locale robusto per memorizzazione, ricerca e scadenze in caso di rate-limit API o disconnessione."""
        # 0. Anti-placeholder audio: non cercare MAI "🎤 Messaggio vocale" o simili nel caveau
        clean_audio_check = re.sub(r"[🎤\s]+", "", lower_t)
        if clean_audio_check in ["messaggiovocale", "vocale", "messaggio", ""]:
            return ChatResponse(
                reply="🎤 Non ho rilevato alcun comando vocale comprensibile in questo messaggio. Prova a ripetere scandendo bene le parole o a scrivermi nella chat!",
                action="REPLY"
            )

        # 0. Richieste temporali in caso di fallback offline o errore API
        temp_resp = self._handle_temporal_intent(user_text, lower_t)
        if temp_resp:
            return temp_resp

        # 0. Scompattamento archivio ZIP in caso di fallback offline o errore API
        is_unzip_request = any(k in lower_t for k in [
            "scompatta", "scompattami", "scompattalo", "scompattare",
            "decomprimi", "decomprimimi", "decomprimilo", "decomprimere",
            "unzip", "fai l'unzip", "fai unzip",
            "estrai lo zip", "estrai l'archivio", "estrai archivio", "estrai i file dallo zip", "estrai tutti i file dallo zip"
        ])
        if is_unzip_request:
            from app.services.archive_service import unzip_document_to_vault
            m_id = re.search(r"\b(?:id\s*[:=]?\s*|numero\s+)?(\d+)\b", lower_t)
            target_id = int(m_id.group(1)) if m_id else None
            m_name = re.search(r"[\"']([a-zA-Z0-9_\-.]+\.zip)[\"']", lower_t)
            target_name = m_name.group(1) if m_name else None

            extracted = unzip_document_to_vault(
                db=db,
                document_id=target_id,
                document_title=target_name,
                thread_id=thread_id
            )
            if extracted:
                doc_lines = []
                for idx, d in enumerate(extracted, 1):
                    details = []
                    if d.category_label:
                        details.append(f"📁 *{d.category_label}*")
                    elif d.doc_type:
                        details.append(f"*{d.doc_type.capitalize()}*")
                    if d.amount is not None:
                        details.append(f"💶 **€ {d.amount:.2f}**")
                    if d.due_date:
                        details.append(f"📅 Scadenza: **{d.due_date.strftime('%d/%m/%Y')}**")
                    detail_str = f" ({' • '.join(details)})" if details else ""
                    summary_line = f"\n   _{d.summary}_" if d.summary else ""
                    doc_lines.append(f"**{idx}.** 📄 **{d.title}**{detail_str}{summary_line}")

                reply = (
                    f"📦 Ho scompattato con successo l'archivio ed esaminato ciascun file singolarmente con l'AI. "
                    f"Ecco il dettaglio dei **{len(extracted)} documenti** estratti e catalogati nel Caveau:\n\n"
                    + "\n\n".join(doc_lines) +
                    "\n\nHo inserito ciascun documento nella sezione corrispondente e aggiornato lo scadenzario. Puoi aprirli, visualizzarli o scaricarli direttamente dalle schede qui sotto! ⬇️"
                )
                docs_info = [
                    {
                        "id": d.id,
                        "document_id": d.id,
                        "title": d.title,
                        "issuer": d.issuer,
                        "doc_type": d.doc_type,
                        "category": d.category,
                        "category_label": d.category_label,
                        "category_icon": d.category_icon,
                        "amount": d.amount,
                        "due_date": d.due_date.isoformat() if d.due_date else None,
                        "status": d.status,
                        "summary": d.summary,
                        "file_url": f"/uploads/{Path(d.file_path).name}" if d.file_path else None,
                        "download_url": f"/api/documents/{d.id}/download",
                        "file_type": d.file_type
                    }
                    for d in extracted
                ]
                return ChatResponse(
                    reply=reply,
                    action="show_document_card",
                    data={"extracted_count": len(extracted), "documents": docs_info},
                    documents=docs_info
                )
            else:
                return ChatResponse(
                    reply="⚠️ Non ho trovato alcun archivio ZIP nel caveau da decomprimere, oppure l'archivio non contiene file validi. Puoi caricare un file .zip con l'icona della graffetta 📎 in basso!",
                    action="unzip_vault_archive",
                    data={"success": False}
                )

        # 0a. Eliminazione sicura di documenti o oggetti
        del_resp = self._handle_deletion_intent(user_text, lower_t, db, thread_id=thread_id)
        if del_resp:
            return del_resp

        # 0a. Fallback Google Drive se l'API esterna è irraggiungibile
        drive_resp = self._handle_drive_intent(user_text, lower_t, db, thread_id=thread_id)
        if drive_resp:
            return drive_resp

        # 0a. Collegamento foto/documento a oggetto fisico
        linked_photo_item = self._extract_link_photo_item(user_text)
        if linked_photo_item:
            tool_out = self.execute_tool("link_document_to_item", {"item_name": linked_photo_item}, db=db, thread_id=thread_id)
            if tool_out.get("success"):
                it_name = tool_out.get("item_name", linked_photo_item)
                return ChatResponse(
                    reply=f"✅ Ho associato la foto alla posizione di **{it_name}**! Quando mi chiederai dove si trova, ti mostrerò subito la foto della sua posizione. 📸",
                    action="link_document_to_item",
                    data=tool_out,
                    documents=tool_out.get("documents")
                )
            else:
                return ChatResponse(
                    reply=tool_out.get("error", "Non sono riuscito ad associare la foto all'oggetto."),
                    action="link_document_to_item",
                    data=tool_out
                )

        # 0b. Mostra scheda documento o download
        if any(k in lower_t for k in [
            "scarica", "scaricarla", "scaricarlo", "scaricalo", "scaricala", "scaricarli", "scaricali", "scaricare",
            "download", "fare il download", "voglio scaricare", "voglio il download", "voglio fare il download",
            "apri il documento", "apri il file", "mostramelo", "mostramela", "mostrameli", "fammi vedere il file",
            "fammi vedere il documento", "voglio vederlo", "voglio vederla", "apri il pdf", "mostra la scheda",
            "vedi il documento", "mandami il pdf"
        ]):
            last_asst_msg = (
                db.query(ChatMessage)
                .filter(ChatMessage.thread_id == thread_id, ChatMessage.sender == "assistant")
                .order_by(ChatMessage.id.desc())
                .first()
            )
            target_docs = []
            if last_asst_msg and last_asst_msg.content:
                all_docs = db.query(Document).order_by(Document.created_at.desc()).all()
                for d in all_docs:
                    if d.title and len(d.title) >= 3 and d.title.lower() in last_asst_msg.content.lower():
                        if d not in target_docs:
                            target_docs.append(d)
                if not target_docs:
                    cand_lines = [line.strip(" *🏛️📄:-") for line in last_asst_msg.content.split("\n") if any(k in line.lower() for k in ["f24", "bolletta", "ricevuta", "contratto", "estratto", "certificato", "tessera"])]
                    for cl in cand_lines:
                        s_res = search_vault_documents(db, cl, thread_id=thread_id)
                        if s_res:
                            td = db.query(Document).filter(Document.id == s_res[0]["id"]).first()
                            if td and td not in target_docs:
                                target_docs.append(td)

            if len(target_docs) > 1 and not any(k in lower_t for k in ["entrambi", "tutti", "tutte", "download", "scarica"]):
                for d in target_docs:
                    d_words = [w for w in re.split(r"[^\w]+", d.title.lower()) if len(w) > 2 and w not in ITALIAN_STOPWORDS]
                    if any(w in lower_t for w in d_words):
                        target_docs = [d]
                        break

            args_card = {"document_ids": [d.id for d in target_docs]} if target_docs else {}
            card_res = self.execute_tool("show_document_card", args_card, db=db, thread_id=thread_id)
            c_docs = card_res.get("documents", [])
            if c_docs:
                if len(c_docs) > 1:
                    rep = f"📄 Ecco le schede per i documenti richiesti! Puoi visualizzarli con 'Vedi' o scaricarli direttamente con il pulsante 'Scarica' qui sotto. ⬇️"
                else:
                    rep = f"📄 Ecco la scheda per **{c_docs[0]['title']}**! Puoi visualizzarlo o scaricarlo direttamente dalla scheda qui sotto. ⬇️"
                return ChatResponse(
                    reply=rep,
                    action="show_document_card",
                    data=card_res,
                    documents=c_docs
                )

        # 1. Rinomina documento / foto
        if any(k in lower_t for k in ["chiamalo", "chiamala", "rinomina", "salvalo come", "salvala come", "dagli il nome", "dalle il nome", "dai il nome"]):
            new_title = self._extract_rename_title(user_text)
            if new_title:
                r_out = self.execute_tool("rename_vault_document", {"new_title": new_title}, db=db, thread_id=thread_id)
                if r_out.get("success"):
                    return ChatResponse(
                        reply=f"✅ Ho rinominato il file in '**{r_out['new_title']}**'!",
                        action="rename_vault_document",
                        data=r_out,
                        documents=r_out.get("documents")
                    )

        # 1. Memorizzazione o modifica posizione fisica
        item_n, loc_n = self._extract_item_and_location(user_text)
        if item_n and loc_n:
            db_res = self.execute_tool("store_physical_item", {"item_name": item_n, "primary_location": loc_n}, db, thread_id=thread_id)
            return ChatResponse(reply=f"✅ Memorizzato! Ho salvato la posizione di '{item_n}' in: {loc_n}.", action="store_physical_item", data=db_res)

        # 3. Scadenze in sospeso
        if any(k in lower_t for k in ["scadenz", "da pagare", "quanto devo pagare", "cosa scade"]):
            t_out = self.execute_tool("get_upcoming_deadlines", {}, db, thread_id=thread_id)
            docs = t_out.get("deadlines") or t_out.get("upcoming_documents", [])
            if docs:
                lines = []
                for d in docs[:5]:
                    urg = f" - ⚠️ {d['urgency_label']}" if d.get('urgency_label') else ""
                    lines.append(f"- 📄 **{d['title']}** — {d.get('amount','?')} € scad. {d.get('due_date','?')}{urg}")
                return ChatResponse(reply="📅 Ecco le tue scadenze in sospeso:\n\n" + "\n".join(lines), action="get_upcoming_deadlines", data=t_out, documents=docs)
            return ChatResponse(reply="✅ Non ci sono scadenze o pagamenti in sospeso al momento.", action="get_upcoming_deadlines", data=t_out)

        # 3b. Ispezione dati tabelle e fogli Excel / CSV / Word
        is_content_query = any(k in lower_t for k in [
            "foglio excel", "file excel", "foglio di calcolo", "riga ", "righe", "colonna ", "colonne",
            "cella ", "celle", "tabella", "leggi il file", "leggi il foglio", "leggimi il file",
            "cosa c'è nel file", "cosa ce nel file", "cosa c'è nel foglio", "cosa ce nel foglio",
            "cosa contiene il file", "cosa contiene il foglio", "dati del foglio", "dati di excel"
        ]) or (any(k in lower_t for k in ["riga", "colonna", "cella", "importo", "fatturato", "valore"]) and any(k in lower_t for k in ["excel", "xlsx", "xls", "tabella", "foglio"]))

        if is_content_query:
            c_res = self.execute_tool("read_vault_document_content", {"query": user_text}, db=db, thread_id=thread_id)
            if c_res.get("success"):
                tbl = c_res.get("markdown_table") or c_res.get("content_text") or ""
                doc_title = c_res.get("document_title") or "Documento"
                sheet_info = f" (Foglio: **{c_res.get('active_sheet')}**)" if c_res.get("active_sheet") else ""
                reply_text = (
                    f"📊 **Dati estratti dal file '{doc_title}'**{sheet_info}:\n\n"
                    f"{tbl}\n\n"
                    f"💡 *{c_res.get('summary', '')}*"
                )
                return ChatResponse(
                    reply=reply_text,
                    action="read_vault_document_content",
                    data=c_res
                )

        # 4. Liste o elenchi del caveau
        is_list = (
            (
                any(k in lower_t for k in [
                    "lista", "elenco", "elencami", "quali documenti", "quali oggetti",
                    "mostrami tutti", "mostrami tutte", "mostra tutti", "mostra tutte",
                    "cosa c'è nel caveau", "cosa ce nel caveau", "cosa ho nel caveau", "cosa hai nel caveau",
                    "vedere tutti", "vedere tutte", "tutti i documenti", "tutti gli oggetti", "che oggetti", "che documenti"
                ])
                or lower_t.strip(" !.?") in ["documenti", "oggetti", "tutti i documenti", "tutti gli oggetti", "tutto", "i miei documenti", "i miei oggetti"]
            )
            and not any(k in lower_t for k in ["elimina", "cancella", "rimuovi", "butta", "eliminami", "cancellami", "svuota", "eliminali", "cancellali", "rimuovili"])
        )
        if is_list:
            target = "physical_items" if any(k in lower_t for k in ["oggett", "cose"]) else ("documents" if any(k in lower_t for k in ["document", "file", "bollett", "fattur"]) else "all")
            l_res = self.execute_tool("list_vault_contents", {"target_type": target}, db=db, thread_id=thread_id)
            if target == "physical_items":
                items = l_res.get("physical_items", [])
                if items:
                    lines = [f"- 📍 **{it['item_name']}**: {it['location_str']}" for it in items]
                    rep = "📍 Ecco gli oggetti fisici memorizzati nel caveau:\n\n" + "\n".join(lines)
                else:
                    rep = "Nel caveau non sono presenti oggetti fisici memorizzati al momento. Dimmi pure dove riponi i tuoi oggetti e li registrerò subito! 📍"
                return ChatResponse(reply=rep, action="list_vault_contents", data=l_res)
            elif target == "documents":
                docs = l_res.get("documents", [])
                if docs:
                    lines = [f"- 📄 **{d['title']}** ({d.get('issuer', '')})" for d in docs]
                    rep = f"📄 Ecco i {len(docs)} documenti presenti nel caveau:\n\n" + "\n".join(lines)
                else:
                    rep = "Nel caveau non sono presenti documenti archiviati al momento."
                return ChatResponse(reply=rep, action="list_vault_contents", data=l_res, documents=docs[:5])
            else:
                items = l_res.get("physical_items", [])
                docs = l_res.get("documents", [])
                parts = []
                if docs:
                    lines = [f"- 📄 **{d['title']}** ({d.get('issuer', '')})" for d in docs]
                    parts.append("📄 **Documenti:**\n" + "\n".join(lines))
                if items:
                    lines = [f"- 📍 **{it['item_name']}**: {it['location_str']}" for it in items]
                    parts.append("📍 **Oggetti fisici:**\n" + "\n".join(lines))
                rep = "\n\n".join(parts) if parts else "Nel caveau non sono presenti documenti o oggetti memorizzati al momento."
                return ChatResponse(reply=rep, action="list_vault_contents", data=l_res, documents=docs[:5])

        # 4. Ricerca intelligente nel caveau (oggetti fisici e documenti)
        search_q = re.sub(
            r"^(?:dov'è|dov'e|dove ho messo|dove sono|dove|cerca|trovami|trova|dammi|mostrami|apri|visualizza|prendi|scarica|vedi)\s*(?:il|la|lo|le|i|l'|un|una|uno)?\s*",
            "", lower_t
        ).strip(" ?.")
        clean_q = search_q or user_text
        if len(clean_q) >= 2:
            s_res = self.execute_tool("search_vault", {"query": clean_q}, db=db, thread_id=thread_id)
            f_docs = s_res.get("found_documents", [])
            f_items = s_res.get("found_physical_items", [])
            is_where_intent = any(k in lower_t for k in ["dov'è", "dov'e", "dove è", "dove sono", "dove si trova", "dove si trovano", "dove ho messo", "dove ho riposto", "dove ho lasciato", "dove sta", "dove stanno"])
            if is_where_intent and f_items:
                it = f_items[0]
                loc = it['primary_location'] + (f" ({it['detailed_location']})" if it.get('detailed_location') else "")
                linked_d = None
                if it.get("document_id"):
                    d_rec = db.query(Document).filter(Document.id == it["document_id"]).first()
                    if d_rec:
                        fn = Path(d_rec.file_path).name if d_rec.file_path else ""
                        linked_d = {
                            "id": d_rec.id, "document_id": d_rec.id, "title": d_rec.title,
                            "issuer": d_rec.issuer, "amount": d_rec.amount,
                            "due_date": d_rec.due_date.isoformat() if d_rec.due_date else None,
                            "summary": d_rec.summary,
                            "file_url": f"/uploads/{fn}" if fn else None,
                            "download_url": f"/api/documents/{d_rec.id}/download",
                            "file_type": d_rec.file_type
                        }
                elif it.get("image_url"):
                    linked_d = {
                        "id": it.get("item_id"), "document_id": it.get("item_id"), "title": f"Foto {it['item_name']}",
                        "file_url": it["image_url"], "download_url": it["image_url"], "file_type": "image"
                    }
                photo_note = "\n📸 Ho allegato la foto della posizione qui sotto!" if (it.get("has_photo") or linked_d) else ""
                return ChatResponse(
                    reply=f"📍 **{it['item_name']}** si trova in: {loc}.{photo_note}",
                    action="search_vault",
                    data=s_res,
                    documents=[linked_d] if linked_d else None
                )

            if f_docs:
                if len(f_docs) == 1:
                    d = f_docs[0]
                    amt_str = f" ({d['amount']:.2f} €)" if d.get('amount') else ""
                    due_str = f" - scadenza: {d['due_date']}" if d.get('due_date') else ""
                    return ChatResponse(
                        reply=f"📄 Ho trovato il documento **{d['title']}**{amt_str}{due_str}:\n💡 {d.get('summary', '')}",
                        action="show_document_card",
                        data=s_res,
                        documents=[d]
                    )
                else:
                    lines = [f"- 📄 **{d['title']}** ({d.get('issuer') or d.get('doc_type', '')})" for d in f_docs]
                    rep = (
                        f"📄 Ho trovato i seguenti **{len(f_docs)} documenti** nel caveau:\n\n" +
                        "\n".join(lines) +
                        "\n\nEcco le schede con i pulsanti 'Vedi' e 'Scarica' per ciascun file qui sotto! ⬇️"
                    )
                    return ChatResponse(
                        reply=rep,
                        action="show_document_card",
                        data=s_res,
                        documents=f_docs
                    )
            if f_items:
                it = f_items[0]
                loc = it['primary_location'] + (f" ({it['detailed_location']})" if it.get('detailed_location') else "")
                linked_d = None
                if it.get("document_id"):
                    d_rec = db.query(Document).filter(Document.id == it["document_id"]).first()
                    if d_rec:
                        fn = Path(d_rec.file_path).name if d_rec.file_path else ""
                        linked_d = {
                            "id": d_rec.id, "document_id": d_rec.id, "title": d_rec.title,
                            "issuer": d_rec.issuer, "amount": d_rec.amount,
                            "due_date": d_rec.due_date.isoformat() if d_rec.due_date else None,
                            "summary": d_rec.summary,
                            "file_url": f"/uploads/{fn}" if fn else None,
                            "download_url": f"/api/documents/{d_rec.id}/download",
                            "file_type": d_rec.file_type
                        }
                elif it.get("image_url"):
                    linked_d = {
                        "id": it.get("item_id"), "document_id": it.get("item_id"), "title": f"Foto {it['item_name']}",
                        "file_url": it["image_url"], "download_url": it["image_url"], "file_type": "image"
                    }
                photo_note = "\n📸 Ho allegato la foto della posizione qui sotto!" if (it.get("has_photo") or linked_d) else ""
                return ChatResponse(
                    reply=f"📍 **{it['item_name']}** si trova in: {loc}.{photo_note}",
                    action="search_vault",
                    data=s_res,
                    documents=[linked_d] if linked_d else None
                )

        if clean_audio_check in ["messaggiovocale", "vocale"]:
            return ChatResponse(
                reply="🎤 Non ho rilevato alcun comando vocale comprensibile in questo messaggio. Prova a ripetere scandendo bene le parole o a scrivermi nella chat!",
                action="REPLY"
            )

        return ChatResponse(
            reply=f"Non ho trovato nessun documento o oggetto corrispondente a '{user_text}' nel tuo caveau. Puoi chiedermi dove si trova un oggetto, cercare un documento o verificare le scadenze!",
            action="REPLY"
        )


AgentService = AgenticChatService

