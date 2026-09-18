from datetime import date
from sqlalchemy.orm import Session
from app.models.database import Document, PhysicalItem, ChatMessage, init_db, get_engine
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

    # Scenario 5: Richiesta posizione oggetto fisico ("dove è la collana rossa?") con risposta su oggetto ("La 'Collana rossa' si trova in soggiorno. 📍")
    # Non deve MAI allegare documenti non correlati
    docs_unrelated = [{"title": "F24 AGENZIA DELLE ENTRATE", "issuer": "AGENZIA DELLE ENTRATE"}]
    text5 = "La 'Collana rossa' si trova in soggiorno. 📍"
    filtered5 = filter_relevant_documents(docs_unrelated, text5, "dove è la collana rossa?")
    assert filtered5 is None

    # Scenario 6: Richiesta meta/capacità ("cosa puoi fare?") con risposta esplicativa che cita parole come "cucina", "documenti", "bolletta"
    docs_caveau = [
        {"title": "Certificazione Unica CU 2026", "issuer": "Datore di Lavoro"},
        {"title": "Ricevuta Pre-Immatricolazione Università di Pavia", "issuer": "Università di Pavia"},
    ]
    text6 = (
        "Certo, ti spiego subito cosa posso fare per te! Sono il tuo assistente per il caveau.\n"
        "Per i tuoi oggetti fisici: Dimmi 'Ho messo le chiavi di scorta in cucina' e io lo terrò a mente.\n"
        "Per i tuoi documenti digitali: Chiedimi 'Trovami la bolletta Enel' e te li mostrerò subito."
    )
    filtered6 = filter_relevant_documents(docs_caveau, text6, "cosa puoi fare?")
    assert filtered6 is None, "Non deve allegare documenti a domande meta/help ('cosa puoi fare?')"

    # Scenario 7: Prevenzione falsi positivi di sottostringa (es. acronimo 'cu' dentro 'cucina' o 'di' in parole italiane)
    text7 = "Ho annotato che le posizioni in cucina e salotto sono state aggiornate digitalmente."
    filtered7 = filter_relevant_documents(docs_caveau, text7, "dove sono le posizioni?")
    assert filtered7 is None, "'cu' in 'cucina' e 'di' in 'digitalmente' non devono provocare falsi positivi"


def test_agent_meta_question_does_not_attach_documents():
    """Verifica che a fronte di 'cosa puoi fare?' non vengano allegati documenti dal DB."""
    from app.models.database import Document, init_db, get_engine
    from sqlalchemy.orm import Session
    from unittest.mock import patch, MagicMock

    engine = get_engine("sqlite:///:memory:")
    init_db(engine)
    with Session(engine) as session:
        doc1 = Document(
            title="Certificazione Unica CU 2026",
            file_path="uploads/cu2026.pdf",
            file_type="pdf",
            doc_type="fiscale",
            thread_id="t_meta",
            summary="Certificazione unica CU per redditi di lavoro dipendente"
        )
        doc2 = Document(
            title="Ricevuta Pre-Immatricolazione Università di Pavia",
            file_path="uploads/unipv.pdf",
            file_type="pdf",
            doc_type="ricevuta",
            thread_id="t_meta",
            summary="Ricevuta immatricolazione tasse universitarie da pagare"
        )
        session.add_all([doc1, doc2])
        session.commit()

        agent = AgenticChatService()

        # Simula una risposta diretta dell'assistente che spiega cosa può fare citando esempi di cucina e bolletta
        mock_reply = (
            "Certo, ti spiego subito cosa posso fare per te! Sono il tuo assistente personale per il caveau 'Dove lo AI messo'. "
            "Memorizzo la posizione: Dimmi 'Ho messo le chiavi di scorta in cucina'. "
            "Trovo i documenti all'istante: Chiedimi 'Trovami la bolletta Enel' o 'Dammi i documenti di identità'."
        )

        with patch("httpx.Client.post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: {
                    "candidates": [
                        {
                            "content": {
                                "parts": [{"text": mock_reply}]
                            }
                        }
                    ]
                }
            )

            res = agent.run_turn("cosa puoi fare?", session, thread_id="t_meta")
            assert res.documents is None or len(res.documents) == 0, f"Attesi 0 documenti allegati, trovati: {res.documents}"



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


