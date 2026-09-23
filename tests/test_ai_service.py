from app.services.ai_service import MockAIService

def test_mock_ai_extract_document():
    ai = MockAIService()
    result = ai.extract_document(b"fake pdf content", "application/pdf", filename="bolletta_enel.pdf")
    assert result.doc_type == "bolletta"
    assert result.amount == 64.20
    assert result.due_date == "2026-10-28"

def test_mock_ai_route_intent_store():
    ai = MockAIService()
    intent = ai.classify_and_extract_intent("Ho messo il passaporto nella scrivania in camera")
    assert intent.intent == "STORE_LOCATION"
    assert "passaporto" in (intent.item_name or "").lower()

def test_mock_ai_route_intent_query():
    ai = MockAIService()
    intent = ai.classify_and_extract_intent("Dov'è il passaporto?")
    assert intent.intent == "QUERY_LOCATION"

def test_mock_ai_extract_identity_card_with_deadline():
    ai = MockAIService()
    result = ai.extract_document(b"fake id content", "image/jpeg", filename="carta_identita_mario.jpg")
    assert result.doc_type == "documento_identita"
    assert result.amount is None
    assert result.due_date == "2034-05-18"
    assert result.is_payable is True
    assert result.category == "documenti_identita"

