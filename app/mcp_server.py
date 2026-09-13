import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from mcp.server.mcpserver import MCPServer
from sqlalchemy.orm import Session
from app.models.database import get_db, init_db, Document, PhysicalItem

mcp = MCPServer("dove-lo-ai-messo")

def _get_db_session() -> Session:
    init_db()
    return next(get_db())

@mcp.tool()
def get_vault_context() -> str:
    """Restituisce il contesto completo e aggiornato del Caveau (ultimi documenti, oggetti e scadenze) per dare memoria immediata all'AI."""
    db = _get_db_session()
    docs = db.query(Document).order_by(Document.id.desc()).limit(5).all()
    items = db.query(PhysicalItem).order_by(PhysicalItem.id.desc()).limit(10).all()
    unpaid = db.query(Document).filter(Document.status == "da_pagare").all()

    output = ["=== CONTESTO ATTUALE DEL CAVEAU (DOVE LO AI MESSO) ===\n"]
    output.append("## Ultimi Documenti Archiviati:")
    if docs:
        for d in docs:
            amount_str = f" | Importo: {d.amount} €" if d.amount else ""
            due_str = f" | Scadenza: {d.due_date}" if d.due_date else ""
            output.append(f"- [ID {d.id}] **{d.title}** ({d.doc_type} - {d.issuer}){amount_str}{due_str}")
            output.append(f"  Sintesi: {d.summary[:200]}...")
    else:
        output.append("Nessun documento presente.")

    output.append("\n## Posizioni Oggetti Fisici Memorizzati:")
    if items:
        for it in items:
            loc = it.primary_location + (f" -> {it.detailed_location}" if it.detailed_location else "")
            output.append(f"- **{it.item_name}**: {loc} (categoria: {it.category})")
    else:
        output.append("Nessun oggetto fisico registrato.")

    output.append(f"\n## Scadenze da pagare: {len(unpaid)} in sospeso.")
    return "\n".join(output)

@mcp.tool()
def search_vault(query: str) -> str:
    """Cerca nel caveau documenti e oggetti fisici corrispondenti alla parola chiave."""
    db = _get_db_session()
    q = query.strip().lower()

    docs = db.query(Document).order_by(Document.id.desc()).all()
    matching_docs = []
    for d in docs:
        blob = f"{d.title} {d.issuer or ''} {d.summary} {d.doc_type}".lower()
        if q in blob:
            matching_docs.append(f"- Documento #{d.id}: {d.title} ({d.doc_type}) - Emittente: {d.issuer}\n  {d.summary}")

    items = db.query(PhysicalItem).order_by(PhysicalItem.id.desc()).all()
    matching_items = []
    for it in items:
        blob = f"{it.item_name} {it.primary_location} {it.detailed_location or ''}".lower()
        if q in blob:
            loc = it.primary_location + (f" ({it.detailed_location})" if it.detailed_location else "")
            matching_items.append(f"- Oggetto: {it.item_name} -> Posizione: {loc}")

    result = []
    if matching_docs:
        result.append("Documenti trovati:\n" + "\n".join(matching_docs[:3]))
    if matching_items:
        result.append("Oggetti fisici trovati:\n" + "\n".join(matching_items[:3]))
    if not result:
        return f"Nessun risultato trovato nel caveau per '{query}'."
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
    """Recupera le scadenze e bollette da pagare."""
    db = _get_db_session()
    unpaid = db.query(Document).filter(Document.status == "da_pagare").order_by(Document.due_date.asc().nulls_last()).all()
    if not unpaid:
        return "Non ci sono scadenze o bollette in sospeso nel caveau."
    lines = [f"- {d.title}: {d.amount or 0:.2f} € entro il {d.due_date or 'data non definita'}" for d in unpaid]
    return "Scadenze da pagare:\n" + "\n".join(lines)

if __name__ == "__main__":
    mcp.run()
