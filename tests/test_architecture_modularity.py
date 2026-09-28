"""
Test suite per la verifica dell'architettura modulare (Separation of Concerns).
Verifica l'integrità dei package modulari del backend e dei moduli frontend.
"""
from pathlib import Path
import subprocess
import sys


def test_agent_package_modularity():
    """Verifica che il backend Agent sia organizzato in package modulare con sotto-moduli specializzati."""
    import app.services.agent as agent_pkg
    from app.services.agent import helpers, tools_spec, prompts, context_builder, tools_executor, orchestrator
    from app.services.agent_service import AgenticChatService, AgentService

    # Verifica export principali del package
    assert hasattr(agent_pkg, "AgenticChatService")
    assert hasattr(agent_pkg, "AgentService")
    assert hasattr(agent_pkg, "TOOLS_DEFINITION")
    assert hasattr(agent_pkg, "SYSTEM_PROMPT")
    assert hasattr(agent_pkg, "execute_vault_tool")
    assert hasattr(agent_pkg, "build_system_prompt")
    assert hasattr(agent_pkg, "get_current_date_info")
    assert hasattr(agent_pkg, "categorize_deadline")

    # Verifica specializzazione sotto-moduli
    assert hasattr(helpers, "categorize_deadline")
    assert hasattr(helpers, "extract_rename_title")
    assert hasattr(tools_spec, "TOOLS_DEFINITION")
    assert hasattr(prompts, "SYSTEM_PROMPT")
    assert hasattr(context_builder, "build_system_prompt")
    assert hasattr(tools_executor, "execute_vault_tool")
    assert hasattr(orchestrator, "AgenticChatService")

    # Verifica conformità classe
    agent = AgenticChatService()
    assert hasattr(agent, "run_turn")
    assert hasattr(agent, "execute_tool")
    assert hasattr(agent, "build_system_prompt")


def test_archive_package_modularity():
    """Verifica che il backend Archive sia organizzato in package modulare con sotto-moduli specializzati."""
    import app.services.archive as archive_pkg
    from app.services.archive import inspectors, metadata, zip_ops
    from app.services.archive_service import inspect_document_content, create_zip_from_documents, unzip_document_to_vault

    # Verifica export principali del package
    assert hasattr(archive_pkg, "inspect_document_content")
    assert hasattr(archive_pkg, "render_office_file_to_html")
    assert hasattr(archive_pkg, "create_zip_from_documents")
    assert hasattr(archive_pkg, "unzip_document_to_vault")
    assert hasattr(archive_pkg, "fast_extract_document_metadata")

    # Verifica specializzazione sotto-moduli
    assert hasattr(inspectors, "inspect_document_content")
    assert hasattr(inspectors, "render_office_file_to_html")
    assert hasattr(inspectors, "extract_text_from_office_file")
    assert hasattr(metadata, "fast_extract_document_metadata")
    assert hasattr(zip_ops, "create_zip_from_documents")
    assert hasattr(zip_ops, "unzip_document_to_vault")


def test_frontend_modules_structure():
    """Verifica che la directory static/js/modules/ contenga i 7 moduli frontend e che il bundler funzioni."""
    modules_dir = Path("static/js/modules")
    assert modules_dir.exists() and modules_dir.is_dir()

    expected_modules = [
        "01-core.js",
        "02-navigation.js",
        "03-threads.js",
        "04-cloud.js",
        "05-chat.js",
        "06-panel.js",
        "07-modals.js",
    ]

    for mod in expected_modules:
        p = modules_dir / mod
        assert p.exists(), f"Modulo frontend mancante: {mod}"
        assert p.stat().st_size > 1000, f"Modulo {mod} troppo piccolo o vuoto"

    # Verifica che lo script di bundling compili senza errori
    res = subprocess.run([sys.executable, "scripts/bundle_frontend.py"], capture_output=True, text=True)
    assert res.returncode == 0
    assert "Bundle generato con successo" in res.stdout

    bundle_path = Path("static/js/app-bundle.js")
    assert bundle_path.exists()
    assert bundle_path.stat().st_size > 400000
