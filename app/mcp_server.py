import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from mcp.server.mcpserver import MCPServer
from sqlalchemy.orm import Session
from app.models.database import get_db, init_db, Document, PhysicalItem
from app.services.search_service import search_vault_documents, search_vault_items

AGENT_ROLE_AND_INSTRUCTIONS = """Sei l'assistente AI intelligente di 'Dove lo AI messo', un caveau digitale e inventario fisico per famiglie e professionisti italiani.

IL TUO COMPITO PRINCIPALE E MISSIONE OPERATIVA:
1. RICERCA E ASSISTENZA NEI DOCUMENTI:
   - Gli utenti cercano nel caveau documenti personali, fiscali e domestici: Modello 730, Modelli F24, bollette di utenze (luce, gas, telefono), fatture, contratti di locazione o lavoro, ricevute sanitarie, certificati scolastici/universitari, stipendi ed estratti conto.
   - Il tuo dovere fondamentale è AIUTARE gli utenti a individuare immediatamente il documento esatto che cercano.
   - Esponi subito tutti i dettagli rilevanti: titolo, ente o fornitore emittente, importo da pagare o rimborsato, data di scadenza e una sintesi chiara e comprensibile del documento.
   - Rendi sempre disponibili il visualizzatore e il link di download per permettere all'utente di scaricare il file direttamente sul proprio computer o smartphone.

2. GESTIONE E PROMEMORIA DELLE SCADENZE:
   - Gli utenti devono poter verificare in ogni momento cosa c'è da pagare.
   - Aiutali a non incorrere in more o dimenticanze, tenendo traccia delle bollette e dei tributi con stato 'da_pagare'.

3. RITROVAMENTO IMMEDIATO DEGLI OGGETTI FISICI:
   - Gli utenti memorizzano dove hanno riposto oggetti importanti (es. passaporto nel primo cassetto della scrivania, chiavi di scorta nel mobile d'ingresso, caricatore, occhiali, faldoni cartacei).
   - Quando l'utente chiede dove si trova qualcosa, rispondi con esattezza specificando stanza, mobile o cassetto.

4. MEMORIZZAZIONE RAPIDA ED EFFICACE:
   - Quando l'utente ti dice dove ha appena riposto un oggetto, salvalo tempestivamente nel caveau con lo strumento `store_physical_item`.

LINEE GUIDA COMPORTAMENTALI:
- Sii sempre cortese, chiaro, proattivo e sicuro.
- Se l'utente chiede un documento, cercalo subito nel caveau senza fargli domande di permesso superflue (es. mai chiedere "vuoi che te lo mostri?").
- Rispondi sempre in lingua italiana naturale e comprensibile."""

mcp = MCPServer(
    "dove-lo-ai-messo",
    description="Caveau intelligente per documenti, bollette, scadenze e oggetti fisici con assistenza AI",
    instructions=AGENT_ROLE_AND_INSTRUCTIONS
)

def _get_db_session() -> Session:
    init_db()
    return next(get_db())

@mcp.prompt("vault_assistant_instructions")
def vault_assistant_instructions() -> str:
    """Istruzioni operative per guidare l'assistente AI nel supporto agli utenti per ricerca documenti, download, scadenze e oggetti fisici."""
    return AGENT_ROLE_AND_INSTRUCTIONS

@mcp.tool()
def get_vault_context() -> str:
    """Restituisce il ruolo e le istruzioni dell'agente, insieme al contesto completo e aggiornato del Caveau (ultimi documenti, oggetti e scadenze)."""
    db = _get_db_session()
    docs = db.query(Document).order_by(Document.id.desc()).limit(6).all()
    items = db.query(PhysicalItem).order_by(PhysicalItem.id.desc()).limit(10).all()
    unpaid = db.query(Document).filter(Document.status == "da_pagare").all()

    output = [
        "=== RUOLO E COMPITI DELL'AGENTE (DOVE LO AI MESSO) ===",
        "Sei l'assistente AI dedicato del Caveau. Il tuo compito primario è aiutare gli utenti a:",
        "1. TROVARE I DOCUMENTI: Quando gli utenti cercano documenti (730, F24, bollette, contratti, ricevute), devi aiutarli individuando subito il file corretto, esponendo i dati chiave e permettendo loro di visualizzarli e scaricarli.",
        "2. MONITORARE LE SCADENZE: Aiutali a non dimenticare bollette e tributi in scadenza.",
        "3. RITROVARE OGGETTI FISICI: Ricorda e indica con esattezza dove sono stati messi gli oggetti memorizzati (stanze, mobili, cassetti).",
        "4. MEMORIZZARE: Salva con prontezza le posizioni comunicate dagli utenti.",
        "",
        "=== CONTESTO ATTUALE DEL CAVEAU (DATI IN TEMPO REALE) ===",
        "## Ultimi Documenti Archiviati:"
    ]

    if docs:
        for d in docs:
            amount_str = f" | Importo: {d.amount:.2f} €" if d.amount is not None else ""
            due_str = f" | Scadenza: {d.due_date}" if d.due_date else ""
            output.append(f"- [ID {d.id}] **{d.title}** ({d.doc_type} - {d.issuer}){amount_str}{due_str}")
            output.append(f"  File: /uploads/{Path(d.file_path).name} | Download: /api/documents/{d.id}/download")
            output.append(f"  Sintesi: {d.summary[:200]}...")
    else:
        output.append("Nessun documento presente.")

    output.append("\n## Posizioni Oggetti Fisici Memorizzati:")
    if items:
        for it in items:
            loc = it.primary_location + (f" -> {it.detailed_location}" if it.detailed_location else "")
            output.append(f"- **{it.item_name}**: {loc} (categoria: {it.category or 'generico'})")
    else:
        output.append("Nessun oggetto fisico registrato.")

    output.append(f"\n## Scadenze da pagare: {len(unpaid)} in sospeso.")
    return "\n".join(output)

