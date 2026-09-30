"""
Test suite esaustiva per il Motore di Ricerca Ibrido ad Alta Precisione (99.999%),
pgvector / SQLite fallback, pre-filtro deterministico e Smart Router Agentico.
"""
import pytest
from datetime import date
from sqlalchemy.orm import Session

from app.models.database import init_db, SessionLocal, Document, DocumentEmbedding
from app.services.query_normalizer import (
    validate_codice_fiscale,
    validate_partita_iva,
    validate_iban,
    validate_targa_italiana,
    extract_deterministic_entities,
    normalize_query,
)
from app.services.vector_service import (
    chunk_text,
    cosine_similarity,
    generate_embedding,
    store_document_chunks,
    search_vector_semantic,
)
from app.services.search_router import (
    search_exact_sql,
    search_vector_semantic as router_search_vector,
    search_hybrid,
)
from app.services.agent.tools_executor import execute_vault_tool


@pytest.fixture(scope="module")
def setup_database():
    """Inizializza il database SQLite prima di eseguire i test."""
    init_db()
    yield


@pytest.fixture
def db_session(setup_database):
    """Fornisce una sessione di database pulita per ciascun test."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


# ==============================================================================
# 1. TEST UNITARI: VALIDAZIONE CODICE FISCALE (D.M. 23/12/1976 + OMOCODIE)
# ==============================================================================

def test_codice_fiscale_valid():
    """Verifica che codici fiscali italiani validi superino il checksum ufficiale."""
    # Mario Rossi nato il 01/08/1985 a Roma (H501) -> CIN 'Q'
    assert validate_codice_fiscale("RSSMRA85M01H501Q") is True
    # Lettere minuscole e spaziature
    assert validate_codice_fiscale("  rss mra 85m01 h501q  ") is True
    # Altro codice fiscale valido (donna nata il 15/04/1972 a Milano F205 -> 55 in giorno)
    # BNCGLD72D55F205U
    assert validate_codice_fiscale("BNCGLD72D55F205U") is True


def test_codice_fiscale_invalid():
    """Verifica che codici fiscali con checksum errato o caratteri invalidi vengano scartati."""
    # Checksum alterato (Q -> A)
    assert validate_codice_fiscale("RSSMRA85M01H501A") is False
    # Lunghezza errata
    assert validate_codice_fiscale("RSSMRA85M01H501") is False
    assert validate_codice_fiscale("RSSMRA85M01H501QQ") is False
    # Caratteri non ammessi
    assert validate_codice_fiscale("RSSMRA85M01H501!") is False


# ==============================================================================
# 2. TEST UNITARI: PARTITA IVA ITALIANA (11 CIFRE, ALGORITMO DI LUHN)
# ==============================================================================

def test_partita_iva_valid():
    """Verifica la validazione della Partita IVA italiana."""
    assert validate_partita_iva("00743110157") is True


def test_partita_iva_invalid():
    """Verifica che Partite IVA non conformi o con check digit errato vengano rifiutate."""
    # Check digit alterato (7 -> 8)
    assert validate_partita_iva("00743110158") is False
    # Lunghezza errata
    assert validate_partita_iva("0074311015") is False
    assert validate_partita_iva("007431101570") is False
    # Lettere non permesse
    assert validate_partita_iva("0074311015A") is False


# ==============================================================================
# 3. TEST UNITARI: IBAN EUROPEO (ISO 13616 / MOD-97)
# ==============================================================================

def test_iban_valid():
    """Verifica che codici IBAN conformi a MOD-97 vengano validati con successo."""
    assert validate_iban("IT60X0542811101000000123456") is True
    # Spaziature tipiche bancarie
    assert validate_iban("IT60 X054 2811 1010 0000 0123 456") is True


def test_iban_invalid():
    """Verifica che codici IBAN alterati vengano scartati."""
    assert validate_iban("IT60X0542811101000000123457") is False
    assert validate_iban("IT12") is False


# ==============================================================================
# 4. TEST UNITARI: TARGHE AUTOMOBILISTICHE ITALIANE
# ==============================================================================

def test_targa_italiana():
    """Verifica il riconoscimento delle targhe standard e storiche provinciali."""
    assert validate_targa_italiana("AB123CD") is True
    assert validate_targa_italiana("gf987zw") is True
    assert validate_targa_italiana("MI123456") is True
    # Targa con lettere proibite nel formato standard (I, O, Q, U)
    assert validate_targa_italiana("AI123CD") is False
    assert validate_targa_italiana("12345") is False


# ==============================================================================
# 5. TEST: ESTRAZIONE ENTITÀ DETERMINISTICHE (PRE-FILTRO < 1MS, ZERO TOKEN)
# ==============================================================================

def test_extract_deterministic_entities_complete():
    """Verifica l'estrazione combinata di CF, PIVA, IBAN, targhe, fatture, importi e date."""
    query = (
        "Cerca la fattura FT-2024/01 emessa per Mario Rossi con CF RSSMRA85M01H501Q "
        "con accredito su IBAN IT60X0542811101000000123456 e importo pari a € 1.250,50 "
        "relativa al veicolo targa AB123CD del 15/03/2026."
    )
    ent = extract_deterministic_entities(query)

    assert "RSSMRA85M01H501Q" in ent.codici_fiscali
    assert "IT60X0542811101000000123456" in ent.iban
    assert "AB123CD" in ent.targhe
    assert "FT-2024/01" in ent.numeri_fattura
    assert 1250.5 in ent.importi
    assert len(ent.date_puntuali) == 1
    assert ent.date_puntuali[0] == date(2026, 3, 15)
    assert ent.has_exact_identifiers is True


