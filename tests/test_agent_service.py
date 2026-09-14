from datetime import date
from sqlalchemy.orm import Session
from app.models.database import Document, PhysicalItem, init_db, get_engine
from app.services.agent_service import AgenticChatService, filter_relevant_documents


def test_search_vault_precision_no_unrelated_documents():
    engine = get_engine("sqlite:///:memory:")
    init_db(engine)
    with Session(engine) as session:
        # Documento 1: Mutuo
        doc_mutuo = Document(
            title="Estratto Conto Mutuo Intesa Sanpaolo",
            file_path="uploads/mutuo.pdf",
            file_type="pdf",
            doc_type="mutuo",
            issuer="Intesa Sanpaolo",
            amount=841.00,
            due_date=date(2026, 10, 1),
            status="da_pagare",
            summary="Estratto conto mutuo tasso fisso. Rata di ottobre 2026 totale 841 euro con addebito previsto."
        )
        # Documento 2: Bolletta Gas (contiene 'addebito', 'scadenza', 'ottobre')
        doc_eni = Document(
            title="Bolletta ENI gas e luce S.p.A.",
            file_path="uploads/eni.pdf",
            file_type="pdf",
            doc_type="bolletta",
            issuer="ENI gas e luce",
            amount=79.30,
            due_date=date(2026, 10, 5),
            status="da_pagare",
            summary="Bolletta gas naturale con scadenza al 05/10/2026. L'addebito è previsto su carta di credito."
        )
        # Documento 3: Bolletta Acqua (contiene 'scadenza', 'ottobre', 'pagamento')
        doc_mm = Document(
            title="Bolletta MM S.p.A. — Metropolitana Milanese",
            file_path="uploads/mm.pdf",
            file_type="pdf",
            doc_type="bolletta",
            issuer="MM S.p.A.",
            amount=68.00,
            due_date=date(2026, 10, 15),
            status="da_pagare",
            summary="Bolletta del servizio idrico integrato. Scadenza di pagamento 15 ottobre 2026."
        )
        # Documento 4: F24 (contiene 'rata', 'acconto', 'scadenza')
        doc_f24 = Document(
            title="F24 Agenzia delle Entrate",
            file_path="uploads/f24.pdf",
            file_type="pdf",
            doc_type="f24",
            issuer="Agenzia delle Entrate",
            amount=320.00,
            due_date=date(2026, 11, 30),
            status="da_pagare",
            summary="Modello F24 versamento acconto IRPEF seconda rata."
        )
        session.add_all([doc_mutuo, doc_eni, doc_mm, doc_f24])
        session.commit()

        agent = AgenticChatService()

        # Verifica 1: "dammi il documento del mutuo"
        res1 = agent.execute_tool("search_vault", {"query": "dammi il documento del mutuo"}, session)
        found_docs1 = res1.get("found_documents", [])
        assert len(found_docs1) == 1
        assert found_docs1[0]["title"] == "Estratto Conto Mutuo Intesa Sanpaolo"

        # Verifica 2: "rata del mutuo"
        res2 = agent.execute_tool("search_vault", {"query": "rata del mutuo"}, session)
        found_docs2 = res2.get("found_documents", [])
        assert len(found_docs2) == 1
        assert found_docs2[0]["title"] == "Estratto Conto Mutuo Intesa Sanpaolo"

        # Verifica 3: "scadenza mutuo"
        res3 = agent.execute_tool("search_vault", {"query": "scadenza mutuo"}, session)
        found_docs3 = res3.get("found_documents", [])
        assert len(found_docs3) == 1
        assert found_docs3[0]["title"] == "Estratto Conto Mutuo Intesa Sanpaolo"


def test_search_vault_bolletta_specific():
    engine = get_engine("sqlite:///:memory:")
    init_db(engine)
    with Session(engine) as session:
        doc_eni = Document(
            title="Bolletta ENI gas e luce",
            file_path="uploads/eni.pdf",
            file_type="pdf",
            doc_type="bolletta",
            issuer="ENI gas e luce",
            summary="Bolletta gas naturale."
        )
        doc_enel = Document(
            title="Bolletta Enel Energia",
            file_path="uploads/enel.pdf",
            file_type="pdf",
            doc_type="bolletta",
            issuer="Enel Energia",
            summary="Bolletta energia elettrica luce."
        )
        session.add_all([doc_eni, doc_enel])
        session.commit()

        agent = AgenticChatService()
        res = agent.execute_tool("search_vault", {"query": "bolletta enel"}, session)
        found = res.get("found_documents", [])
        assert len(found) == 1
        assert found[0]["title"] == "Bolletta Enel Energia"