@mcp.tool()
def search_vault(query: str) -> str:
    """Cerca nel caveau documenti e oggetti fisici con supporto per singolari/plurali, sinonimi, tolleranza ai refusi e link per il download."""
    db = _get_db_session()
    docs = search_vault_documents(db, query)
    items = search_vault_items(db, query)

    result = []
    if docs:
        doc_lines = []
        for d in docs[:4]:
            amt = f" | Importo: {d['amount']:.2f} €" if d.get('amount') is not None else ""
            due = f" | Scadenza: {d['due_date']}" if d.get('due_date') else ""
            dl_url = d.get('download_url') or f"/api/documents/{d['document_id']}/download"
            doc_lines.append(
                f"- Documento #{d['document_id']}: **{d['title']}** ({d.get('doc_type', 'generico')}) - Emittente: {d.get('issuer', 'N/D')}{amt}{due}\n"
                f"  Anteprima: {d.get('file_url', 'N/D')} | Link Download Diretto: {dl_url}\n"
                f"  Sintesi: {d.get('summary', '')}"
            )
        result.append("Documenti trovati (aiuta l'utente fornendogli i dettagli e la possibilità di scaricare il file):\n" + "\n".join(doc_lines))

    if items:
        item_lines = [
            f"- Oggetto: **{it['item_name']}** -> Posizione: {it['primary_location']}" + 
            (f" ({it['detailed_location']})" if it.get("detailed_location") else "") 
            for it in items[:4]
        ]
        result.append("Oggetti fisici trovati:\n" + "\n".join(item_lines))

    if not result:
        return f"Nessun risultato trovato nel caveau per '{query}'. Invita gentilmente l'utente a verificare il nome o a caricare/memorizzare l'elemento."
    return "\n\n".join(result)

@mcp.tool()
def store_physical_item(item_name: str, primary_location: str, detailed_location: str = "", category: str = "generico") -> str:
    """Memorizza o aggiorna la posizione di un oggetto fisico nel caveau."""
    db = _get_db_session()
    cleaned = item_name.strip().capitalize()
    existing = db.query(PhysicalItem).filter(PhysicalItem.item_name.ilike(cleaned)).first()
    if existing:
        existing.primary_location = primary_location
        if detailed_location:
            existing.detailed_location = detailed_location
        item = existing
    else:
        item = PhysicalItem(
            item_name=cleaned,
            primary_location=primary_location,
            detailed_location=detailed_location or None,
            category=category
        )
        db.add(item)
    db.commit()
    db.refresh(item)
    loc = item.primary_location + (f" ({item.detailed_location})" if item.detailed_location else "")
    return f"Memorizzato con successo: '{item.item_name}' in {loc}."

@mcp.tool()
def get_upcoming_deadlines() -> str:
    """Recupera le scadenze e bollette da pagare con link di download per i rispettivi documenti."""
    db = _get_db_session()
    unpaid = db.query(Document).filter(Document.status == "da_pagare").order_by(Document.due_date.asc().nulls_last()).all()
    if not unpaid:
        return "Non ci sono scadenze o bollette in sospeso nel caveau. Tutti i pagamenti risultano quietanzati!"
    lines = [
        f"- **{d.title}**: {d.amount or 0:.2f} € entro il {d.due_date or 'data non definita'} | Download: /api/documents/{d.id}/download" 
        for d in unpaid
    ]
    return "Scadenze e bollette da pagare in sospeso:\n" + "\n".join(lines)

if __name__ == "__main__":
    mcp.run()