def test_extract_textual_italian_date():
    """Verifica il parsing di date scritte in linguaggio naturale italiano."""
    query = "Bolletta del 28 ottobre 2026 da 64,20 euro"
    ent = extract_deterministic_entities(query)
    assert len(ent.date_puntuali) == 1
    assert ent.date_puntuali[0] == date(2026, 10, 28)
    assert 64.20 in ent.importi


# ==============================================================================
# 6. TEST: CHUNKING VETTORIALE E SIMILARITÀ COSENICA
# ==============================================================================

def test_chunking_with_overlap():
    """Verifica che il chunker suddivida il testo rispettando la dimensione e l'overlap."""
    long_text = "Paragrafo uno di prova molto lungo. " * 30
    chunks = chunk_text(long_text, chunk_size=200, chunk_overlap=50)
    assert len(chunks) > 1
    for ch in chunks:
        assert len(ch) <= 250


def test_cosine_similarity_math():
    """Verifica la correttezza matematica del calcolo della similarità cosenica."""
    v1 = [1.0, 0.0, 0.0]
    v2 = [1.0, 0.0, 0.0]
    v3 = [0.0, 1.0, 0.0]
    v4 = [-1.0, 0.0, 0.0]

    assert pytest.approx(cosine_similarity(v1, v2), 0.001) == 1.0
    assert pytest.approx(cosine_similarity(v1, v3), 0.001) == 0.0
    assert pytest.approx(cosine_similarity(v1, v4), 0.001) == -1.0


# ==============================================================================
# 7. TEST DI INTEGRAZIONE: ARCHIVIAZIONE E RICERCA VETTORIALE (DOCUMENT_EMBEDDINGS)
# ==============================================================================

def test_store_and_search_vector_embeddings(db_session: Session):
    """Verifica l'archiviazione di chunk in document_embeddings e la ricerca semantica."""
    doc = Document(
        title="Referto Visita Cardiologica Dottor Neri",
        file_path="referto_cuore.pdf",
        file_type="pdf",
        doc_type="sanita",
        issuer="Ospedale San Raffaele",
        amount=150.0,
        due_date=date(2026, 5, 20),
        status="quietanzato",
        category="Sanità & Visite",
        summary="Elettrocardiogramma e controllo pressione arteriosa nella norma."
    )
    db_session.add(doc)
    db_session.commit()
    db_session.refresh(doc)

    try:
        # Genera e salva i chunk vettoriali
        content = f"{doc.title}. {doc.summary}. Controllo ecocardiogramma e visita cardiologica specialistica."
        emb_list = store_document_chunks(db_session, doc.id, content, user_id="user_test_1")
        assert len(emb_list) >= 1

        # Ricerca semantica concettuale (senza match esatto del titolo)
        results = search_vector_semantic(db_session, "controllo pressione e cuore", top_k=5, user_id="user_test_1")
        assert len(results) >= 1
        assert results[0]["document_id"] == doc.id
        assert results[0]["score"] > 0.05
    finally:
        db_session.delete(doc)
        db_session.commit()


# ==============================================================================
# 8. TEST ROUTER: RICERCA DETERMINISTICA ESATTA SQL (search_exact_sql)
# ==============================================================================

def test_search_exact_sql_by_code(db_session: Session):
    """Verifica la ricerca esatta B-Tree per codice fiscale e targa."""
    doc1 = Document(
        title="Assicurazione UnipolSai MG4",
        file_path="polizza_mg4.pdf",
        file_type="pdf",
        doc_type="polizza",
        issuer="UnipolSai",
        amount=540.0,
        due_date=date(2026, 9, 1),
        status="da_pagare",
        category="Auto & Moto",
        summary="Polizza RC Auto veicolo targa GF987ZW intestata a CF RSSMRA85M01H501Q"
    )
    db_session.add(doc1)
    db_session.commit()
    db_session.refresh(doc1)

    try:
        # Ricerca per codice fiscale esatto
        res_cf = search_exact_sql(db_session, {"codice_fiscale": "RSSMRA85M01H501Q"})
        assert len(res_cf) >= 1
        assert res_cf[0]["id"] == doc1.id
        assert any("codice_fiscale" in f for f in res_cf[0]["matched_fields"])

        # Ricerca per targa esatta
        res_plate = search_exact_sql(db_session, {"targa": "GF987ZW"})
        assert len(res_plate) >= 1
        assert res_plate[0]["id"] == doc1.id

        # Ricerca con codice inesistente -> 0 risultati
        res_empty = search_exact_sql(db_session, {"codice_fiscale": "BNCGLD72D55F205S"})
        assert len(res_empty) == 0
    finally:
        db_session.delete(doc1)
        db_session.commit()


