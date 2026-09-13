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