def test_extract_item_and_location():
    agent = AgenticChatService()
    
    # 1. "modifica la posizione della tenda da campeggio e mettila in soggiorno"
    item, loc = agent._extract_item_and_location("modifica la posizione della tenda da campeggio e mettila in soggiorno")
    assert item.lower() == "tenda da campeggio"
    assert loc.lower() == "soggiorno"

    # 2. "sposta la tenda da campeggio in soggiorno"
    item2, loc2 = agent._extract_item_and_location("sposta la tenda da campeggio in soggiorno")
    assert item2.lower() == "tenda da campeggio"
    assert loc2.lower() == "soggiorno"

    # 3. "cambia la posizione del passaporto in studio"
    item3, loc3 = agent._extract_item_and_location("cambia la posizione del passaporto in studio")
    assert item3.lower() == "passaporto"
    assert loc3.lower() == "studio"

    # 4. "metti le chiavi sul comodino"
    item4, loc4 = agent._extract_item_and_location("metti le chiavi sul comodino")
    assert item4.lower() == "chiavi"
    assert loc4.lower() == "comodino"

    # 5. "ora la tenda da campeggio si trova in soggiorno"
    item5, loc5 = agent._extract_item_and_location("ora la tenda da campeggio si trova in soggiorno")
    assert item5.lower() == "tenda da campeggio"
    assert loc5.lower() == "soggiorno"

    # 6. Pronome "mettila in soggiorno" con oggetto nel contesto
    item6, loc6 = agent._extract_item_and_location("mettila in soggiorno", last_item_in_context="Tenda da campeggio")
    assert item6.lower() == "tenda da campeggio"
    assert loc6.lower() == "soggiorno"


def test_store_physical_item_updates_existing_fuzzy():
    engine = get_engine("sqlite:///:memory:")
    init_db(engine)
    with Session(engine) as session:
        # 1. Salva inizialmente "Tenda da campeggio" in "Garage" con dettaglio "Scaffale in fondo"
        item = PhysicalItem(
            item_name="Tenda da campeggio",
            primary_location="Garage",
            detailed_location="Scaffale in fondo",
            thread_id="general"
        )
        session.add(item)
        session.commit()

        agent = AgenticChatService()

        # 2. Aggiorna usando "Tenda da campeggio" verso "Soggiorno"
        res = agent.execute_tool(
            "store_physical_item",
            {"item_name": "tenda da campeggio", "primary_location": "Soggiorno"},
            session,
            thread_id="general"
        )
        assert res["success"] is True
        assert res["primary_location"] == "Soggiorno"
        assert res["detailed_location"] is None

        # Verifica che nel DB ci sia sempre UN solo record aggiornato
        items = session.query(PhysicalItem).all()
        assert len(items) == 1
        assert items[0].primary_location == "Soggiorno"
        assert items[0].detailed_location is None

        # 3. Aggiorna usando abbreviazione "Tenda" verso "Camera da letto"
        res2 = agent.execute_tool(
            "store_physical_item",
            {"item_name": "Tenda", "primary_location": "Camera da letto", "detailed_location": "Armadio"},
            session,
            thread_id="general"
        )
        assert res2["success"] is True
        assert res2["primary_location"] == "Camera da letto"
        assert res2["detailed_location"] == "Armadio"

        items = session.query(PhysicalItem).all()
        assert len(items) == 1
        assert items[0].primary_location == "Camera da letto"
        assert items[0].detailed_location == "Armadio"


