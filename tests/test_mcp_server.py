import pytest
from app.mcp_server import mcp, AGENT_ROLE_AND_INSTRUCTIONS, get_vault_context, search_vault, vault_assistant_instructions
from app.models.database import get_db, init_db, Document, PhysicalItem
from datetime import date

def test_mcp_server_instructions_and_prompt():
    # 1. MCP Server instance has instructions configured
    assert mcp.instructions is not None
    assert "RICERCA E ASSISTENZA NEI DOCUMENTI" in mcp.instructions
    assert "730" in mcp.instructions
    assert "bollette" in mcp.instructions

    # 2. Prompt function returns complete agent instructions
    prompt_text = vault_assistant_instructions()
    assert "IL TUO COMPITO PRINCIPALE E MISSIONE OPERATIVA" in prompt_text
    assert "Modello 730" in prompt_text

def test_mcp_get_vault_context_includes_role():
    context = get_vault_context()
    assert "=== RUOLO E COMPITI DELL'AGENTE (DOVE LO AI MESSO) ===" in context
    assert "TROVARE I DOCUMENTI" in context
    assert "MONITORARE LE SCADENZE" in context
    assert "RITROVARE OGGETTI FISICI" in context

def test_mcp_search_vault_includes_download_link():
    init_db()
    db = next(get_db())
    # Add a test document
    doc = Document(
        title="Dichiarazione 730 Test",
        file_path="uploads/test_730.pdf",
        file_type="pdf",
        doc_type="730",
        issuer="Agenzia delle Entrate",
        amount=150.0,
        due_date=date(2026, 7, 15),
        status="archiviato",
        summary="Dichiarazione dei redditi 730 di test."
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    res = search_vault("730")
    assert "Dichiarazione 730 Test" in res
    assert f"/api/documents/{doc.id}/download" in res
