from datetime import date, datetime, timezone
import pytest
from sqlalchemy.orm import Session
from app.models.database import Document, init_db, get_engine
from app.services.category_service import (
    DEFAULT_GENERAL_CATEGORIES,
    get_active_vault_categories,
    extract_subfolder,
    resolve_or_create_category_and_subfolder,
    consolidate_vault_categories,
)


@pytest.fixture
def db_session():
    engine = get_engine("sqlite:///:memory:")
    init_db(engine)
    with Session(engine) as session:
        yield session


def test_default_categories_catalog():
    slugs = [c["slug"] for c in DEFAULT_GENERAL_CATEGORIES]
    assert "utenze_bollette" in slugs
    assert "fisco_tributi" in slugs
    assert "ricevute_spese" in slugs
    assert "contratti_polizze" in slugs
    assert "documenti_identita" in slugs
    assert "sanita_spese_mediche" in slugs
    assert "formazione_certificati" in slugs
    assert "auto_veicoli" in slugs
    assert "canzoni_musica" in slugs
    assert "archivi_zip" in slugs
    assert "foto_immagini" in slugs


def test_deduplication_converges_to_general_categories(db_session):
    # Test 1: "Testi Canzoni" converge su "Canzoni, Musica & Testi Personali"
    slug, label, icon, sub = resolve_or_create_category_and_subfolder(
        proposed_label="Testi Canzoni",
        document_text="Strofe e accordi del brano musicale",
        doc_type="canzone",
        db=db_session
    )
    assert slug == "canzoni_musica"
    assert label == "Canzoni & Testi Musicali"
    assert icon == "fa-music"

    # Test 2: "Bolletta Luce" converge su "Utenze & Bollette"
    slug2, label2, icon2, sub2 = resolve_or_create_category_and_subfolder(
        proposed_label="Bolletta Luce",
        document_text="Fornitura energia elettrica Enel consumi smc",
        doc_type="bolletta",
        due_date=date(2026, 5, 20),
        db=db_session
    )
    assert slug2 == "utenze_bollette"
    assert label2 == "Utenze & Bollette"
    assert sub2 == "2026"

    # Test 3: "Scontrini e Ricevute Fiscali" converge su "Fatture, Spese & Ricevute"
    slug3, label3, icon3, sub3 = resolve_or_create_category_and_subfolder(
        proposed_label="Scontrini e Ricevute Fiscali",
        document_text="Pagamento spesa farmacia e cancelleria",
        doc_type="ricevuta",
        db=db_session
    )
    assert slug3 == "ricevute_spese"
    assert label3 == "Fatture, Spese & Ricevute"


def test_new_category_creation_when_not_related(db_session):
    # Test: argomento totalmente non inerente (es. "Ricette della Nonna" o "Collezione Minerali")
    slug, label, icon, sub = resolve_or_create_category_and_subfolder(
        proposed_label="Ricette & Cucina Tradizionale",
        document_text="Ingredienti per fare la pasta alla carbonara con guanciale",
        doc_type="ricetta",
        proposed_icon="fa-utensils",
        db=db_session
    )
    assert slug == "ricette_cucina_tradizionale"
    assert label == "Ricette & Cucina Tradizionale"
    assert icon == "fa-utensils"

    # Ora simuliamo che questa nuova categoria venga salvata nel database
    doc = Document(
        title="Pasta Carbonara",
        file_path="/storage/carbonara.pdf",
        file_type="pdf",
        summary="Ricetta per la pasta alla carbonara con pecorino e guanciale",
        category=slug,
        category_label=label,
        category_icon=icon
    )
    db_session.add(doc)
    db_session.commit()

    # Successivo caricamento affine: "Ricette di Pasta" deve convergere verso la cartella creata nel Caveau!
    slug_next, label_next, icon_next, _ = resolve_or_create_category_and_subfolder(
        proposed_label="Ricette di Pasta",
        document_text="Altra ricetta di cucina",
        doc_type="ricetta",
        db=db_session
    )
    assert slug_next == "ricette_cucina_tradizionale"
    assert label_next == "Ricette & Cucina Tradizionale"


def test_extract_subfolder_logic():
    # 1. Da due_date (date object)
    assert extract_subfolder(due_date=date(2026, 11, 15)) == "2026"

    # 2. Da stringa data
    assert extract_subfolder(due_date="2025-04-10") == "2025"

    # 3. Da nome file con anno
    assert extract_subfolder(filename="rendiconto_spese_2024_ufficio.xlsx") == "2024"

    # 4. Sottocartella tematica esplicita
    assert extract_subfolder(proposed_subfolder="Locazioni") == "Locazioni"

    # 5. Sottocartella anno esplicita
    assert extract_subfolder(proposed_subfolder="2027") == "2027"

    # 6. Fallback anno corrente per bolletta senza data
    current_year = str(datetime.now(timezone.utc).year)
    assert extract_subfolder(doc_type="bolletta") == current_year