def test_flow_modifica_e_query_posizione():
    engine = get_engine("sqlite:///:memory:")
    init_db(engine)
    with Session(engine) as session:
        agent = AgenticChatService()
        agent.settings.OPENROUTER_API_KEY = "" # offline test

        # 1. Memorizza in garage
        r1 = agent.run_turn("Ho messo la tenda da campeggio in garage", session, thread_id="casa")
        assert "garage" in r1.reply.lower()

        item_db = session.query(PhysicalItem).filter(PhysicalItem.thread_id == "casa").first()
        assert item_db is not None
        assert item_db.primary_location.lower() == "garage"

        # 2. Modifica la posizione in soggiorno
        r2 = agent.run_turn("modifica la posizione della tenda da campeggio e mettila in soggiorno", session, thread_id="casa")
        assert "soggiorno" in r2.reply.lower()

        session.refresh(item_db)
        assert item_db.primary_location.lower() == "soggiorno"

        # 3. Chiedi dove si trova
        r3 = agent.run_turn("dove è la tenda da campeggio?", session, thread_id="casa")
        assert "soggiorno" in r3.reply.lower()
        assert "garage" not in r3.reply.lower()

        # 4. Elimina la tenda
        session.delete(item_db)
        session.commit()

        # 5. Chiedi dove si trova dopo l'eliminazione: non deve allucinare il soggiorno, deve dire non trovata
        r4 = agent.run_turn("dove è la tenda da campeggio?", session, thread_id="casa")
        assert "soggiorno" not in r4.reply.lower()
        assert "non ho trovato" in r4.reply.lower()


def test_database_grounding_overrides_chat_history():
    engine = get_engine("sqlite:///:memory:")
    init_db(engine)
    with Session(engine) as session:
        # Inietta nella cronologia della chat messaggi che menzionano oggetti inesistenti o vecchi
        old_msg1 = ChatMessage(
            sender="assistant",
            content="Al momento ho memorizzato la posizione dei seguenti oggetti:\n* Tenda da campeggio: garage\n* Occhiali da sole: custodia",
            thread_id="general"
        )
        old_msg2 = ChatMessage(
            sender="user",
            content="ok grazie",
            thread_id="general"
        )
        session.add_all([old_msg1, old_msg2])
        session.commit()

        agent = AgenticChatService()
        agent.settings.OPENROUTER_API_KEY = "" # offline

        # 1. Nel DB non ci sono oggetti: la risposta DEVE dire che non ci sono oggetti, ignorando la chat vecchia
        res_empty = agent.run_turn("che oggetti hai?", session, thread_id="general")
        assert "tenda" not in res_empty.reply.lower()
        assert "occhiali" not in res_empty.reply.lower()
        assert "non sono presenti oggetti" in res_empty.reply.lower() or "non ho oggetti" in res_empty.reply.lower()

        # 2. Ora aggiungiamo SOLO il passaporto in DB
        item_pass = PhysicalItem(item_name="Passaporto", primary_location="Studio", thread_id="general")
        session.add(item_pass)
        session.commit()

        # 3. La risposta DEVE contenere solo il passaporto e ZERO tenda da campeggio
        res_one = agent.run_turn("che oggetti hai?", session, thread_id="general")
        assert "passaporto" in res_one.reply.lower()
        assert "tenda" not in res_one.reply.lower()
        assert "occhiali" not in res_one.reply.lower()