def test_filter_relevant_documents():
    docs = [
        {"title": "Estratto Conto Mutuo Intesa Sanpaolo", "issuer": "Intesa Sanpaolo"},
        {"title": "Bolletta ENI gas e luce", "issuer": "ENI gas e luce"},
        {"title": "Bolletta MM Servizio Idrico", "issuer": "MM S.p.A."}
    ]

    # Scenario 1: L'assistente cita solo il mutuo nel testo
    text1 = "Qui trovi il documento del mutuo:\n\n**Titolo:** Estratto Conto Mutuo Intesa Sanpaolo"
    filtered1 = filter_relevant_documents(docs, text1, "dammi il documento del mutuo")
    assert len(filtered1) == 1
    assert filtered1[0]["title"] == "Estratto Conto Mutuo Intesa Sanpaolo"

    # Scenario 2: Richiesta singolare ("il documento del mutuo")
    text2 = "Ecco cosa ho trovato nel caveau."
    filtered2 = filter_relevant_documents(docs, text2, "dammi il documento del mutuo")
    assert len(filtered2) == 1
    assert filtered2[0]["title"] == "Estratto Conto Mutuo Intesa Sanpaolo"

    # Scenario 3: Richiesta plurale con lista esplicita
    text3 = "Ho trovato queste bollette:\n- Bolletta ENI gas e luce\n- Bolletta MM Servizio Idrico"
    filtered3 = filter_relevant_documents(docs, text3, "mostrami le bollette")
    assert len(filtered3) == 2
    assert {d["title"] for d in filtered3} == {"Bolletta ENI gas e luce", "Bolletta MM Servizio Idrico"}

    # Scenario 4: Richiesta generica di elenco senza citazioni dirette (nessun widget casuale forzato)
    text4 = "Ecco l'elenco dei documenti salvati nel caveau."
    filtered4 = filter_relevant_documents(docs, text4, "elencami i documenti che hai")
    assert filtered4 is None


def test_agent_service_bulk_deletion_intent():
    engine = get_engine("sqlite:///:memory:")
    init_db(engine)
    with Session(engine) as session:
        d1 = Document(title="Bolletta Enel", file_path="uploads/enel.pdf", file_type="pdf", doc_type="bolletta", thread_id="t1", summary="bolletta")
        d2 = Document(title="Bolletta A2A", file_path="uploads/a2a.pdf", file_type="pdf", doc_type="bolletta", thread_id="t1", summary="bolletta")
        d3 = Document(title="Contratto Lavoro", file_path="uploads/contratto.pdf", file_type="pdf", doc_type="contratto", thread_id="t1", summary="contratto")
        session.add_all([d1, d2, d3])
        session.commit()

        agent = AgenticChatService()

        # 1. "elimina tutti i documenti che hai"
        resp_all = agent._handle_deletion_intent("elimina tutti i documenti che hai", "elimina tutti i documenti che hai", session, thread_id="t1")
        assert resp_all is not None
        assert resp_all.action == "REQUEST_DELETE"
        assert resp_all.confirmation["target_type"] == "bulk_documents"
        assert len(resp_all.confirmation["target_ids"]) == 3

        # 2. "elimina tutte le bollette" -> filtra solo bollette
        resp_bollette = agent._handle_deletion_intent("elimina tutte le bollette", "elimina tutte le bollette", session, thread_id="t1")
        assert resp_bollette is not None
        assert resp_bollette.action == "REQUEST_DELETE"
        assert resp_bollette.confirmation["target_type"] == "bulk_documents"
        assert len(resp_bollette.confirmation["target_ids"]) == 2

        # 3. "eliminali" (plural)
        resp_plural = agent._handle_deletion_intent("eliminali", "eliminali", session, thread_id="t1")
        assert resp_plural is not None
        assert resp_plural.action == "REQUEST_DELETE"
        assert resp_plural.confirmation["target_type"] == "bulk_documents"


def test_list_vault_contents_tool():
    engine = get_engine("sqlite:///:memory:")
    init_db(engine)
    with Session(engine) as session:
        # Aggiungi 2 documenti e 1 oggetto fisico
        d1 = Document(title="Bolletta Enel", file_path="uploads/enel.pdf", file_type="pdf", doc_type="bolletta", thread_id="general", summary="bolletta luce")
        d2 = Document(title="F24 Tributi", file_path="uploads/f24.pdf", file_type="pdf", doc_type="f24", thread_id="general", summary="f24")
        item1 = PhysicalItem(item_name="Passaporto", primary_location="Studio", detailed_location="Cassetto 1", thread_id="general")
        session.add_all([d1, d2, item1])
        session.commit()

        agent = AgenticChatService()

        # 1. Recupera solo documenti
        res_docs = agent.execute_tool("list_vault_contents", {"target_type": "documents"}, session, thread_id="general")
        assert res_docs["documents_count"] == 2
        assert res_docs["items_count"] == 0
        assert len(res_docs["documents"]) == 2

        # 2. Recupera solo oggetti fisici
        res_items = agent.execute_tool("list_vault_contents", {"target_type": "physical_items"}, session, thread_id="general")
        assert res_items["documents_count"] == 0
        assert res_items["items_count"] == 1
        assert res_items["physical_items"][0]["item_name"] == "Passaporto"

        # 3. Recupera all
        res_all = agent.execute_tool("list_vault_contents", {"target_type": "all"}, session, thread_id="general")
        assert res_all["documents_count"] == 2
        assert res_all["items_count"] == 1