def test_consolidate_vault_categories(db_session):
    # Inseriamo vecchi documenti con categorie frammentate
    d1 = Document(
        title="Canzone d'Autore",
        file_path="/storage/brano.txt",
        file_type="txt",
        doc_type="canzone",
        summary="Testo del brano con strofe e ritornello",
        category="musica_testi",
        category_label="Testi Canzoni",
        category_icon="fa-music"
    )
    d2 = Document(
        title="Bolletta Enel Luce 2025",
        file_path="/storage/bolletta_2025.pdf",
        file_type="pdf",
        doc_type="bolletta",
        summary="Bolletta energia elettrica 2025",
        category="utenze_enel",
        category_label="Bollette Luce Enel",
        category_icon="fa-bolt"
    )
    db_session.add_all([d1, d2])
    db_session.commit()

    report = consolidate_vault_categories(db_session)
    assert report["updated_documents_count"] == 2

    # Verifica convergenza
    db_session.refresh(d1)
    db_session.refresh(d2)

    assert d1.category == "canzoni_musica"
    assert d1.category_label == "Canzoni & Testi Musicali"

    assert d2.category == "utenze_bollette"
    assert d2.category_label == "Utenze & Bollette"
    assert d2.subfolder == "2025"


def test_recategorize_with_subfolder_agent(db_session):
    from app.services.agent_service import AgentService
    agent = AgentService()

    doc = Document(
        title="Contratto Affitto Studio",
        file_path="/storage/contratto_affitto.pdf",
        file_type="pdf",
        doc_type="contratto",
        summary="Contratto di locazione ad uso ufficio",
        category="contratti_polizze",
        category_label="Contratti, Polizze & Assicurazioni"
    )
    db_session.add(doc)
    db_session.commit()

    # Eseguiamo il tool recategorize specificando la sottocartella "Locazioni"
    result = agent.execute_tool(
        "recategorize_vault_document",
        {
            "document_id": doc.id,
            "category_label": "Contratti, Polizze & Assicurazioni",
            "subfolder": "Locazioni"
        },
        db_session,
        "general"
    )

    assert result["success"] is True
    assert result["subfolder"] == "Locazioni"
    db_session.refresh(doc)
    assert doc.subfolder == "Locazioni"
    assert "Locazioni" in result["message"]


def test_recategorize_with_subfolder_mcp(db_session, monkeypatch):
    from contextlib import contextmanager
    from app.mcp_server import recategorize_vault_document

    @contextmanager
    def _mock_session():
        yield db_session

    monkeypatch.setattr("app.mcp_server._get_db_session", _mock_session)

    doc = Document(
        title="Fattura Commercialista",
        file_path="/storage/fattura_2026.pdf",
        file_type="pdf",
        doc_type="fattura",
        summary="Fattura parcella 2026",
        category="ricevute_spese",
        category_label="Fatture, Spese & Ricevute"
    )
    db_session.add(doc)
    db_session.commit()

    res = recategorize_vault_document(
        category_label="Fatture, Spese & Ricevute",
        document_id=doc.id,
        subfolder="2026"
    )
    assert "sottocartella: 2026" in res
    saved_doc = db_session.query(Document).filter(Document.id == doc.id).first()
    assert saved_doc.subfolder == "2026"


def test_drive_folder_path_with_subfolder():
    from app.services.drive_service import resolve_drive_folder_path

    # Con category_label e subfolder
    path = resolve_drive_folder_path(
        "bolletta",
        due_date=date(2026, 10, 28),
        category_label="Utenze & Bollette",
        subfolder="2026"
    )
    assert path == ["DoveLoAIMesso", "Utenze & Bollette", "2026"]

    # Con category_label e sottocartella tema
    path_theme = resolve_drive_folder_path(
        "contratto",
        category_label="Contratti, Polizze & Assicurazioni",
        subfolder="Locazioni"
    )
    assert path_theme == ["DoveLoAIMesso", "Contratti, Polizze & Assicurazioni", "Locazioni"]

    # Backward compatibility: senza category_label e subfolder
    legacy_path = resolve_drive_folder_path("bolletta", due_date=date(2026, 10, 28))
    assert legacy_path == ["DoveLoAIMesso", "2026", "Bollette & Utenze"]


def test_ai_service_extracts_subfolder():
    from app.services.ai_service import MockAIService
    svc = MockAIService()

    # Bolletta con scadenza 2026-10-28
    doc = svc.extract_document(b"dummy", "application/pdf", "bolletta_enel.pdf")
    assert doc.category == "utenze_bollette"
    assert doc.category_label == "Utenze & Bollette"
    assert doc.subfolder == "2026"