def test_llm_postprocessing_guardrail_prevents_context_hallucinations():
    from unittest.mock import patch, MagicMock

    engine = get_engine("sqlite:///:memory:")
    init_db(engine)
    with Session(engine) as session:
        agent = AgenticChatService()
        agent.settings.OPENROUTER_API_KEY = "mock_key"

        # Scenario 1: Il modello in r2 prova ad allucinare una lista di oggetti mentre il DB è vuoto
        mock_r1 = MagicMock()
        mock_r1.status_code = 200
        mock_r1.json.return_value = {
            "choices": [{
                "message": {
                    "role": "assistant",
                    "tool_calls": [{
                        "id": "call_123",
                        "function": {
                            "name": "list_vault_contents",
                            "arguments": '{"target_type": "physical_items"}'
                        }
                    }]
                }
            }]
        }

        mock_r2_hallucinated = MagicMock()
        mock_r2_hallucinated.status_code = 200
        mock_r2_hallucinated.json.return_value = {
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": "Ecco gli oggetti trovati:\n- 📍 **Tenda da campeggio**: Garage"
                }
            }]
        }

        with patch("httpx.post", side_effect=[mock_r1, mock_r2_hallucinated]):
            res = agent.run_turn("elenco oggetti", session, thread_id="general")
            # Il guardrail DEVE bloccare l'allucinazione e riportare che il DB è vuoto
            assert "tenda" not in res.reply.lower()
            assert "non sono presenti oggetti" in res.reply.lower()

        # Scenario 2: L'utente cerca un oggetto inesistente nel DB, il modello in r2 allucina la posizione dalla chat
        mock_r1_search = MagicMock()
        mock_r1_search.status_code = 200
        mock_r1_search.json.return_value = {
            "choices": [{
                "message": {
                    "role": "assistant",
                    "tool_calls": [{
                        "id": "call_456",
                        "function": {
                            "name": "search_vault",
                            "arguments": '{"query": "tenda"}'
                        }
                    }]
                }
            }]
        }

        mock_r2_search_hallucinated = MagicMock()
        mock_r2_search_hallucinated.status_code = 200
        mock_r2_search_hallucinated.json.return_value = {
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": "📍 La tenda da campeggio si trova in soggiorno."
                }
            }]
        }

        with patch("httpx.post", side_effect=[mock_r1_search, mock_r2_search_hallucinated]):
            res_search = agent.run_turn("dove è la tenda?", session, thread_id="general")
            # Il guardrail DEVE bloccare l'allucinazione e comunicare che non è stata trovata nel database
            assert "soggiorno" not in res_search.reply.lower()
            assert "non ho trovato corrispondenze nel database" in res_search.reply.lower() or "non ho trovato" in res_search.reply.lower()


def test_rename_vault_document_tool():
    engine = get_engine("sqlite:///:memory:")
    init_db(engine)
    with Session(engine) as session:
        doc = Document(
            title="Foto generica volante",
            file_path="uploads/volante.jpg",
            file_type="jpeg",
            doc_type="foto_oggetto",
            summary="Base volante rapido"
        )
        session.add(doc)
        session.commit()

        agent = AgenticChatService()
        res = agent.execute_tool("rename_vault_document", {"new_title": "Base Volante Fanatec"}, session)
        assert res.get("success") is True
        assert res.get("new_title") == "Base Volante Fanatec"

        # Verifica aggiornamento su database
        db_doc = session.query(Document).filter(Document.id == doc.id).first()
        assert db_doc.title == "Base Volante Fanatec"


def test_conversational_rename_turn():
    engine = get_engine("sqlite:///:memory:")
    init_db(engine)
    with Session(engine) as session:
        doc = Document(
            title="Immagine sconosciuta",
            file_path="uploads/img.jpg",
            file_type="jpeg",
            doc_type="foto",
            summary="Dispositivo meccanico"
        )
        session.add(doc)
        session.commit()

        agent = AgenticChatService()
        agent.settings.OPENROUTER_API_KEY = "" # Test deterministic/offline fallback flow

        res = agent.run_turn("chiamalo Base Volante Fanatec", session)
        assert res.action == "rename_vault_document"
        assert "Base Volante Fanatec" in res.reply

        # Verifica DB
        db_doc = session.query(Document).filter(Document.id == doc.id).first()
        assert db_doc.title == "Base Volante Fanatec"


def test_show_document_card_tool():
    engine = get_engine("sqlite:///:memory:")
    init_db(engine)
    with Session(engine) as session:
        doc = Document(
            title="F24 Agenzia delle Entrate",
            file_path="uploads/f24.pdf",
            file_type="pdf",
            doc_type="f24",
            issuer="Agenzia delle Entrate",
            amount=1240.00,
            summary="Modello F24 versamento acconto imposte."
        )
        session.add(doc)
        session.commit()

        agent = AgenticChatService()

        # Test 1: Tramite document_id
        res1 = agent.execute_tool("show_document_card", {"document_id": doc.id}, session)
        assert res1.get("success") is True
        assert res1["document"]["title"] == "F24 Agenzia delle Entrate"
        assert res1["document"]["id"] == doc.id
        assert len(res1["documents"]) == 1

        # Test 2: Tramite document_title o query
        res2 = agent.execute_tool("show_document_card", {"document_title": "f24"}, session)
        assert res2.get("success") is True
        assert res2["document"]["id"] == doc.id

        # Test 3: Senza parametri (recupera l'ultimo documento nel canale)
        res3 = agent.execute_tool("show_document_card", {}, session)
        assert res3.get("success") is True
        assert res3["document"]["id"] == doc.id


