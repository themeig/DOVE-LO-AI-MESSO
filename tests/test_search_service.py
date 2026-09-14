from datetime import date
from sqlalchemy.orm import Session

from app.models.database import Document, PhysicalItem, init_db, get_engine
from app.services.search_service import search_vault_documents, search_vault_items, it_stem, token_matches


def setup_test_data(session: Session):
    # Documenti di test
    doc_eni = Document(
        title="Bolletta ENI gas e luce S.p.A.",
        file_path="uploads/eni.pdf",
        file_type="pdf",
        doc_type="bolletta",
        issuer="ENI gas e luce",
        amount=79.30,
        due_date=date(2026, 10, 5),
        status="da_pagare",
        summary="Bolletta gas naturale con scadenza al 05/10/2026."
    )
    doc_enel = Document(
        title="Bolletta Enel Energia",
        file_path="uploads/enel.pdf",
        file_type="pdf",
        doc_type="bolletta",
        issuer="Enel Energia",
        amount=64.20,
        due_date=date(2026, 10, 28),
        status="da_pagare",
        summary="Bolletta energia elettrica luce del bimestre."
    )
    doc_mm = Document(
        title="Bolletta MM S.p.A. — Servizio Idrico",
        file_path="uploads/mm.pdf",
        file_type="pdf",
        doc_type="bolletta",
        issuer="MM S.p.A.",
        amount=52.00,
        due_date=date(2026, 10, 15),
        status="da_pagare",
        summary="Bolletta fornitura acqua potabile."
    )
    doc_f24 = Document(
        title="Modello F24 Agenzia delle Entrate",
        file_path="uploads/f24.pdf",
        file_type="pdf",
        doc_type="f24",
        issuer="Agenzia delle Entrate",
        amount=320.00,
        due_date=date(2026, 11, 30),
        status="da_pagare",
        summary="Modello F24 versamento acconto IRPEF seconda rata."
    )
    doc_mutuo = Document(
        title="Estratto Conto Mutuo Intesa Sanpaolo",
        file_path="uploads/mutuo.pdf",
        file_type="pdf",
        doc_type="mutuo",
        issuer="Intesa Sanpaolo",
        amount=841.00,
        due_date=date(2026, 10, 1),
        status="da_pagare",
        summary="Estratto conto mutuo tasso fisso rata mensile."
    )
    session.add_all([doc_eni, doc_enel, doc_mm, doc_f24, doc_mutuo])

    # Oggetti fisici di test
    item_pass = PhysicalItem(
        item_name="Passaporto",
        primary_location="Studio",
        detailed_location="1° Cassetto scrivania",
        category="documenti"
    )
    item_chiavi = PhysicalItem(
        item_name="Chiavi di scorta",
        primary_location="Ingresso",
        detailed_location="Svuotatasche",
        category="chiavi"
    )
    item_caricatore = PhysicalItem(
        item_name="Caricatore iPhone",
        primary_location="Camera da letto",
        detailed_location="Comodino destro",
        category="elettronica"
    )
    session.add_all([item_pass, item_chiavi, item_caricatore])
    session.commit()


def test_stemming_plural_to_singular_documents():
    """Verifica che la ricerca al plurale 'bollette' trovi tutti i documenti 'bolletta' (Enel, ENI, MM)."""
    engine = get_engine("sqlite:///:memory:")
    init_db(engine)
    with Session(engine) as session:
        setup_test_data(session)

        # 'bollette' deve trovare tutte e 3 le bollette
        results = search_vault_documents(session, "bollette")
        titles = [d["title"] for d in results]
        assert len(titles) == 3
        assert "Bolletta Enel Energia" in titles
        assert "Bolletta ENI gas e luce S.p.A." in titles
        assert "Bolletta MM S.p.A. — Servizio Idrico" in titles


def test_semantic_concept_synonyms_documents():
    """Verifica la ricerca contestuale/semantica (es. 'tasse' trova F24, 'luce' trova Enel/ENI)."""
    engine = get_engine("sqlite:///:memory:")
    init_db(engine)
    with Session(engine) as session:
        setup_test_data(session)

        # 'tasse' -> trova F24 Agenzia delle Entrate
        tasse_res = search_vault_documents(session, "tasse")
        assert len(tasse_res) >= 1
        assert tasse_res[0]["title"] == "Modello F24 Agenzia delle Entrate"

        # 'fisco' -> trova F24
        fisco_res = search_vault_documents(session, "fisco")
        assert len(fisco_res) >= 1
        assert fisco_res[0]["title"] == "Modello F24 Agenzia delle Entrate"

        # 'mutui' (plurale) -> trova Estratto Conto Mutuo
        mutui_res = search_vault_documents(session, "mutui")
        assert len(mutui_res) == 1
        assert mutui_res[0]["title"] == "Estratto Conto Mutuo Intesa Sanpaolo"


def test_fuzzy_typo_tolerance_documents():
    """Verifica che piccoli refusi digitati dall'utente (es. 'nele' per 'enel') vengano compresi."""
    engine = get_engine("sqlite:///:memory:")
    init_db(engine)
    with Session(engine) as session:
        setup_test_data(session)

        results = search_vault_documents(session, "bolletta nele")
        assert len(results) == 1
        assert results[0]["title"] == "Bolletta Enel Energia"


def test_search_precision_no_cross_contamination():
    """Verifica che una ricerca specifica come 'bolletta enel' non restituisca ENI o il Mutuo."""
    engine = get_engine("sqlite:///:memory:")
    init_db(engine)
    with Session(engine) as session:
        setup_test_data(session)

        results = search_vault_documents(session, "bolletta enel")
        assert len(results) == 1
        assert results[0]["title"] == "Bolletta Enel Energia"


def test_stemming_and_fuzzy_physical_items():
    """Verifica che lo stemming e la tolleranza ai refusi funzionino anche per gli oggetti fisici."""
    engine = get_engine("sqlite:///:memory:")
    init_db(engine)
    with Session(engine) as session:
        setup_test_data(session)

        # Plurale 'passaporti' trova 'Passaporto'
        res1 = search_vault_items(session, "passaporti")
        assert len(res1) == 1
        assert res1[0]["item_name"] == "Passaporto"

        # Singolare 'chiave' trova 'Chiavi di scorta'
        res2 = search_vault_items(session, "chiave")
        assert len(res2) == 1
        assert res2[0]["item_name"] == "Chiavi di scorta"

        # Refuso 'pasaporto' (una 's' sola) trova 'Passaporto'
        res3 = search_vault_items(session, "pasaporto")
        assert len(res3) == 1
        assert res3[0]["item_name"] == "Passaporto"

        # Plurale 'caricatori' trova 'Caricatore iPhone'
        res4 = search_vault_items(session, "caricatori")
        assert len(res4) == 1
        assert res4[0]["item_name"] == "Caricatore iPhone"


def test_collana_rossa_no_f24_cross_contamination():
    """Verifica che cercare 'collana rossa' non restituisca per errore F24 con cognome 'Rossi' nella sintesi."""
    engine = get_engine("sqlite:///:memory:")
    init_db(engine)
    with Session(engine) as session:
        setup_test_data(session)
        # setup_test_data include "Modello F24 Agenzia delle Entrate" con 'Rossi Leo' nel riepilogo
        docs = search_vault_documents(session, "collana rossa")
        assert len(docs) == 0