# ==============================================================================
# 9. TEST ROUTER: RICERCA IBRIDA CON RRF ED EXACT-MATCH BOOST (+1.0)
# ==============================================================================

def test_search_hybrid_boost(db_session: Session):
    """
    Verifica che nella ricerca ibrida un documento con codice rigido esatto
    riceva l'Exact-Match Boost (+1.0) e scali al primo posto della classifica.
    """
    doc_target = Document(
        title="Fattura Intervento Elettricista Rossi",
        file_path="fattura_elettricista.pdf",
        file_type="pdf",
        doc_type="fattura",
        issuer="ElettroRossi",
        amount=280.0,
        due_date=date(2026, 6, 10),
        status="da_pagare",
        category="Casa & Manutenzione",
        summary="Riparazione quadro elettrico per Mario Rossi CF RSSMRA85M01H501Q fattura n. FT-2026/88"
    )
    doc_other = Document(
        title="Preventivo Impianto Elettrico Generale",
        file_path="preventivo_generale.pdf",
        file_type="pdf",
        doc_type="preventivo",
        issuer="ElettroRossi",
        amount=1200.0,
        due_date=None,
        status="archiviato",
        category="Casa & Manutenzione",
        summary="Valutazione costi rifacimento impianto elettrico casa e quadro elettrico."
    )
    db_session.add_all([doc_target, doc_other])
    db_session.commit()
    db_session.refresh(doc_target)
    db_session.refresh(doc_other)

    try:
        # Indicizza frammenti vettoriali per entrambi
        store_document_chunks(db_session, doc_target.id, doc_target.title + " " + doc_target.summary)
        store_document_chunks(db_session, doc_other.id, doc_other.title + " " + doc_other.summary)

        # Query mista: sia concettuale ("quadro elettrico") sia con codice esatto CF
        query = "Cerca il documento per quadro elettrico con CF RSSMRA85M01H501Q"
        hybrid_results = search_hybrid(db_session, query, top_k=5)

        assert len(hybrid_results) >= 1
        # Il documento target con il CF deve essere in prima posizione assoluta
        assert hybrid_results[0]["id"] == doc_target.id
        # Il punteggio deve includere il boost (+1.0)
        assert hybrid_results[0]["rrf_score"] >= 1.0
        assert hybrid_results[0]["match_type"] in ("hybrid_boosted", "exact_code")
    finally:
        db_session.delete(doc_target)
        db_session.delete(doc_other)
        db_session.commit()


# ==============================================================================
# 10. TEST MULTI-TENANCY READY (ISOLAMENTO PER USER_ID)
# ==============================================================================

def test_multi_tenancy_vector_isolation(db_session: Session):
    """Verifica che query con user_id non espongano frammenti o documenti di altri utenti."""
    doc_user_a = Document(
        user_id="user_alpha",
        title="Documento Riservato Utente A",
        file_path="doc_a.pdf",
        file_type="pdf",
        doc_type="riservato",
        summary="Informazioni strettamente personali per Alpha."
    )
    doc_user_b = Document(
        user_id="user_beta",
        title="Documento Riservato Utente B",
        file_path="doc_b.pdf",
        file_type="pdf",
        doc_type="riservato",
        summary="Informazioni strettamente personali per Beta."
    )
    db_session.add_all([doc_user_a, doc_user_b])
    db_session.commit()
    db_session.refresh(doc_user_a)
    db_session.refresh(doc_user_b)

    try:
        store_document_chunks(db_session, doc_user_a.id, doc_user_a.summary, user_id="user_alpha")
        store_document_chunks(db_session, doc_user_b.id, doc_user_b.summary, user_id="user_beta")

        # Utente Alpha non deve vedere i documenti di Beta
        results_alpha = search_vector_semantic(db_session, "informazioni personali", user_id="user_alpha")
        doc_ids_alpha = [r["document_id"] for r in results_alpha]
        assert doc_user_a.id in doc_ids_alpha
        assert doc_user_b.id not in doc_ids_alpha
    finally:
        db_session.delete(doc_user_a)
        db_session.delete(doc_user_b)
        db_session.commit()


# ==============================================================================
# 11. TEST TOOL EXECUTION TRAMITE AGENTE
# ==============================================================================

def test_tools_executor_new_search_tools(db_session: Session):
    """Verifica che i nuovi tool siano eseguibili tramite execute_vault_tool."""
    # Test search_exact_sql via execute_vault_tool
    res1 = execute_vault_tool("search_exact_sql", {"codice_fiscale": "RSSMRA85M01H501Q"}, db_session)
    assert "found_documents" in res1
    assert "total_matches" in res1

    # Test search_vector_semantic via execute_vault_tool
    res2 = execute_vault_tool("search_vector_semantic", {"concept": "bolletta luce"}, db_session)
    assert "found_documents" in res2
    assert "total_matches" in res2

    # Test search_hybrid via execute_vault_tool
    res3 = execute_vault_tool("search_hybrid", {"query_text": "fattura Enel € 64,20"}, db_session)
    assert "found_documents" in res3
    assert "total_matches" in res3
