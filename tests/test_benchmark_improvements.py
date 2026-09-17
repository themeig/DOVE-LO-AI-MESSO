from datetime import date
from sqlalchemy.orm import Session

from app.models.database import Document, PhysicalItem, init_db, get_engine
from app.services.agent_service import AgenticChatService
from app.services.search_service import search_vault_documents


def test_q100_patente_mario_rossi_deadline_and_search():
    engine = get_engine("sqlite:///:memory:")
    init_db(engine)
    with Session(engine) as session:
        doc_patente = Document(
            title="Patente di Guida Mario Rossi",
            file_path="uploads/patente_mario.pdf",
            file_type="pdf",
            doc_type="patente",
            issuer="Ministero delle Infrastrutture e dei Trasporti",
            amount=None,
            due_date=date(2031, 5, 18),
            status="archiviato",
            summary="Patente di guida categoria B intestata a Mario Rossi con scadenza al 18/05/2031."
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
            summary="Bolletta luce in scadenza."
        )
        session.add_all([doc_patente, doc_enel])
        session.commit()

        # 1. search_vault_documents con la domanda completa del benchmark
        query = "Qual è la data di scadenza della patente di Mario Rossi?"
        res = search_vault_documents(session, query)
        assert len(res) >= 1
        assert res[0]["id"] == doc_patente.id
        assert res[0]["due_date"] == "2031-05-18"

        # 2. get_upcoming_deadlines con query opzionale include anche documenti archiviati
        agent = AgenticChatService()
        deadlines_res = agent.execute_tool("get_upcoming_deadlines", {"query": "patente"}, session)
        found_titles = [d["title"] for d in deadlines_res.get("deadlines", [])]
        assert "Patente di Guida Mario Rossi" in found_titles


def test_q40_garanzia_amazon_iphone_expiration():
    engine = get_engine("sqlite:///:memory:")
    init_db(engine)
    with Session(engine) as session:
        doc_garanzia = Document(
            title="Garanzia Amazon iPhone 15 Pro",
            file_path="uploads/garanzia_iphone.pdf",
            file_type="pdf",
            doc_type="garanzia",
            issuer="Amazon EU Sarl",
            amount=1199.00,
            due_date=date(2026, 11, 15),
            status="archiviato",
            summary="Certificato di garanzia legale Amazon per acquisto smartphone Apple iPhone 15 Pro."
        )
        session.add(doc_garanzia)
        session.commit()

        query = "Quando scade la garanzia Amazon dell'iPhone?"
        res = search_vault_documents(session, query)
        assert len(res) >= 1
        assert res[0]["id"] == doc_garanzia.id
        assert res[0]["due_date"] == "2026-11-15"


def test_q77_azione_rinnovo_patente():
    engine = get_engine("sqlite:///:memory:")
    init_db(engine)
    with Session(engine) as session:
        doc_patente = Document(
            title="Patente B Mario Rossi",
            file_path="uploads/patente.pdf",
            file_type="pdf",
            doc_type="patente",
            issuer="MIT",
            due_date=date(2031, 5, 18),
            status="archiviato",
            summary="Patente di guida con scadenza di validità al 18 maggio 2031."
        )
        session.add(doc_patente)
        session.commit()

        # Il verbo 'rinnovare' si collega a patente e scadenza tramite CONCEPT_SYNONYMS
        query = "Entro quando devo rinnovare la patente di Mario Rossi?"
        res = search_vault_documents(session, query)
        assert len(res) >= 1
        assert res[0]["id"] == doc_patente.id