def test_conversational_download_request_shows_card():
    engine = get_engine("sqlite:///:memory:")
    init_db(engine)
    with Session(engine) as session:
        doc = Document(
            title="F24 Agenzia delle Entrate",
            file_path="uploads/f24.pdf",
            file_type="pdf",
            doc_type="f24",
            issuer="Agenzia delle Entrate",
            amount=1240.00,
            thread_id="general",
            summary="Modello F24 versamento acconto imposte."
        )
        session.add(doc)

        # Simula il messaggio precedente dell'assistente che cita l'F24 (esattamente come nello screenshot)
        last_asst_msg = ChatMessage(
            sender="assistant",
            content="Al momento, l'unica bolletta/scadenza in sospeso che ho registrato è:\n* F24 Agenzia delle Entrate 🏛️\n* Importo: 1.240,00 €\n* Scadenza: 30 novembre 2026",
            thread_id="general"
        )
        session.add(last_asst_msg)
        session.commit()

        agent = AgenticChatService()
        agent.settings.OPENROUTER_API_KEY = "" # deterministic fallback

        # L'utente risponde: "ok voglio scaricarla"
        res = agent.run_turn("ok voglio scaricarla", session, thread_id="general")
        assert res.documents is not None
        assert len(res.documents) == 1
        assert res.documents[0]["title"] == "F24 Agenzia delle Entrate"
        assert "[Link per scaricare" not in res.reply


def test_affirmative_response_picks_proposed_document_not_unrelated():
    engine = get_engine("sqlite:///:memory:")
    init_db(engine)
    with Session(engine) as session:
        doc_mg = Document(
            title="zip mg4",
            file_path="uploads/mg4.png",
            file_type="png",
            doc_type="foto",
            summary="File compressi e dati relativi a modelli MG4."
        )
        doc_pavia = Document(
            title="Ricevuta Pre-Immatricolazione Università di Pavia",
            file_path="uploads/pavia.pdf",
            file_type="pdf",
            doc_type="ricevuta",
            summary="Ricevuta iscrizione università."
        )
        session.add_all([doc_mg, doc_pavia])

        # L'assistente chiede se mostrare zip mg4 (esattamente come nel messaggio 1040 dello screenshot)
        asst_msg = ChatMessage(
            sender="assistant",
            content='Ho nel caveau un file chiamato "**zip mg4**" che contiene informazioni relative a modelli MG4.\n\nDesideri che ti mostri i dettagli di questo file?',
            thread_id="general"
        )
        session.add(asst_msg)
        session.commit()

        agent = AgenticChatService()
        agent.settings.OPENROUTER_API_KEY = "" # deterministic fallback

        # L'utente risponde "si"
        res = agent.run_turn("si", session, thread_id="general")
        assert res.documents is not None
        assert len(res.documents) == 1
        assert res.documents[0]["title"] == "zip mg4"
        assert "pavia" not in res.reply.lower()
        assert "immatricolazione" not in res.reply.lower()


