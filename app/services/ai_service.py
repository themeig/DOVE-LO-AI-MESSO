import re
from typing import Protocol
from app.models.schemas import ExtractedDocument, MessageIntent
from app.config import get_settings

class AIServiceInterface(Protocol):
    def extract_document(self, file_bytes: bytes, mime_type: str, filename: str = "") -> ExtractedDocument:
        ...
    def classify_and_extract_intent(self, text: str) -> MessageIntent:
        ...

class MockAIService:
    """Deterministic offline AI Service for tests and development without API keys."""
    def extract_document(self, file_bytes: bytes, mime_type: str, filename: str = "") -> ExtractedDocument:
        fn = filename.lower()
        if "f24" in fn or "tribut" in fn:
            return ExtractedDocument(
                doc_type="f24",
                issuer="Agenzia delle Entrate",
                amount=2450.00,
                due_date="2026-09-16",
                summary="Modello F24 versamento IVA trimestrale.",
                tags=["f24", "fisco", "iva"]
            )
        # Default: Bolletta
        return ExtractedDocument(
            doc_type="bolletta",
            issuer="Enel Energia",
            amount=64.20,
            due_date="2026-10-28",
            summary="Bolletta Enel Luce bimestre agosto-settembre.",
            tags=["luce", "energia", "utenze"]
        )

    def classify_and_extract_intent(self, text: str) -> MessageIntent:
        t = text.lower()
        if "dov'è" in t or "dove si trova" in t or "dove ho messo" in t or "dove sono" in t:
            item = re.sub(r".*?(dov'è|dove si trova|dove ho messo|dove sono)\s+", "", t).strip(" ?.")
            return MessageIntent(intent="QUERY_LOCATION", item_name=item, query_text=text)
        
        if "scadenz" in t or "da pagare" in t or "quanto devo pagare" in t:
            return MessageIntent(intent="QUERY_DEADLINES", query_text=text)

        if "messo" in t or "riposto" in t or "lasciato" in t or "salvato" in t:
            item = "oggetto"
            loc = "posto specificato"
            m = re.search(r"(?:messo|riposto|salvato)\s+(?:il\s+|la\s+|le\s+|i\s+|l\')?(.+?)\s+(?:nel|nella|in|su|sul|sotto)\s+(.+)", t)
            if m:
                item = m.group(1).strip()
                loc = m.group(2).strip()
            return MessageIntent(
                intent="STORE_LOCATION",
                item_name=item,
                primary_location=loc,
                detailed_location=None
            )

        return MessageIntent(intent="GENERAL", query_text=text)

def get_ai_service() -> AIServiceInterface:
    return MockAIService()
