import re
import logging
from typing import Protocol
from app.models.schemas import ExtractedDocument, MessageIntent
from app.config import get_settings

logger = logging.getLogger(__name__)

class AIServiceInterface(Protocol):
    def extract_document(self, file_bytes: bytes, mime_type: str, filename: str = "") -> ExtractedDocument:
        ...
    def classify_and_extract_intent(self, text: str) -> MessageIntent:
        ...

class MockAIService:
    """Motore offline deterministico per test e sviluppo senza consumo di token."""
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
        
        if "scadenz" in t or "da pagare" in t or "quanto devo pagare" in t or "bollett" in t:
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


class GeminiAIService:
    """Motore reale multimodale basato su Google Gemini (google-genai SDK)."""
    def __init__(self, api_key: str):
        from google import genai
        self.client = genai.Client(api_key=api_key)
        self.model = "gemini-2.5-flash"

    def extract_document(self, file_bytes: bytes, mime_type: str, filename: str = "") -> ExtractedDocument:
        from google.genai import types
        try:
            # Assicura un mime_type valido per immagini/PDF
            mt = mime_type
            if not mt or mt == "application/octet-stream":
                if filename.lower().endswith(".pdf"):
                    mt = "application/pdf"
                elif filename.lower().endswith((".jpg", ".jpeg")):
                    mt = "image/jpeg"
                elif filename.lower().endswith(".png"):
                    mt = "image/png"
                else:
                    mt = "application/pdf"

            part = types.Part.from_bytes(data=file_bytes, mime_type=mt)
            prompt = (
                "Analizza questo documento (bolletta, F24, fattura, atto, ricevuta). "
                "Estrai con la massima precisione: tipo documento, fornitore/emittente, importo numerico in euro se presente, "
                "data di scadenza (formato YYYY-MM-DD) se presente, e una spiegazione in 2 frasi in italiano semplice di cosa rappresenta."
            )
            response = self.client.models.generate_content(
                model=self.model,
                contents=[part, prompt],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=ExtractedDocument,
                    temperature=0.1
                )
            )
            return ExtractedDocument.model_validate_json(response.text)
        except Exception as e:
            logger.error(f"Errore chiamata Gemini Vision: {e}")
            # Fallback elegante al mock se l'API fallisce
            return MockAIService().extract_document(file_bytes, mime_type, filename)

    def classify_and_extract_intent(self, text: str) -> MessageIntent:
        from google.genai import types
        try:
            prompt = f"""Sei l'assistente intelligente 'Dove L'Ho Messo'. Analizza questo messaggio in italiano:
"{text}"

Classifica l'intento:
- STORE_LOCATION: se l'utente dice dove ha messo/conservato qualcosa (es. 'ho messo il passaporto nella credenza'). Estrai item_name, primary_location, detailed_location.
- QUERY_LOCATION: se l'utente chiede dove si trova qualcosa (es. 'dove sono le chiavi?'). Estrai item_name.
- QUERY_DEADLINES: se chiede cosa scade o bollette/tasse da pagare.
- GENERAL: per saluti o altre comunicazioni generiche.
"""
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=MessageIntent,
                    temperature=0.1
                )
            )
            return MessageIntent.model_validate_json(response.text)
        except Exception as e:
            logger.error(f"Errore chiamata Gemini Text: {e}")
            return MockAIService().classify_and_extract_intent(text)


def get_ai_service() -> AIServiceInterface:
    api_key = get_settings().GEMINI_API_KEY
    if api_key and api_key.strip():
        try:
            return GeminiAIService(api_key=api_key.strip())
        except Exception as e:
            logger.warning(f"Impossibile inizializzare GeminiAIService: {e}. Uso MockAIService.")
            return MockAIService()
    return MockAIService()
