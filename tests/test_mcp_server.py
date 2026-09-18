import pytest
from datetime import date
from pathlib import Path
from app.mcp_server import (
    mcp,
    AGENT_ROLE_AND_INSTRUCTIONS,
    get_current_date,
    get_app_version,
    get_vault_stats,
    get_vault_context,
    search_vault,
    list_vault_contents,
    get_recent_vault_documents,
    store_physical_item,
    link_document_to_item,
    get_upcoming_deadlines,
    rename_vault_document,
    recategorize_vault_document,
    delete_vault_record,
    create_zip_archive,
    unzip_vault_archive,
    get_google_drive_status,
    scan_local_folder,
    list_watched_folders,
    open_local_file_in_explorer,
    vault_assistant_instructions,
    assistant_behavior_and_widget_rules,
    google_drive_sync_guidelines,
)
from app.models.database import get_db, init_db, Document, PhysicalItem, WatchedFolder, GoogleDriveCredential
from app.version import APP_VERSION


def test_mcp_server_instructions_and_prompts():
    # 1. MCP Server instructions
    assert mcp.instructions is not None
    assert "concierge privato" in mcp.instructions.lower()
    assert "MATRICE DECISIONALE DEI WIDGET" in mcp.instructions
    assert "QUANDO HA SENSO MOSTRARE I WIDGET" in mcp.instructions
    assert "QUANDO NON HA SENSO E VIETATO MOSTRARE WIDGET" in mcp.instructions

    # 2. Prompt functions
    p_inst = vault_assistant_instructions()
    assert "TONO E STILE PROFESSIONALE" in p_inst

    p_widget = assistant_behavior_and_widget_rules()
    assert "AUTONOMIA DECISIONALE ASSOLUTA" in p_widget
    assert "show_document_card" in p_widget
    assert "cosa puoi fare" in p_widget

    p_drive = google_drive_sync_guidelines()
    assert "DoveLoAIMesso" in p_drive
    assert "dual" in p_drive
    assert "cloud_only" in p_drive


def test_mcp_date_version_and_stats():
    init_db()
    d_str = get_current_date()
    assert "Oggi è" in d_str

    v_str = get_app_version()
    assert APP_VERSION in v_str

    stats_str = get_vault_stats()
    assert f"v{APP_VERSION}" in stats_str
    assert "Documenti totali archiviati" in stats_str
    assert "Oggetti fisici catalogati" in stats_str


def test_mcp_context_and_search():
    init_db()
    db = next(get_db())

    # Add test doc
    doc = Document(
        title="Contratto Locazione Test",
        file_path="uploads/contratto_test.pdf",
        file_type="pdf",
        doc_type="contratto",
        issuer="Agenzia Immobiliare",
        amount=650.0,
        due_date=date(2026, 11, 1),
        status="da_pagare",
        summary="Contratto di locazione appartamento."
    )
    db.add(doc)

    item = PhysicalItem(
        item_name="Passaporto Italiano",
        primary_location="Studio",
        detailed_location="Primo Cassetto Scrivania",
        category="documenti"
    )
    db.add(item)
    db.commit()

    # Test get_vault_context
    ctx = get_vault_context()
    assert "Contratto Locazione Test" in ctx
    assert "Passaporto Italiano" in ctx

    # Test search_vault
    res_doc = search_vault("locazione")
    assert "Contratto Locazione Test" in res_doc
    assert f"/api/documents/{doc.id}/download" in res_doc

    res_item = search_vault("passaporto")
    assert "Passaporto Italiano" in res_item
    assert "Studio" in res_item


def test_mcp_list_and_recent_contents():
    init_db()
    all_res = list_vault_contents(target_type="all")
    assert "DOCUMENTI NEL CAVEAU" in all_res
    assert "OGGETTI FISICI NEL CAVEAU" in all_res

    docs_res = list_vault_contents(target_type="documents")
    assert "DOCUMENTI NEL CAVEAU" in docs_res

    items_res = list_vault_contents(target_type="physical_items")
    assert "OGGETTI FISICI NEL CAVEAU" in items_res

    recent = get_recent_vault_documents(limit=2)
    assert len(recent) > 0


def test_mcp_store_and_link_physical_items():
    init_db()
    db = next(get_db())

    # Store physical item
    msg = store_physical_item(
        item_name="Occhiali da Sole",
        primary_location="Camera da letto",
        detailed_location="Comodino destro",
        category="accessori"
    )
    assert "Memorizzato con successo" in msg
    assert "Occhiali da sole" in msg

    # Link document to item
    doc = Document(
        title="Foto Custodia Occhiali",
        file_path="uploads/custodia.jpg",
        file_type="jpg",
        summary="Foto della custodia"
    )
    db.add(doc)
    db.commit()

    link_msg = link_document_to_item(item_name="Occhiali da sole", document_id=doc.id)
    assert "collegato con successo" in link_msg


def test_mcp_deadlines_and_document_actions():
    init_db()
    db = next(get_db())

    # Deadlines
    deadlines = get_upcoming_deadlines()
    assert "Scadenze" in deadlines or "quietanzati" in deadlines.lower()


    # Rename
    doc = Document(
        title="Vecchio Titolo Da Rinominare",
        file_path="uploads/vecchio.pdf",
        file_type="pdf",
        summary="Test rename"
    )
    db.add(doc)
    db.commit()

    rename_res = rename_vault_document("Nuovo Titolo Bolletta Gas", document_id=doc.id)
    assert "rinominato con successo" in rename_res
    assert "Nuovo Titolo Bolletta Gas" in rename_res

    # Recategorize
    recar_res = recategorize_vault_document(
        category_label="Canzoni & Testi Musicali",
        document_id=doc.id,
        category_icon="fa-music"
    )
    assert "spostato con successo" in recar_res
    assert "Canzoni & Testi Musicali" in recar_res

    # Delete
    del_res = delete_vault_record(target_type="document", title="", target_id=doc.id)
    assert "eliminato definitivamente" in del_res


def test_mcp_zip_archive_tools():
    init_db()
    # Test zip creation with non-matching query
    res_no = create_zip_archive(query="nonexistent_xyz999_pattern")
    assert "Nessun documento trovato" in res_no

    # Test unzip with non-matching title
    res_unzip = unzip_vault_archive(document_title="nonexistent_archive_xyz")
    assert "Impossibile estrarre" in res_unzip



def test_mcp_drive_and_folders(tmp_path: Path):
    init_db()
    # Google Drive status when not connected
    drive_stat = get_google_drive_status()
    assert "DoveLoAIMesso" in drive_stat

    # Watched folders
    wf_list = list_watched_folders()
    assert "Cartelle del computer" in wf_list or "Nessuna cartella" in wf_list

    # Local folder scan on isolated tmp directory
    scan_res = scan_local_folder(str(tmp_path))
    assert "Scansione cartelle PC completata" in scan_res


    # Open in explorer test for nonexistent path
    open_res = open_local_file_in_explorer(path="C:/nonexistent_path_xyz123")
    assert "non trovato" in open_res.lower()