def test_q54_quanti_modelli_f24_full_sentence_stopwords():
    engine = get_engine("sqlite:///:memory:")
    init_db(engine)
    with Session(engine) as session:
        doc1 = Document(
            title="Modello F24 Acconto Giugno",
            file_path="uploads/f24_1.pdf",
            file_type="pdf",
            doc_type="f24",
            issuer="Agenzia delle Entrate",
            amount=450.00,
            due_date=date(2026, 6, 16),
            status="quietanzato",
            summary="Versamento F24 prima rata."
        )
        doc2 = Document(
            title="Modello F24 Saldo Novembre",
            file_path="uploads/f24_2.pdf",
            file_type="pdf",
            doc_type="f24",
            issuer="Agenzia delle Entrate",
            amount=520.00,
            due_date=date(2026, 11, 30),
            status="da_pagare",
            summary="Versamento F24 seconda rata."
        )
        session.add_all([doc1, doc2])
        session.commit()

        query = "Quanti modelli F24 risultano archiviati nel caveau?"
        res = search_vault_documents(session, query)
        found_ids = [d["id"] for d in res]
        assert doc1.id in found_ids
        assert doc2.id in found_ids


def test_q99_hallucination_prevention_trap_fine():
    engine = get_engine("sqlite:///:memory:")
    init_db(engine)
    with Session(engine) as session:
        # Documento trappola: bolletta pagata a luglio 2026 (contiene 'pagato', 'luglio', '2026')
        doc_trappola = Document(
            title="Bolletta A2A Luce Luglio",
            file_path="uploads/a2a.pdf",
            file_type="pdf",
            doc_type="bolletta",
            issuer="A2A Energia",
            amount=95.00,
            due_date=date(2026, 7, 20),
            status="quietanzato",
            summary="Importo pagato regolarmente nel mese di luglio 2026."
        )
        session.add(doc_trappola)
        session.commit()

        # Domanda trabocchetto: la multa autovelox non esiste affatto!
        query = "Quanto ho pagato per la multa dell'autovelox di luglio 2026?"
        res = search_vault_documents(session, query)
        # Anchor Subject Validation DEVE bloccare la bolletta e restituire 0 risultati
        assert len(res) == 0

        # Il fallback deterministico dell'agente DEVE dare risposta negativa pulita senza allucinare
        agent = AgenticChatService()
        reply = agent._fallback_deterministic_response(query, query.lower(), session, thread_id="general")
        assert reply.action in ["search_vault", "REPLY"]
        assert reply.documents is None or len(reply.documents) == 0
        assert "non ho trovato" in reply.reply.lower()


def test_q92_scontrino_hera_acqua():
    engine = get_engine("sqlite:///:memory:")
    init_db(engine)
    with Session(engine) as session:
        doc_hera = Document(
            title="Fattura Hera Servizio Idrico",
            file_path="uploads/hera_acqua.pdf",
            file_type="pdf",
            doc_type="bolletta",
            issuer="Hera Comm",
            amount=42.10,
            due_date=date(2026, 10, 10),
            status="da_pagare",
            summary="Bolletta servizio idrico integrato acqua potabile."
        )
        session.add(doc_hera)
        session.commit()

        # 'Scontrino' mappa su ricevuta/fattura/bolletta, 'hera' su acqua/bolletta
        query = "Scontrino Hera acqua"
        res = search_vault_documents(session, query)
        assert len(res) >= 1
        assert res[0]["id"] == doc_hera.id


def test_q93_foto_ricevuta_730_format_boost():
    engine = get_engine("sqlite:///:memory:")
    init_db(engine)
    with Session(engine) as session:
        doc_foto_730 = Document(
            title="Ricevuta Modello 730",
            file_path="uploads/foto_ricevuta_730.jpg",
            file_type="image",
            doc_type="ricevuta",
            issuer="CAF ACLI",
            amount=None,
            due_date=None,
            status="archiviato",
            summary="Scatto fotografico della ricevuta di trasmissione modello 730 per detrazioni."
        )
        doc_guida_pdf = Document(
            title="Guida Compilazione 730",
            file_path="uploads/guida_730.pdf",
            file_type="pdf",
            doc_type="generico",
            issuer="Agenzia Entrate",
            amount=None,
            due_date=None,
            status="archiviato",
            summary="Manuale informativo sul modello 730."
        )
        session.add_all([doc_foto_730, doc_guida_pdf])
        session.commit()

        query = "Foto ricevuta 730"
        res = search_vault_documents(session, query)
        assert len(res) >= 1
        assert res[0]["id"] == doc_foto_730.id