def test_multi_document_affirmative_and_download_flow():
    """Verifica il flusso completo di richiesta multipla ('si di entrambi', 'voglio fare il download', 'entrambi')."""
    engine = get_engine("sqlite:///:memory:")
    init_db(engine)
    with Session(engine) as session:
        doc_ts = Document(
            title="Tessera Sanitaria Italiana",
            file_path="uploads/tessera.pdf",
            file_type="pdf",
            doc_type="sanitario",
            summary="Dati anagrafici e codice fiscale."
        )
        doc_pavia = Document(
            title="Ricevuta Pre-Immatricolazione Università di Pavia",
            file_path="uploads/pavia.pdf",
            file_type="pdf",
            doc_type="ricevuta",
            summary="Ricevuta iscrizione università."
        )
        session.add_all([doc_ts, doc_pavia])

        # 1. L'assistente elenca entrambi i documenti come nello screenshot
        asst_msg1 = ChatMessage(
            sender="assistant",
            content=(
                "Ho trovato i seguenti documenti inerenti all'identificazione personale:\n"
                "* 📄 Tessera Sanitaria Italiana : Contiene i tuoi dati anagrafici.\n"
                "* 📄 Ricevuta Pre-Immatricolazione Università di Pavia : Riporta i tuoi dati anagrafici.\n\n"
                "Desideri che ti mostri la scheda di uno di questi documenti in particolare?"
            ),
            thread_id="general"
        )
        session.add(asst_msg1)
        session.commit()

        agent = AgenticChatService()
        agent.settings.OPENROUTER_API_KEY = "" # deterministic fallback

        # 2. L'utente risponde: "si di entrambi"
        res1 = agent.run_turn("si di entrambi", session, thread_id="general")
        assert res1.documents is not None, "Le schede devono essere allegate!"
        assert len(res1.documents) == 2, "Devono essere allegate entrambe le schede!"
        titles1 = [d["title"] for d in res1.documents]
        assert "Tessera Sanitaria Italiana" in titles1
        assert "Ricevuta Pre-Immatricolazione Università di Pavia" in titles1
        assert "singolarmente" not in res1.reply.lower()

        # Salviamo la risposta nella cronologia
        session.add(ChatMessage(sender="assistant", content=res1.reply, thread_id="general"))
        session.commit()

        # 3. L'utente risponde: "voglio fare il download"
        res2 = agent.run_turn("voglio fare il download", session, thread_id="general")
        assert res2.documents is not None, "Il download deve allegare le schede con pulsante!"
        assert len(res2.documents) == 2
        assert "singolarmente" not in res2.reply.lower()

        # 4. L'utente risponde: "entrambi"
        res3 = agent.run_turn("entrambi", session, thread_id="general")
        assert res3.documents is not None
        assert len(res3.documents) == 2
        assert "singolarmente" not in res3.reply.lower()


def test_delete_vault_record_tool_bulk_and_single():
    """Verifica che il tool delete_vault_record supporti sia eliminazioni singole che in blocco (es. bulk_documents)."""
    engine = get_engine("sqlite:///:memory:")
    init_db(engine)
    with Session(engine) as session:
        d1 = Document(title="Bolletta Enel", file_path="uploads/enel.pdf", file_type="pdf", doc_type="bolletta", summary="Bolletta luce")
        d2 = Document(title="Bolletta A2A", file_path="uploads/a2a.pdf", file_type="pdf", doc_type="bolletta", summary="Bolletta gas")
        d3 = Document(title="Ricevuta IMU F24", file_path="uploads/f24.pdf", file_type="pdf", doc_type="f24", summary="Tributo IMU")
        session.add_all([d1, d2, d3])
        session.commit()

        agent = AgenticChatService()

        # 1. Eliminazione totale ("bulk_documents")
        res_all = agent.execute_tool("delete_vault_record", {"target_type": "bulk_documents", "title": "Tutti i documenti"}, session)
        assert res_all["status"] == "pending_confirmation"
        assert res_all["confirmation"]["target_type"] == "bulk_documents"
        assert len(res_all["confirmation"]["target_ids"]) == 3
        assert d1.id in res_all["confirmation"]["target_ids"]
        assert d2.id in res_all["confirmation"]["target_ids"]
        assert d3.id in res_all["confirmation"]["target_ids"]

        # 2. Eliminazione categoria ("bolletta")
        res_bollette = agent.execute_tool("delete_vault_record", {"target_type": "bulk_documents", "title": "Tutte le bollette", "category": "bolletta"}, session)
        assert res_bollette["status"] == "pending_confirmation"
        assert len(res_bollette["confirmation"]["target_ids"]) == 2
        assert d1.id in res_bollette["confirmation"]["target_ids"]
        assert d2.id in res_bollette["confirmation"]["target_ids"]
        assert d3.id not in res_bollette["confirmation"]["target_ids"]

        # 3. Eliminazione singolo documento per titolo
        res_single = agent.execute_tool("delete_vault_record", {"target_type": "document", "title": "Ricevuta IMU F24"}, session)
        assert res_single["status"] == "pending_confirmation"
        assert res_single["confirmation"]["target_type"] == "document"
        assert res_single["confirmation"]["target_id"] == d3.id


