import sys
import os
import re
from pathlib import Path
from contextlib import contextmanager

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from datetime import date
from typing import Optional, List, Dict, Any
from mcp.server.mcpserver import MCPServer
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.models.database import (
    get_db,
    init_db,
    get_engine,
    get_session_maker,
    Document,
    PhysicalItem,
    WatchedFolder,
    GoogleDriveCredential,
)
from app.services.search_service import search_vault_documents, search_vault_items
from app.services.agent_service import get_current_date_info, categorize_deadline
from app.services.drive_service import resolve_drive_folder_path
from app.version import APP_VERSION

AGENT_ROLE_AND_INSTRUCTIONS = """Sei l'assistente AI esecutivo e intelligente di 'Dove lo AI messo', un caveau digitale crittografato e inventario fisico per famiglie e professionisti italiani.

IL TUO RUOLO E LA TUA MISSIONE:
Operi come un concierge privato, fidato, rassicurante e impeccabile. Gestisci con la massima precisione:
1. I documenti personali, fiscali e amministrativi dell'utente (730, F24, bollette, contratti, fatture, referti, certificati, fogli Excel, documenti Word, archivi ZIP).
2. L'inventario e la posizione esatta degli oggetti fisici distribuiti in casa, studio, ufficio o garage (stanze, mobili, cassetti, ripiani, con relative foto dimostrative).
3. Lo scadenzario delle imposte e delle utenze con calcolo puntuale dei giorni rimanenti e prevenzione delle more.
4. La sincronizzazione cloud con Google Drive e il monitoraggio delle cartelle locali del computer (es. cartella Download).

TONO E STILE PROFESSIONALE:
- Lingua italiana naturale, elegante, fluida, rassicurante e cortese.
- Usa un "tu" professionale e cordiale (stile executive concierge).
- DIVIETO ASSOLUTO di mostrare gergo tecnico di programmazione o database verso l'utente (mai dire 'ID 83', 'query SQL', 'foreign key', 'record SQLite', 'tabella physical_items').
- Sii trasparente: il database reale è la sola fonte di verità. Se un elemento non è presente, comunicalo con garbo e offri assistenza per memorizzarlo o caricarlo.

MATRICE DECISIONALE DEI WIDGET E DELLE SCHEDE DOCUMENTO (AUTONOMIA & NESSUN AUTOMATISMO):
Spetta a te decidere in piena autonomia quando ha senso mostrare widget/schede grafiche interattive e quando NO.
A. QUANDO HA SENSO MOSTRARE I WIDGET / SCHEDE DOCUMENTO:
   - Quando l'utente chiede esplicitamente di trovare, vedere, consultare, aprire o scaricare uno o più documenti specifici (es. 'dammi la bolletta Enel', 'mostrami la tessera sanitaria', 'scarica il 730', 'cerca il contratto d'affitto', 'apri la fattura', 'scaricali entrambi').
   - Quando l'utente richiede un'azione cumulativa (es. 'scaricali tutti e due', 'mostrami tutte le bollette di ottobre'): genera subito le schede per ciascun file, senza costringerlo a farlo singolarmente.
   - Al termine dell'estrazione di un archivio ZIP: genera le schede interattive di tutti i file scompattati nel caveau.
   - Per cancellazioni o azioni critiche: genera il widget interattivo di conferma eliminazione con i pulsanti di sicurezza.
B. QUANDO NON HA SENSO E VIETATO MOSTRARE WIDGET:
   - Domande generali, informative, di aiuto o di presentazione delle tue capacità (es. 'cosa puoi fare?', 'chi sei?', 'come funzioni?', 'cosa sai fare?', 'a cosa servi?', 'aiuto', saluti iniziali).
   - Quando citi documenti, bollette o ricevute come mero ESEMPIO descrittivo per spiegare cosa sai fare: ZERO widget!
   - Ricerca di posizioni fisiche di oggetti privi di foto associata (es. 'dove sono le chiavi?'): rispondi con indicazione testuale precisa.
   - Richieste di calcoli o totali di spesa ('quanto ho speso di luce quest'anno?'): rispondi con il calcolo numerico e il riassunto testuale.
   - Chiacchierata informale, chiarimenti e domande di disambiguazione.

GUIDA PER SITUAZIONI SPECIFICHE:
1. Ricerca Documenti: individua subito i file con `search_vault`, esponi emittente, importo, scadenza e sintesi, e fornisci i link per visualizzazione e download.
2. Oggetti Fisici: cerca con `search_vault` o salva con `store_physical_item`. Specifica sempre stanza e cassetto/ripiano.
3. Foto collegate agli oggetti: con `link_document_to_item` associa foto di scontrini o posizioni agli oggetti fisici.
4. Scadenze: usa `get_upcoming_deadlines`, calcola l'urgenza esatta rispetto alla data odierna, avvisando con prontezza delle scadenze imminenti o scadute.
5. File Office: per fogli Excel (.xlsx/.xls) e Word (.docx), informa l'utente che cliccando su [👁️ Vedi] potrà consultare tabelle stilizzate e testi formattati direttamente a schermo intero.
6. Archivi ZIP: usa `create_zip_archive` per raggruppare file e `unzip_vault_archive` per estrarli e catalogarli automaticamente nel caveau.
7. Google Drive: usa `get_google_drive_status`. Conosci le modalità 'dual' e 'cloud_only', l'alberatura `DoveLoAIMesso / <Anno> / <Categoria> / ...` e il pulsante [Drive ↗]. Non dire mai di non avere accesso a Drive!
8. Cartelle PC: usa `scan_local_folder`, `list_watched_folders` e `open_local_file_in_explorer` per aprire i file nativamente in Windows Explorer.
9. Sicurezza: il caveau usa crittografia a riposo AES-128 / Fernet, blocco con scarico chiavi dalla RAM e wipe database protetto da password.
"""

