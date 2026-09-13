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
    def generate_conversational_reply(self, text: str, chat_history: list = None) -> str:
        ...

def _extract_json_object(raw_text: str) -> dict:
    """Estrae in modo robusto il dizionario JSON dal testo o dal reasoning del modello."""
    # 1. Prova prima con il blocco di codice markdown ```json ... ```
    json_block = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw_text, re.DOTALL)
    if json_block:
        try:
            return json.loads(json_block.group(1))
        except Exception:
            pass

    # 2. Cerca blocchi graffe bilanciati
    for m in re.finditer(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", raw_text, re.DOTALL):
        try:
            parsed = json.loads(m.group(0))
            if isinstance(parsed, dict) and ("doc_type" in parsed or "intent" in parsed or "issuer" in parsed):
                return parsed
        except Exception:
            continue

    # 3. Fallback: pulizia testo e ricerca greedy
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
        if "bollett" in fn or "enel" in fn or "luce" in fn or "gas" in fn:
            return ExtractedDocument(
                doc_type="bolletta",
                issuer="Enel Energia",
                amount=64.20,
                due_date="2026-10-28",
                summary="Bolletta Enel Luce bimestre agosto-settembre.",
                tags=["luce", "energia", "utenze"]
            )
        # Per foto, screenshot o altri allegati non fiscali
        is_screen = any(k in fn for k in [".png", "screen", "cattura", "screenshot"])
        return ExtractedDocument(
            doc_type="screenshot" if is_screen else "generico",
            issuer="File Utente",
            amount=None,
            due_date=None,
            summary=f"Immagine/allegato '{filename}' salvato in archivio.",
            tags=["allegato", "foto" if not is_screen else "screenshot"]
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

    def generate_conversational_reply(self, text: str, chat_history: list = None) -> str:
        t = text.lower()
        if "chi sei" in t or "cosa fai" in t or "cosa puoi fare" in t or "ai" in t:
            return "Ciao! Sono l'assistente AI di 'Dove lo AI messo'. Posso memorizzare dove riponi oggetti e documenti importanti, leggere foto e PDF di bollette ed F24 con le relative scadenze, e gestire lo scadenzario dei pagamenti."
        if "document" in t or "mandare" in t or "inviare" in t or "carica" in t or "foto" in t:
            return "Certamente! Puoi inviarmi documenti e bollette (foto o PDF) cliccando sull'icona della graffetta 📎 o della fotocamera 📷 qui in basso. Estrarrò automaticamente fornitore, importo e data di scadenza!"
        if "ciao" in t or "buongiorno" in t or "buonasera" in t or "salve" in t:
            return "Ciao! Come posso aiutarti oggi? Puoi dirmi dove hai messo un oggetto, chiedermi dove si trova qualcosa o caricare una bolletta."
        return "Sono qui per aiutarti! Puoi chiedermi dove hai riposto un oggetto, caricare documenti o bollette, o verificare le tue scadenze."


class OpenRouterAIService:
    """Motore AI multimodale tramite OpenRouter API (modelli gratuiti inclusi)."""
    def __init__(self, api_key: str, model: str = "liquid/lfm-2.5-2.6b:free"):
        self.api_key = api_key.strip()
        self.primary_model = model.strip() or "liquid/lfm-2.5-2.6b:free"
        self.fallback_models = [
            "nex-agi/nex-n2.5-mini:free",
            "nex-agi/nex-n2.5-pro:free"
        ]
        self.vision_model = "dots-studio/dots-3-note-preview:free"
        self.base_url = "https://openrouter.ai/api/v1/chat/completions"

    def _call_openrouter(self, messages: list, max_tokens: int = 400, model_override: str = None, temperature: float = 0.2) -> str:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": "http://localhost:8000",
            "X-Title": "Dove lo AI messo",
            "Content-Type": "application/json"
        }
        first_model = model_override or self.primary_model
        # Se stiamo inviando immagini, non provare modelli text-only nei fallback
        has_images = any(
            isinstance(m.get("content"), list) and any(item.get("type") == "image_url" for item in m.get("content", []))
            for m in messages
        )
        models_to_try = [first_model] if has_images else ([first_model] + [m for m in self.fallback_models if m != first_model])
        
        for m in models_to_try:
            payload = {
                "model": m,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature
            }
            try:
                res = httpx.post(self.base_url, headers=headers, json=payload, timeout=25.0 if has_images else 12.0)
                if res.status_code == 200:
                    data = res.json()
                    choices = data.get("choices", [])
                    if choices:
                        msg = choices[0]["message"]
                        content = msg.get("content")
                        reasoning = msg.get("reasoning")
                        if content and content.strip():
                            return content.strip()
                        if reasoning and reasoning.strip():
                            return reasoning.strip()
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
                "Sei l'assistente 'Dove lo AI messo'. Analizza con precisione questa immagine caricata dall'utente.\n"
                "1. Se è una bolletta, F24, fattura o ricevuta con scadenza/pagamento, estrai ente, importo da pagare e data di scadenza.\n"
                "2. Se NON è un documento fiscale o bolletta da pagare (es. è uno screenshot di un sito o app, una foto di un oggetto, una schermata web, un meme, ecc.), NON inventare dati! Imposta amount=null e due_date=null, e descrivi fedelmente cosa vedi nel campo 'summary'.\n\n"
                "Rispondi ESCLUSIVAMENTE in formato JSON valido con questa struttura:\n"
                "{\n"
                '  "doc_type": "bolletta" | "f24" | "ricevuta" | "fattura" | "screenshot" | "foto" | "generico",\n'
                '  "issuer": "nome ente, sito o applicazione riconosciuta",\n'
                '  "amount": null oppure numero decimale,\n'
                '  "due_date": null oppure "YYYY-MM-DD",\n'
                '  "summary": "descrizione reale in 1-2 frasi in italiano di cosa si vede",\n'
                '  "tags": ["tag1", "tag2"]\n'
                "}"
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
            response_text = self._call_openrouter(messages, max_tokens=1600, model_override=self.vision_model, temperature=0.1)
            parsed = _extract_json_object(response_text)
            return ExtractedDocument(**parsed)
        except Exception as e:
            logger.error(f"Errore OpenRouter extract_document: {e}. Uso fallback Mock.")
            return MockAIService().extract_document(file_bytes, mime_type, filename)

    def classify_and_extract_intent(self, text: str) -> MessageIntent:
        try:
            prompt = f"""Sei l'assistente 'Dove lo AI messo'. Analizza questo messaggio in italiano dell'utente:
"{text}"

Identifica l'intenzione ed estrai le informazioni necessarie. Rispondi ESCLUSIVAMENTE in formato JSON valido con questa struttura esatta:
{{
  "intent": "STORE_LOCATION" | "QUERY_LOCATION" | "QUERY_DEADLINES" | "GENERAL",
  "item_name": "nome dell'oggetto o null",
  "primary_location": "luogo principale (es. stanza o mobile) o null",
  "detailed_location": "dettaglio specifico (es. cassetto, ripiano) o null"
}}

Regole:
- Se l'utente dice dove ha messo/lasciato/conservato/riposto qualcosa -> intent: "STORE_LOCATION"
- Se chiede dove si trova un oggetto o dove l'ha messo -> intent: "QUERY_LOCATION"
- Se chiede cosa scade o bollette/pagamenti -> intent: "QUERY_DEADLINES"
- Se saluta, fa domande generali sull'app, su chi sei o se può mandare documenti -> intent: "GENERAL"
"""
            messages = [{"role": "user", "content": prompt}]
            # nex-agi is very reliable for structured JSON
            response_text = self._call_openrouter(messages, max_tokens=200, model_override="nex-agi/nex-n2.5-mini:free", temperature=0.1)
            parsed = _extract_json_object(response_text)
            return MessageIntent(**parsed)
        except Exception as e:
            logger.error(f"Errore OpenRouter classify_intent: {e}. Uso fallback Mock.")
            return MockAIService().classify_and_extract_intent(text)

    def generate_conversational_reply(self, text: str, chat_history: list = None) -> str:
        try:
            system_prompt = (
                "Sei l'assistente virtuale intelligente e cordiale di 'Dove lo AI messo' per WhatsApp. "
                "Aiuti famiglie e professionisti a ricordare dove hanno riposto oggetti importanti, "
                "a catalogare bollette e documenti (che l'utente può inviare cliccando sull'icona graffetta 📎 o fotocamera 📷), "
                "e a tenere d'occhio le scadenze nella Dashboard moderna in alto a destra.\n"
                "Rispondi in modo naturale, caldo, amichevole e conciso in italiano come in una chat WhatsApp vera. "
                "Non ripetere mai frasi fisse da bot."
            )
            messages = [{"role": "system", "content": system_prompt}]
            if chat_history:
                for m in chat_history[-4:]:
                    messages.append({"role": m.get("role", "user"), "content": m.get("content", "")})
            messages.append({"role": "user", "content": text})

            # liquid/lfm-2.5-2.6b:free is great and conversational
            return self._call_openrouter(messages, max_tokens=200, model_override="liquid/lfm-2.5-2.6b:free", temperature=0.4)
        except Exception as e:
            logger.error(f"Errore OpenRouter generate_conversational_reply: {e}. Uso fallback Mock.")
            return MockAIService().generate_conversational_reply(text, chat_history)


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