def test_proactive_multi_document_cards_emission_no_confirmation_needed():
    """Scenario 1: Se una ricerca o richiesta trova 2-3 documenti pertinenti (es. 'dammi i documenti di identità'),
    l'agente emette proattivamente tutte le schede e non chiede 'quale preferisci?' o 'quale vuoi?'."""
    engine = get_engine("sqlite:///:memory:")
    init_db(engine)
    with Session(engine) as session:
        doc_ts = Document(
            title="Tessera Sanitaria Italiana",
            file_path="uploads/tessera.pdf",
            file_type="pdf",
            doc_type="sanitario",
            summary="Dati anagrafici e codice fiscale."
        )
        doc_pavia = Document(
            title="Ricevuta Pre-Immatricolazione Università di Pavia",
            file_path="uploads/pavia.pdf",
            file_type="pdf",
            doc_type="ricevuta",
            summary="Ricevuta iscrizione università con dati anagrafici identificativi."
        )
        doc_mutuo = Document(
            title="Estratto Conto Mutuo Intesa",
            file_path="uploads/mutuo.pdf",
            file_type="pdf",
            doc_type="mutuo",
            summary="Estratto conto mutuo banca."
        )
        session.add_all([doc_ts, doc_pavia, doc_mutuo])
        session.commit()

        agent = AgenticChatService()
        agent.settings.OPENROUTER_API_KEY = "" # deterministic fallback

        # Richiesta utente: "dammi i documenti di identità"
        res = agent.run_turn("dammi i documenti di identità", session, thread_id="general")

        # Verifica che entrambe le card siano state allegate
        assert res.documents is not None, "Le schede documento devono essere allegate!"
        assert len(res.documents) == 2, f"Dovevano essere allegate 2 schede, trovate {len(res.documents)}"
        titles = [d["title"] for d in res.documents]
        assert "Tessera Sanitaria Italiana" in titles
        assert "Ricevuta Pre-Immatricolazione Università di Pavia" in titles
        assert "Estratto Conto Mutuo Intesa" not in titles

        # Verifica che la risposta NON contenga domande di esitazione superflue
        reply_low = res.reply.lower()
        assert "quale preferisci" not in reply_low
        assert "quale desideri" not in reply_low
        assert "uno in particolare" not in reply_low
        assert "singolarmente" not in reply_low


