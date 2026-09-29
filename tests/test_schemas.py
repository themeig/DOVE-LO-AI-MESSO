from app.models.schemas import ExtractedDocument, MessageIntent, ChatResponse

def test_extracted_document_schema():
    data = {
        "doc_type": "bolletta",
        "issuer": "Enel Energia",
        "amount": 64.20,
        "due_date": "2026-10-28",
        "summary": "Bolletta luce di ottobre",
        "tags": ["luce", "enel"]
    }
    doc = ExtractedDocument(**data)
    assert doc.amount == 64.20
    assert doc.issuer == "Enel Energia"

def test_message_intent_schema():
    intent = MessageIntent(
        intent="STORE_LOCATION",
        item_name="passaporto",
        primary_location="studio",
        detailed_location="scrivania"
    )
    assert intent.intent == "STORE_LOCATION"

def test_extracted_document_normalize_amount():
    doc1 = ExtractedDocument(amount="€ 88,45")
    assert doc1.amount == 88.45
    doc2 = ExtractedDocument(amount="1.250,50 EUR")
    assert doc2.amount == 1250.50
    doc3 = ExtractedDocument(amount="45,00")
    assert doc3.amount == 45.00

