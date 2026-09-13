import re
import json
import base64
import logging
import httpx
from typing import Protocol, Optional
from app.models.schemas import ExtractedDocument, MessageIntent
from app.config import get_settings

logger = logging.getLogger(__name__)

class AIServiceInterface(Protocol):
    def extract_document(self, file_bytes: bytes, mime_type: str, filename: str = "") -> ExtractedDocument:
        ...
    def classify_and_extract_intent(self, text: str) -> MessageIntent:
        ...

def _extract_json_object(raw_text: str) -> dict:
    """Estrae in modo robusto il dizionario JSON dal testo della risposta del modello."""
    cleaned = re.sub(r"```(?:json)?", "", raw_text).replace("```", "").strip()
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except Exception:
            pass
    return json.loads(cleaned)

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


class OpenRouterAIService:
    """Motore AI multimodale tramite OpenRouter API (modelli gratuiti inclusi)."""
    def __init__(self, api_key: str, model: str = "google/gemma-4-31b-it:free"):
        self.api_key = api_key.strip()
        self.primary_model = model.strip() or "google/gemma-4-31b-it:free"
        self.fallback_models = [
            "google/gemma-4-26b-a4b-it:free",
            "nex-agi/nex-n2.5-mini:free"
        ]
        self.base_url = "https://openrouter.ai/api/v1/chat/completions"

    def _call_openrouter(self, messages: list, max_tokens: int = 400) -> str:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": "http://localhost:8000",
            "X-Title": "Dove L Ho Messo",
            "Content-Type": "application/json"
        }
        models_to_try = [self.primary_model] + [m for m in self.fallback_models if m != self.primary_model]
        
        for m in models_to_try:
            payload = {
                "model": m,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": 0.1
            }
            try:
                res = httpx.post(self.base_url, headers=headers, json=payload, timeout=15.0)
                if res.status_code == 200:
                    data = res.json()
                    choices = data.get("choices", [])
                    if choices:
                        return choices[0]["message"]["content"]
                else:
                    logger.warning(f"OpenRouter errore modello {m}: {res.status_code} - {res.text[:100]}")
            except Exception as e:
                logger.warning(f"OpenRouter eccezione modello {m}: {e}")
                
        raise RuntimeError("Tutti i modelli OpenRouter sono al momento non disponibili.")

    def extract_document(self, file_bytes: bytes, mime_type: str, filename: str = "") -> ExtractedDocument:
        try:
            mt = mime_type or "image/jpeg"
            b64_img = base64.b64encode(file_bytes).decode("utf-8")
            data_url = f"data:{mt};base64,{b64_img}"

            prompt = (
                "Sei un assistente per la gestione documentale italiana. Analizza questa immagine/documento (bolletta, F24, fattura, ricevuta). "
                "Estrai con la massima precisione queste informazioni e rispondi ESCLUSIVAMENTE in formato JSON con questi campi: "
                '{"doc_type": "string", "issuer": "string", "amount": float_o_null, "due_date": "YYYY-MM-DD_o_null", "summary": "spiegazione in 2 frasi in italiano semplice", "tags": ["tag1", "tag2"]}'
            )

            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": data_url}}
                    ]
                }
            ]
            response_text = self._call_openrouter(messages, max_tokens=350)
            parsed = _extract_json_object(response_text)
            return ExtractedDocument(**parsed)
        except Exception as e:
            logger.error(f"Errore OpenRouter extract_document: {e}. Uso fallback Mock.")
            return MockAIService().extract_document(file_bytes, mime_type, filename)

    def classify_and_extract_intent(self, text: str) -> MessageIntent:
        try:
            prompt = f"""Sei l'assistente 'Dove L'Ho Messo'. Analizza questo messaggio in italiano dell'utente:
"{text}"

Identifica l'intenzione ed estrai le informazioni necessarie. Rispondi ESCLUSIVAMENTE in formato JSON valido con questa struttura esatta:
{{
  "intent": "STORE_LOCATION" | "QUERY_LOCATION" | "QUERY_DEADLINES" | "GENERAL",
  "item_name": "nome dell'oggetto o null",
  "primary_location": "luogo principale (es. stanza o mobile) o null",
  "detailed_location": "dettaglio specifico (es. cassetto, ripiano) o null"
}}

Regole:
- Se l'utente dice dove ha messo/lasciato/conservato qualcosa -> intent: "STORE_LOCATION"
- Se chiede dove si trova un oggetto -> intent: "QUERY_LOCATION"
- Se chiede cosa scade o bollette/pagamenti -> intent: "QUERY_DEADLINES"
- Altrimenti -> intent: "GENERAL"
"""
            messages = [{"role": "user", "content": prompt}]
            response_text = self._call_openrouter(messages, max_tokens=200)
            parsed = _extract_json_object(response_text)
            return MessageIntent(**parsed)
        except Exception as e:
            logger.error(f"Errore OpenRouter classify_intent: {e}. Uso fallback Mock.")
            return MockAIService().classify_and_extract_intent(text)


def get_ai_service() -> AIServiceInterface:
    settings = get_settings()
    if settings.OPENROUTER_API_KEY and settings.OPENROUTER_API_KEY.strip():
        logger.info("Utilizzo OpenRouter AI Service")
        return OpenRouterAIService(
            api_key=settings.OPENROUTER_API_KEY.strip(),
            model=settings.OPENROUTER_MODEL
        )
    if settings.GEMINI_API_KEY and settings.GEMINI_API_KEY.strip():
        from app.services.ai_service import GeminiAIService
        logger.info("Utilizzo Google Gemini AI Service")
        return GeminiAIService(api_key=settings.GEMINI_API_KEY.strip())
    
    return MockAIService()