def test_collective_affirmative_scaricali_and_entrambi_resolution():
    """Scenario 2: Se l'utente dice 'scaricali', 'entrambi', 'mostrali tutti' subito dopo che sono stati elencati più documenti,
    l'assistente risolve tutti i documenti e mostra le schede senza dire 'devi farlo singolarmente'."""
    engine = get_engine("sqlite:///:memory:")
    init_db(engine)
    with Session(engine) as session:
        doc1 = Document(
            title="Bolletta Enel Luce",
            file_path="uploads/enel.pdf",
            file_type="pdf",
            doc_type="bolletta",
            summary="Bolletta energia elettrica."
        )
        doc2 = Document(
            title="Bolletta Gas Eni",
            file_path="uploads/eni.pdf",
            file_type="pdf",
            doc_type="bolletta",
            summary="Bolletta gas naturale."
        )
        session.add_all([doc1, doc2])

        # L'assistente ha appena risposto citando le due bollette
        asst_msg = ChatMessage(
            sender="assistant",
            content="Ho trovato due bollette nel caveau:\n- 📄 Bolletta Enel Luce\n- 📄 Bolletta Gas Eni",
            thread_id="general"
        )
        session.add(asst_msg)
        session.commit()

        agent = AgenticChatService()
        agent.settings.OPENROUTER_API_KEY = "" # deterministic fallback

        # 1. Test "scaricali"
        res_scaricali = agent.run_turn("scaricali", session, thread_id="general")
        assert res_scaricali.documents is not None
        assert len(res_scaricali.documents) == 2
        titles_sc = [d["title"] for d in res_scaricali.documents]
        assert "Bolletta Enel Luce" in titles_sc
        assert "Bolletta Gas Eni" in titles_sc
        assert "singolarmente" not in res_scaricali.reply.lower()

        # 2. Test "scarica entrambi"
        res_entrambi = agent.run_turn("scarica entrambi", session, thread_id="general")
        assert res_entrambi.documents is not None
        assert len(res_entrambi.documents) == 2
        assert "singolarmente" not in res_entrambi.reply.lower()

        # 3. Test "mostrali tutti"
        res_mostrali = agent.run_turn("mostrali tutti", session, thread_id="general")
        assert res_mostrali.documents is not None
        assert len(res_mostrali.documents) == 2


def test_llm_guardrail_replaces_hesitation_with_multi_cards():
    """Verifica che se il modello LLM restituisce una domanda esitante tipo 'Desideri che ti mostri uno in particolare?',
    il guardrail sanifichi il messaggio ed emetta subito tutte le schede trovate."""
    from unittest.mock import patch, MagicMock

    engine = get_engine("sqlite:///:memory:")
    init_db(engine)
    with Session(engine) as session:
        doc1 = Document(
            title="Tessera Sanitaria Italiana",
            file_path="uploads/tessera.pdf",
            file_type="pdf",
            doc_type="sanitario",
            summary="Dati anagrafici e codice fiscale."
        )
        doc2 = Document(
            title="Ricevuta Pre-Immatricolazione Università di Pavia",
            file_path="uploads/pavia.pdf",
            file_type="pdf",
            doc_type="ricevuta",
            summary="Ricevuta iscrizione università con dati anagrafici."
        )
        session.add_all([doc1, doc2])
        session.commit()

        agent = AgenticChatService()
        agent.settings.OPENROUTER_API_KEY = "test-sk-key"

        # Simula il primo step LLM che chiama search_vault
        mock_r1 = MagicMock()
        mock_r1.status_code = 200
        mock_r1.json.return_value = {
            "choices": [{
                "message": {
                    "role": "assistant",
                    "tool_calls": [{
                        "id": "call_search_1",
                        "type": "function",
                        "function": {
                            "name": "search_vault",
                            "arguments": '{"query": "documenti di identità"}'
                        }
                    }]
                }
            }]
        }

        # Simula il secondo step LLM che risponde con una domanda esitante superflua
        mock_r2 = MagicMock()
        mock_r2.status_code = 200
        mock_r2.json.return_value = {
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": (
                        "Ho trovato i seguenti documenti inerenti all'identificazione personale:\n"
                        "* 📄 Tessera Sanitaria Italiana : Contiene i tuoi dati anagrafici.\n"
                        "* 📄 Ricevuta Pre-Immatricolazione Università di Pavia : Riporta i tuoi dati anagrafici.\n\n"
                        "Desideri che ti mostri la scheda di uno di questi documenti in particolare?"
                    )
                }
            }]
        }

        with patch("httpx.post", side_effect=[mock_r1, mock_r2]):
            res = agent.run_turn("dammi i documenti di identità", session, thread_id="general")

            # Il guardrail deve intercettare la domanda superflua, sostituirla ed emettere entrambe le schede
            assert res.documents is not None, "Le schede documento devono essere allegate!"
            assert len(res.documents) == 2, f"Dovevano essere allegate 2 schede, trovate {len(res.documents)}"
            assert "uno di questi documenti in particolare" not in res.reply
            assert "desideri che ti mostri" not in res.reply.lower()
            assert "schede" in res.reply.lower()
            assert res.action == "show_document_card"