mcp = MCPServer(
    "dove-lo-ai-messo",
    description="Caveau intelligente per documenti, bollette, scadenze, file office, archivi zip e oggetti fisici con assistenza AI",
    instructions=AGENT_ROLE_AND_INSTRUCTIONS
)

@contextmanager
def _get_db_session():
    init_db()
    engine = get_engine()
    SessionLocal = get_session_maker(engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()

# ==============================================================================
# PROMPTS MCP
# ==============================================================================

@mcp.prompt("vault_assistant_instructions")
def vault_assistant_instructions() -> str:
    """Istruzioni operative complete per guidare l'assistente AI professionale nel supporto a documenti, scadenze, oggetti fisici e sicurezza."""
    return AGENT_ROLE_AND_INSTRUCTIONS

@mcp.prompt("assistant_behavior_and_widget_rules")
def assistant_behavior_and_widget_rules() -> str:
    """Guida approfondita sul comportamento professionale dell'assistente e matrice decisionale rigorosa sull'uso dei widget/schede."""
    return """MATRICE DECISIONALE WIDGET & REGOLE COMPORTAMENTALI:

1. AUTONOMIA DECISIONALE ASSOLUTA:
L'assistente valuta il contesto reale della conversazione per stabilire se mostrare o meno schede interattive (widget). Non vi sono automatismi ciechi.

2. CASISTICHE DETTAGLIATE WIDGET:
- Mostra widget (`show_document_card`):
  * L'utente chiede un documento per nome o tipo con intenzione di aprirlo, scaricarlo o consultarlo.
  * L'utente chiede 'scaricali entrambi', 'mostrami tutti e due', 'scarica tutti i 730'.
  * Dopo la decompressione di un archivio ZIP.
  * In caso di eliminazione con `delete_vault_record` per consentire la conferma sicura.
- NON mostrare MAI widget:
  * Domande meta ('cosa puoi fare?', 'chi sei?', 'come funzioni?').
  * Esempi illustrativi di testo ('ad esempio puoi caricare una bolletta Enel').
  * Domande su posizioni fisiche senza foto.
  * Domande su somme/statistiche numeriche.

3. ELEGANZA COMUNICATIVA:
Rispondi con calore, precisione e accuratezza, proteggendo la privacy dell'utente e fornendo sempre informazioni esaustive."""

@mcp.prompt("google_drive_sync_guidelines")
def google_drive_sync_guidelines() -> str:
    """Linee guida architetturali e operative per la sincronizzazione cloud con Google Drive in 'Dove lo AI messo'."""
    return """LINEE GUIDA GOOGLE DRIVE CLOUD SYNC:
1. Cartella Principale: 'DoveLoAIMesso' situata nella root di Google Drive dell'utente.
2. Modalità di Archiviazione:
   - 'dual': Conserva una copia cifrata in locale nel caveau e carica una copia organizzata su Google Drive.
   - 'cloud_only': Elimina la copia fisica da locale e conserva solo il file su Google Drive (zero spazio su disco, visualizzabile via cloud).
3. Struttura ad Albero Dinamica:
   - Con scadenza (Bollette, Tributi, F24): `DoveLoAIMesso / <Anno> / <Categoria> / <File>`
   - Senza scadenza (Documenti Personali, Contratti, Foto): `DoveLoAIMesso / <Categoria> / <File>`
4. Categorie Standard: 'Bollette & Utenze', 'Fisco & Tasse', 'Fatture & Spese', 'Contratti & Polizze', 'Documenti & Foto'.
5. Apertura: Ogni documento sincronizzato su Drive dispone del pulsante [Drive ↗] con link diretto `drive_web_url`."""


# ==============================================================================
# TOOL MCP: DATA, CONTESTO, STATISTICHE & VERSIONE
# ==============================================================================

@mcp.tool()
def get_current_date() -> str:
    """Restituisce la data, l'ora, il giorno della settimana e l'anno corrente (es. 'Lunedì 14 Settembre 2026'). Utile per verificare le scadenze."""
    info = get_current_date_info()
    return f"Oggi è {info['formatted_italian']} (Data ISO: {info['date']}, ore {info['current_time']})."

@mcp.tool()
def get_app_version() -> str:
    """Restituisce la versione attiva dell'applicazione 'Dove lo AI messo', il nome e le regole di conformità SemVer."""
    return f"Versione dell'applicazione: v{APP_VERSION} ('Dove lo AI messo' — Executive AI Vault)."

@mcp.tool()
def get_vault_stats() -> str:
    """Restituisce le statistiche generali e KPI del Caveau: totale documenti, oggetti fisici, scadenze in sospeso, totale da pagare in euro e stato Google Drive."""
    with _get_db_session() as db:
        docs_count = db.query(Document).count()
        items_count = db.query(PhysicalItem).count()
        unpaid = db.query(Document).filter(Document.status == "da_pagare").all()
        quietanzati = db.query(Document).filter(Document.status.in_(["pagato", "quietanzato", "archiviato"])).count()
        total_unpaid = sum(d.amount or 0.0 for d in unpaid)
        
        today = date.today()
        overdue = sum(1 for d in unpaid if d.due_date and (d.due_date - today).days < 0)
        due_soon = sum(1 for d in unpaid if d.due_date and 0 <= (d.due_date - today).days <= 7)
        
        watched_count = db.query(WatchedFolder).filter(WatchedFolder.is_active == True).count()
        cred = db.query(GoogleDriveCredential).first()
        drive_status = f"Collegato ({cred.storage_mode})" if cred else "Non collegato"
        
        return (
            f"=== STATISTICHE & KPI CAVEAU (v{APP_VERSION}) ===\n"
            f"- Documenti totali archiviati: {docs_count}\n"
            f"- Oggetti fisici catalogati: {items_count}\n"
            f"- Scadenze e bollette da pagare: {len(unpaid)} (Totale: {total_unpaid:.2f} €)\n"
            f"  * ⚠️ Scadute: {overdue}\n"
            f"  * ⏰ In scadenza entro 7 giorni: {due_soon}\n"
            f"- Documenti quietanzati/archiviati: {quietanzati}\n"
            f"- Cartelle PC monitorate attive: {watched_count}\n"
            f"- Google Drive Cloud Sync: {drive_status}"
        )

@mcp.tool()
def get_vault_context() -> str:
    """Restituisce il ruolo e le istruzioni dell'agente, insieme al contesto completo e aggiornato del Caveau (data odierna, ultimi documenti, oggetti e scadenze)."""
    with _get_db_session() as db:
        date_info = get_current_date_info()
        docs = db.query(Document).order_by(Document.id.desc()).limit(6).all()
        items = db.query(PhysicalItem).order_by(PhysicalItem.id.desc()).limit(10).all()
        unpaid = db.query(Document).filter(Document.status == "da_pagare").all()

        today = date.today()
        overdue_count = sum(1 for d in unpaid if d.due_date and (d.due_date - today).days < 0)
        due_soon_count = sum(1 for d in unpaid if d.due_date and 0 <= (d.due_date - today).days <= 7)

        output = [
            "=== RUOLO E COMPITI DELL'AGENTE (DOVE LO AI MESSO) ===",
            f"DATA E ORA ATTUALE: {date_info['formatted_italian']}, ore {date_info['current_time']} (ISO: {date_info['date']}) | Versione: v{APP_VERSION}",
            "Sei l'assistente AI dedicato del Caveau. Aiuti gli utenti a:",
            "1. TROVARE DOCUMENTI E FILE (PDF, immagini, fogli Excel, documenti Word, archivi ZIP) con anteprima e download.",
            "2. MONITORARE LE SCADENZE E LE UTENZE distinguendo tra pagamenti scaduti, imminenti e quietanzati.",
            "3. RITROVARE OGGETTI FISICI indicando stanze, mobili e cassetti con relative foto.",
            "4. MEMORIZZARE ED AGGIORNARE tempestivamente le posizioni comunicate.",
            "5. GESTIRE GOOGLE DRIVE CLOUD SYNC E LE CARTELLE MONITORATE DEL PC.",
            "",
            "=== CONTESTO ATTUALE DEL CAVEAU (DATI IN TEMPO REALE) ===",
            "## Ultimi Documenti Archiviati:"
        ]

        if docs:
            for d in docs:
                amount_str = f" | Importo: {d.amount:.2f} €" if d.amount is not None else ""
                due_str = f" | Scadenza: {d.due_date}" if d.due_date else ""
                fn = Path(d.file_path).name if d.file_path else "file"
                output.append(f"- [ID {d.id}] **{d.title}** ({d.doc_type} - {d.issuer or 'N/D'}){amount_str}{due_str}")
                output.append(f"  File: /uploads/{fn} | Download: /api/documents/{d.id}/download")
                output.append(f"  Sintesi: {d.summary[:180]}...")
        else:
            output.append("Nessun documento presente.")

        output.append("\n## Posizioni Oggetti Fisici Memorizzati:")
        if items:
            for it in items:
                loc = it.primary_location + (f" -> {it.detailed_location}" if it.detailed_location else "")
                has_photo = " 📸 [Foto collegata]" if it.image_path else ""
                output.append(f"- **{it.item_name}**: {loc} (categoria: {it.category or 'generico'}){has_photo}")
        else:
            output.append("Nessun oggetto fisico registrato.")

        deadlines_summary = f"\n## Scadenze da pagare: {len(unpaid)} in totale"
        if overdue_count > 0 or due_soon_count > 0:
            deadlines_summary += f" (⚠️ {overdue_count} scadute, {due_soon_count} in scadenza entro 7 giorni)."
        else:
            deadlines_summary += " (nessuna scadenza critica immediata)."
        output.append(deadlines_summary)
        return "\n".join(output)


# ==============================================================================
# TOOL MCP: RICERCA, CONSULTAZIONE & ELENCO CONTENUTI
# ==============================================================================

@mcp.tool()
def search_vault(query: str) -> str:
    """Cerca nel caveau documenti e oggetti fisici con supporto per singolari/plurali, sinonimi, tolleranza ai refusi e link per visualizzazione e download."""
    with _get_db_session() as db:
        docs = search_vault_documents(db, query)
        items = search_vault_items(db, query)

        result = []
        if docs:
            doc_lines = []
            for d in docs[:5]:
                amt = f" | Importo: {d['amount']:.2f} €" if d.get('amount') is not None else ""
                due = f" | Scadenza: {d['due_date']}" if d.get('due_date') else ""
                dl_url = d.get('download_url') or f"/api/documents/{d['document_id']}/download"
                drive_tag = f" | [Drive ↗: {d.get('drive_web_url')}]" if d.get('drive_web_url') else ""
                doc_lines.append(
                    f"- Documento #{d['document_id']}: **{d['title']}** ({d.get('doc_type', 'generico')}) - Emittente: {d.get('issuer', 'N/D')}{amt}{due}{drive_tag}\n"
                    f"  Anteprima: {d.get('file_url', 'N/D')} | Link Download Diretto: {dl_url}\n"
                    f"  Sintesi: {d.get('summary', '')}"
                )
            result.append("Documenti trovati (esponi i dettagli e fornisci all'utente la possibilità di aprirli e scaricarli):\n" + "\n".join(doc_lines))

        if items:
            item_lines = []
            for it in items[:5]:
                loc = it['primary_location'] + (f" ({it['detailed_location']})" if it.get("detailed_location") else "")
                photo_info = f" | Foto: {it.get('image_url')}" if it.get("has_photo") else ""
                item_lines.append(f"- Oggetto: **{it['item_name']}** -> Posizione: {loc}{photo_info}")
            result.append("Oggetti fisici trovati:\n" + "\n".join(item_lines))

        if not result:
            return f"Nessun risultato trovato nel caveau per '{query}'. Invita gentilmente l'utente a verificare la dicitura o a memorizzare/caricare l'elemento."
        return "\n\n".join(result)

@mcp.tool()
def list_vault_contents(target_type: str = "all") -> str:
    """Elenca tutti i documenti o tutti gli oggetti fisici memorizzati nel caveau. Usalo quando l'utente chiede la lista, l'elenco o cosa c'è salvato."""
    with _get_db_session() as db:
        output = []
        
        if target_type in ["all", "documents"]:
            docs = db.query(Document).order_by(Document.id.desc()).all()
            output.append(f"=== DOCUMENTI NEL CAVEAU ({len(docs)} totali) ===")
            if docs:
                for d in docs:
                    amt = f" - {d.amount:.2f} €" if d.amount is not None else ""
                    due = f" (Scadenza: {d.due_date})" if d.due_date else ""
                    status_str = f" [{d.status}]"
                    output.append(f"- [ID {d.id}] **{d.title}** ({d.doc_type}){amt}{due}{status_str} | Download: /api/documents/{d.id}/download")
            else:
                output.append("Nessun documento archiviato nel caveau.")

        if target_type in ["all", "physical_items"]:
            items = db.query(PhysicalItem).order_by(PhysicalItem.id.desc()).all()
            output.append(f"\n=== OGGETTI FISICI NEL CAVEAU ({len(items)} totali) ===")
            if items:
                for it in items:
                    loc = it.primary_location + (f" -> {it.detailed_location}" if it.detailed_location else "")
                    photo_tag = " 📸 [Con foto]" if it.image_path else ""
                    output.append(f"- [ID {it.id}] **{it.item_name}**: {loc} (categoria: {it.category or 'generico'}){photo_tag}")
            else:
                output.append("Nessun oggetto fisico registrato.")

        return "\n".join(output)

@mcp.tool()
def get_recent_vault_documents(limit: int = 3) -> str:
    """Recupera gli ultimi documenti caricati o acquisiti nel caveau con anteprima e dettagli."""
    with _get_db_session() as db:
        docs = db.query(Document).order_by(Document.id.desc()).limit(max(1, min(limit, 20))).all()
        if not docs:
            return "Non ci sono documenti registrati di recente nel caveau."
        
        lines = [f"Ultimi {len(docs)} documenti acquisiti nel caveau:"]
        for d in docs:
            amt = f" | {d.amount:.2f} €" if d.amount is not None else ""
            due = f" | Scadenza: {d.due_date}" if d.due_date else ""
            fn = Path(d.file_path).name if d.file_path else ""
            lines.append(
                f"- [ID {d.id}] **{d.title}** ({d.doc_type} - {d.issuer or 'N/D'}){amt}{due}\n"
                f"  Download: /api/documents/{d.id}/download | File: /uploads/{fn}\n"
                f"  Sintesi: {d.summary[:150]}..."
            )
        return "\n".join(lines)


# ==============================================================================
# TOOL MCP: OGGETTI FISICI & FOTO
# ==============================================================================

@mcp.tool()
def store_physical_item(
    item_name: str,
    primary_location: str,
    detailed_location: str = "",
    category: str = "generico",
    document_id: Optional[int] = None
) -> str:
    """Memorizza, aggiorna o sposta la posizione di un oggetto fisico nel caveau, con eventuale collegamento a una foto/documento."""
    with _get_db_session() as db:
        cleaned = item_name.strip().capitalize()
        existing = db.query(PhysicalItem).filter(PhysicalItem.item_name.ilike(cleaned)).first()
        
        img_path = None
        if document_id:
            doc = db.query(Document).filter(Document.id == document_id).first()
            if doc and doc.file_path:
                img_path = doc.file_path

        if existing:
            existing.primary_location = primary_location
            if detailed_location:
                existing.detailed_location = detailed_location
            if category and category != "generico":
                existing.category = category
            if img_path:
                existing.image_path = img_path
                existing.document_id = document_id
            item = existing
        else:
            item = PhysicalItem(
                item_name=cleaned,
                primary_location=primary_location,
                detailed_location=detailed_location or None,
                category=category,
                document_id=document_id,
                image_path=img_path
            )
            db.add(item)
        
        db.commit()
        db.refresh(item)
        loc = item.primary_location + (f" ({item.detailed_location})" if item.detailed_location else "")
        photo_str = " (con foto/documento associato)" if item.image_path else ""
        return f"Memorizzato con successo nel caveau: '{item.item_name}' in {loc}{photo_str}."

@mcp.tool()
def link_document_to_item(
    item_name: str,
    item_id: Optional[int] = None,
    document_id: Optional[int] = None,
    document_title: str = ""
) -> str:
    """Collega una foto, scontrino o documento presente nel caveau a un oggetto fisico memorizzato."""
    with _get_db_session() as db:
        item = None
        if item_id:
            item = db.query(PhysicalItem).filter(PhysicalItem.id == item_id).first()
        if not item and item_name:
            item = db.query(PhysicalItem).filter(PhysicalItem.item_name.ilike(item_name.strip())).first()
            if not item:
                matches = search_vault_items(db, item_name)
                if matches:
                    item_mid = matches[0].get("item_id") or matches[0].get("id")
                    item = db.query(PhysicalItem).filter(PhysicalItem.id == item_mid).first()

        if not item:
            return f"Impossibile trovare l'oggetto fisico '{item_name}' nel caveau per collegarvi la foto."

        doc = None
        if document_id:
            doc = db.query(Document).filter(Document.id == document_id).first()
        elif document_title:
            doc_matches = search_vault_documents(db, document_title)
            if doc_matches:
                doc = db.query(Document).filter(Document.id == doc_matches[0]["document_id"]).first()
        else:
            doc = db.query(Document).order_by(Document.id.desc()).first()

        if not doc:
            return f"Nessun documento o foto trovato nel caveau da associare all'oggetto '{item.item_name}'."

        item.document_id = doc.id
        if doc.file_path:
            item.image_path = doc.file_path
        db.commit()
        return f"Foto/documento '{doc.title}' collegato con successo all'oggetto '{item.item_name}'."


# ==============================================================================
# TOOL MCP: SCADENZARIO & GESTIONE DOCUMENTI
# ==============================================================================

@mcp.tool()
def get_upcoming_deadlines(query: str = "") -> str:
    """Recupera le scadenze e bollette da pagare con conteggio dei giorni rimanenti, categoria di urgenza e link di download."""
    with _get_db_session() as db:
        q = db.query(Document).filter(Document.status == "da_pagare")
        if query.strip():
            q_term = f"%{query.strip()}%"
            q = q.filter(or_(Document.title.ilike(q_term), Document.issuer.ilike(q_term), Document.doc_type.ilike(q_term)))
        
        unpaid = q.order_by(Document.due_date.asc().nulls_last()).all()
        if not unpaid:
            filter_str = f" per '{query}'" if query else ""
            return f"Non ci sono scadenze o bollette in sospeso nel caveau{filter_str}. Tutti i pagamenti risultano quietanzati!"
        
        today = date.today()
        lines = []
        total_amount = 0.0
        for d in unpaid:
            cat = categorize_deadline(d.due_date, today)
            urg_tag = f" — ⚠️ {cat['urgency_label']}" if d.due_date else ""
            amt = d.amount or 0.0
            total_amount += amt
            lines.append(
                f"- **{d.title}** ({d.issuer or 'N/D'}): {amt:.2f} € entro il {d.due_date or 'data non definita'}{urg_tag} | Download: /api/documents/{d.id}/download"
            )
        date_info = get_current_date_info()
        return f"Scadenze e bollette da pagare in sospeso (Oggi: {date_info['formatted_italian']} - Totale: {total_amount:.2f} €):\n" + "\n".join(lines)

@mcp.tool()
def rename_vault_document(new_title: str, document_id: Optional[int] = None) -> str:
    """Rinomina un documento o foto salvato nel caveau, assegnando un nuovo titolo personalizzato."""
    with _get_db_session() as db:
        doc = None
        if document_id:
            doc = db.query(Document).filter(Document.id == document_id).first()
        else:
            doc = db.query(Document).order_by(Document.id.desc()).first()

        if not doc:
            return "Nessun documento trovato da rinominare."

        old_title = doc.title
        doc.title = new_title.strip()
        db.commit()
        return f"Documento #{doc.id} rinominato con successo da '{old_title}' a '{doc.title}'."

@mcp.tool()
def recategorize_vault_document(
    category_label: str,
    document_id: Optional[int] = None,
    document_title: str = "",
    category: str = "",
    category_icon: str = ""
) -> str:
    """Modifica o assegna la sezione/categoria tematica di un documento nel caveau (es. 'Canzoni & Testi Musicali', 'Ricette & Cucina', 'Appunti Universitari', 'Automobili & Manutenzione', 'Utenze & Bollette'). Può creare qualsiasi nuova sezione a tua discrezione."""
    with _get_db_session() as db:
        doc = None
        if document_id:
            doc = db.query(Document).filter(Document.id == document_id).first()
        elif document_title:
            matches = search_vault_documents(db, document_title)
            if matches:
                doc = db.query(Document).filter(Document.id == matches[0]["id"]).first()
        if not doc:
            doc = db.query(Document).order_by(Document.id.desc()).first()

        if not doc:
            return "Nessun documento trovato da ricatalogare nel caveau."

        old_label = doc.category_label or "Non categorizzato"
        clean_label = category_label.strip()
        doc.category_label = clean_label

        if category and category.strip():
            doc.category = category.strip().lower()
        else:
            doc.category = re.sub(r"[^a-zA-Z0-9]+", "_", clean_label.lower()).strip("_")

        if category_icon and category_icon.strip():
            doc.category_icon = category_icon.strip()
        elif not doc.category_icon or doc.category_icon == "fa-folder-closed":
            cl_low = clean_label.lower()
            if any(k in cl_low for k in ["canzon", "music", "brano", "spartit"]):
                doc.category_icon = "fa-music"
            elif any(k in cl_low for k in ["ricett", "cucin", "piatt"]):
                doc.category_icon = "fa-utensils"
            elif any(k in cl_low for k in ["universit", "studio", "laurea", "appunt"]):
                doc.category_icon = "fa-graduation-cap"
            elif any(k in cl_low for k in ["auto", "veicol", "motoc"]):
                doc.category_icon = "fa-car"
            elif any(k in cl_low for k in ["animal", "veterinari", "cane", "gatto"]):
                doc.category_icon = "fa-paw"
            elif any(k in cl_low for k in ["viagg", "vacanz", "volo"]):
                doc.category_icon = "fa-plane"
            elif any(k in cl_low for k in ["bollett", "utenz", "luce", "gas"]):
                doc.category_icon = "fa-bolt"
            elif any(k in cl_low for k in ["fisco", "tribut", "f24"]):
                doc.category_icon = "fa-landmark"
            else:
                doc.category_icon = "fa-folder-open"

        db.commit()
        return f"Documento #{doc.id} '{doc.title}' spostato con successo da '{old_label}' alla sezione '{doc.category_label}' (icona: {doc.category_icon})."

@mcp.tool()
def delete_vault_record(
    target_type: str,
    title: str,
    target_id: Optional[int] = None,
    category: Optional[str] = None
) -> str:
    """Elimina uno o più documenti o posizioni fisiche dal caveau ('document', 'physical_item' o 'bulk_documents')."""
    with _get_db_session() as db:
        if target_type == "document":
            doc = None
            if target_id:
                doc = db.query(Document).filter(Document.id == target_id).first()
            elif title:
                matches = search_vault_documents(db, title)
                if matches:
                    doc = db.query(Document).filter(Document.id == matches[0]["document_id"]).first()
            if not doc:
                return f"Documento '{title}' non trovato per l'eliminazione."
            t = doc.title
            db.delete(doc)
            db.commit()
            return f"Documento '{t}' eliminato definitivamente dal caveau."

        elif target_type == "physical_item":
            item = None
            if target_id:
                item = db.query(PhysicalItem).filter(PhysicalItem.id == target_id).first()
            elif title:
                matches = search_vault_items(db, title)
                if matches:
                    item_mid = matches[0].get("item_id") or matches[0].get("id")
                    item = db.query(PhysicalItem).filter(PhysicalItem.id == item_mid).first()
            if not item:
                return f"Oggetto fisico '{title}' non trovato per l'eliminazione."
            name = item.item_name
            db.delete(item)
            db.commit()
            return f"Posizione dell'oggetto '{name}' rimossa dal caveau."

        elif target_type == "bulk_documents":
            q = db.query(Document)
            if category and category.lower() != "all":
                q = q.filter(Document.doc_type.ilike(f"%{category.lower()}%"))
            docs_to_del = q.all()
            count = len(docs_to_del)
            for d in docs_to_del:
                db.delete(d)
            db.commit()
            return f"Eliminati con successo {count} documenti dal caveau (filtro: {category or 'tutti'})."

        return f"Tipo di eliminazione non riconosciuto: '{target_type}'."


# ==============================================================================
# TOOL MCP: ARCHIVI ZIP (CREAZIONE & DECOMPRESSIONE)
# ==============================================================================

@mcp.tool()
def create_zip_archive(query: str = "", category: str = "", archive_name: str = "") -> str:
    """Crea e comprime uno o più documenti del caveau in un nuovo file archivio .ZIP scaricabile."""
    with _get_db_session() as db:
        from app.services.archive_service import create_zip_from_documents
        zip_doc = create_zip_from_documents(
            db=db,
            query=query or None,
            category=category or None,
            archive_title=archive_name or None
        )
        if not zip_doc:
            return "Nessun documento trovato corrispondente ai criteri per creare l'archivio ZIP."
        return (
            f"Archivio ZIP '{zip_doc.title}' creato con successo nel caveau!\n"
            f"- ID Documento: {zip_doc.id}\n"
            f"- Download diretto: /api/documents/{zip_doc.id}/download\n"
            f"- Sintesi: {zip_doc.summary}"
        )

@mcp.tool()
def unzip_vault_archive(document_id: Optional[int] = None, document_title: str = "") -> str:
    """Estrae e scompatta un archivio ZIP presente nel caveau, indicizzando automaticamente tutti i documenti, immagini, fogli Excel e Word al suo interno."""
    with _get_db_session() as db:
        from app.services.archive_service import unzip_document_to_vault
        extracted = unzip_document_to_vault(
            db=db,
            document_id=document_id,
            document_title=document_title or None
        )
        if not extracted:
            return "Impossibile estrarre l'archivio ZIP o nessun file valido trovato all'interno."
        
        lines = [f"Estratti con successo {len(extracted)} documenti dall'archivio ZIP nel caveau:"]
        for d in extracted:
            lines.append(f"- [ID {d.id}] **{d.title}** ({d.doc_type}) | Download: /api/documents/{d.id}/download")
        return "\n".join(lines)


# ==============================================================================
# TOOL MCP: GOOGLE DRIVE, CARTELLE PC & ESPLORA RISORSE
# ==============================================================================

@mcp.tool()
def get_google_drive_status(query: str = "") -> str:
    """Recupera lo stato attuale della connessione Google Drive Cloud Sync, la modalità ('dual' o 'cloud_only') e l'alberatura delle cartelle su Google Drive."""
    with _get_db_session() as db:
        cred = db.query(GoogleDriveCredential).first()
        if not cred:
            return (
                "Google Drive Cloud Sync non è attualmente collegato.\n"
                "- L'utente può collegare il proprio account dal menu 'Strumenti -> ☁️ Google Drive Cloud Sync'.\n"
                "- Cartella radice configurata: 'DoveLoAIMesso'\n"
                "- Struttura cartelle: DoveLoAIMesso / <Anno> / <Categoria> / <File>"
            )

        q_drive = db.query(Document).filter(
            or_(Document.drive_file_id.isnot(None), Document.drive_web_url.isnot(None))
        )
        if query.strip():
            q_term = f"%{query.strip()}%"
            q_drive = q_drive.filter(or_(Document.title.ilike(q_term), Document.doc_type.ilike(q_term)))

        drive_docs = q_drive.order_by(Document.id.desc()).all()
        lines = [
            f"=== STATO GOOGLE DRIVE CLOUD SYNC ===",
            f"- Stato: Connesso",
            f"- Modalità di archiviazione: {cred.storage_mode} ({'Copia locale + Drive' if cred.storage_mode == 'dual' else 'Solo cloud su Drive'})",
            f"- Account Google: {cred.account_email or 'Non specificato'}",
            f"- Cartella Principale: 'DoveLoAIMesso'",
            f"- Documenti sincronizzati: {len(drive_docs)}"
        ]

        if drive_docs:
            lines.append("\nElenco file su Google Drive:")
            for d in drive_docs[:8]:
                folder_parts = resolve_drive_folder_path(d.doc_type, d.due_date)
                folder_str = " / ".join(folder_parts)
                drive_url = d.drive_web_url or "Disponibile su Drive"
                lines.append(f"- **{d.title}** in '{folder_str}' | Link: {drive_url}")
        return "\n".join(lines)

@mcp.tool()
def scan_local_folder(folder_path: str = "") -> str:
    """Scansiona e indicizza i documenti (PDF, immagini, fatture, ricevute) da una cartella sul PC o da tutte le cartelle monitorate."""
    with _get_db_session() as db:
        from app.services.folder_service import scan_local_folder as do_scan_folder
        
        f_path = folder_path.strip()
        results = []
        if f_path and f_path.lower() != "all":
            res = do_scan_folder(f_path, db)
            results.append(res)
        else:
            watched = db.query(WatchedFolder).filter(WatchedFolder.is_active == True).all()
            if not watched:
                return "Nessuna cartella del computer è attualmente configurata per il monitoraggio. Aggiungine una dalla Dashboard o specifica un percorso valido (es. C:\\Fatture)."
            for wf in watched:
                res = do_scan_folder(wf.path, db, watched_folder_id=wf.id)
                results.append(res)

        total_scanned = sum(r.scanned_files_count for r in results)
        total_new = sum(r.new_indexed_count for r in results)
        total_skipped = sum(r.skipped_count for r in results)
        total_errors = sum(r.error_count for r in results)

        return (
            f"Scansione cartelle PC completata:\n"
            f"- File esaminati: {total_scanned}\n"
            f"- Nuovi documenti indicizzati nel caveau: {total_new}\n"
            f"- File già presenti o non modificati: {total_skipped}\n"
            f"- Errori: {total_errors}"
        )

@mcp.tool()
def list_watched_folders() -> str:
    """Elenca tutte le cartelle del computer attualmente monitorate da 'Dove lo AI messo'."""
    with _get_db_session() as db:
        folders = db.query(WatchedFolder).all()
        if not folders:
            return "Nessuna cartella del computer è attualmente configurata per il monitoraggio."
        
        lines = [f"Cartelle del computer monitorate ({len(folders)} totali):"]
        for f in folders:
            status = "🟢 Attiva" if f.is_active else "⚪ Inattiva"
            last = f.last_scanned_at.strftime("%d/%m/%Y %H:%M") if f.last_scanned_at else "Mai"
            lines.append(f"- **{f.name}** ({f.path}) [{status}] — File trovati: {f.file_count or 0}, Ultima scansione: {last}")
        return "\n".join(lines)

@mcp.tool()
def open_local_file_in_explorer(document_title: str = "", document_id: Optional[int] = None, path: str = "") -> str:
    """Apre direttamente un file o una cartella in Esplora File di Windows (File Explorer) evidenziandolo."""
    with _get_db_session() as db:
        from app.services.folder_service import open_path_in_explorer
        
        target_path = None
        if document_id:
            doc = db.query(Document).filter(Document.id == document_id).first()
            if doc:
                target_path = doc.original_path or doc.file_path
        elif document_title:
            matches = search_vault_documents(db, document_title)
            if matches:
                doc = db.query(Document).filter(Document.id == matches[0]["document_id"]).first()
                if doc:
                    target_path = doc.original_path or doc.file_path
        elif path:
            target_path = path

        if not target_path or not Path(target_path).exists():
            return f"File o percorso non trovato sul computer: {target_path or document_title or document_id}."

        opened = open_path_in_explorer(target_path)
        if opened:
            return f"Aperto con successo '{Path(target_path).name}' in Esplora Risorse di Windows."
        return f"Impossibile aprire Esplora Risorse per il percorso: {target_path}."


if __name__ == "__main__":
    mcp.run()
