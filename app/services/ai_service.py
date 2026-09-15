import io
import re
import json
import base64
import logging
import httpx
import pypdf
from pathlib import Path
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
    # Rimuove blocchi di thinking/reasoning (<thought>...</thought> o <think>...</think>)
    cleaned_input = re.sub(r"<thought>.*?</thought>", "", raw_text, flags=re.DOTALL | re.IGNORECASE)
    cleaned_input = re.sub(r"<think>.*?</think>", "", cleaned_input, flags=re.DOTALL | re.IGNORECASE)
    cleaned_input = re.sub(r"</?(?:thought|think)[^>]*>", "", cleaned_input, flags=re.IGNORECASE).strip()

    # 1. Prova prima con il blocco di codice markdown ```json ... ```
    json_block = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned_input, re.DOTALL)
    if json_block:
        try:
            return json.loads(json_block.group(1))
        except Exception:
            pass

    # 2. Cerca blocchi graffe bilanciati
    for m in re.finditer(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", cleaned_input, re.DOTALL):
        try:
            parsed = json.loads(m.group(0))
            if isinstance(parsed, dict) and ("doc_type" in parsed or "intent" in parsed or "issuer" in parsed or "title" in parsed):
                return parsed
        except Exception:
            continue

    # 3. Fallback: pulizia testo e ricerca greedy
    cleaned = re.sub(r"```(?:json)?", "", cleaned_input).replace("```", "").strip()
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
        if "tolc" in fn or "certificate" in fn or "certificat" in fn:
            return ExtractedDocument(
                title="Certificato Test TOLC-E CISIA",
                doc_type="certificato",
                issuer="CISIA / Università degli Studi di Milano",
                amount=None,
                due_date=None,
                summary="Certificato ufficiale esiti del test TOLC-E svolto da Riccardo Maggi. Punteggio totale: 22.5.",
                tags=["tolc", "università", "esame", "cisia"],
                suggest_rename=False
            )
        if "f24" in fn or "tribut" in fn:
            return ExtractedDocument(
                title="Modello F24 Versamento IVA",
                doc_type="f24",
                issuer="Agenzia delle Entrate",
                amount=2450.00,
                due_date="2026-09-16",
                summary="Modello F24 versamento IVA trimestrale.",
                tags=["f24", "fisco", "iva"],
                suggest_rename=False
            )
        if "bollett" in fn or "enel" in fn or "luce" in fn or "gas" in fn:
            return ExtractedDocument(
                title="Bolletta Enel Energia",
                doc_type="bolletta",
                issuer="Enel Energia",
                amount=64.20,
                due_date="2026-10-28",
                summary="Bolletta Enel Luce bimestre agosto-settembre.",
                tags=["luce", "energia", "utenze"],
                suggest_rename=False
            )
        # Supporto Word (.docx, .doc)
        if any(fn.endswith(ext) for ext in [".docx", ".doc"]):
            return ExtractedDocument(
                title=f"Documento Word {Path(filename).stem.replace('_', ' ').capitalize()}",
                doc_type="contratto" if "contratt" in fn else "documento_word",
                issuer="Studio Legale / Società",
                amount=3500.0 if "contratt" in fn else None,
                due_date="2026-12-31" if "contratt" in fn else None,
                summary=f"Documento di testo Word '{filename}' elaborato con successo.",
                tags=["word", "documento", "docx"],
                suggest_rename=False
            )
        # Supporto Excel / CSV (.xlsx, .xls, .csv)
        if any(fn.endswith(ext) for ext in [".xlsx", ".xls", ".csv"]):
            return ExtractedDocument(
                title=f"Foglio Calcolo {Path(filename).stem.replace('_', ' ').capitalize()}",
                doc_type="foglio_calcolo",
                issuer="Contabilità / Amministrazione",
                amount=570.50 if "spese" in fn else None,
                due_date="2026-12-01" if "spese" in fn else None,
                summary=f"Foglio di calcolo Excel/CSV '{filename}' con tabelle di dati e riepilogo spese.",
                tags=["excel", "tabelle", "dati", "spese"],
                suggest_rename=False
            )
        # Supporto Archivi ZIP (.zip)
        if fn.endswith(".zip") or "archivio" in fn:
            return ExtractedDocument(
                title=f"Archivio Compresso {Path(filename).stem.replace('_', ' ').capitalize()}",
                doc_type="archivio_zip",
                issuer="Dove lo AI messo",
                amount=None,
                due_date=None,
                summary=f"Archivio ZIP compresso '{filename}' salvato nel caveau.",
                tags=["zip", "archivio", "compresso"],
                suggest_rename=False
            )

        # Per foto, screenshot o altri allegati non fiscali
        is_screen = any(k in fn for k in [".png", "screen", "cattura", "screenshot"])
        clean_name = Path(filename).stem.replace("_", " ").replace("-", " ").strip()
        guessed_title = f"Screenshot {clean_name}" if is_screen else f"Foto {clean_name or 'Oggetto'}"
        return ExtractedDocument(
            title=guessed_title,
            doc_type="screenshot" if is_screen else "foto",
            issuer=None,
            amount=None,
            due_date=None,
            summary=f"Immagine/allegato '{filename}' salvato in archivio.",
            tags=["allegato", "screenshot" if is_screen else "foto"],
            suggest_rename=True
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
    """Motore AI multimodale tramite OpenRouter API (modello: google/gemini-2.5-flash-lite con fallback a free)."""
    def __init__(self, api_key: str, model: str = "google/gemini-2.5-flash-lite"):
        self.api_key = api_key.strip()
        self.primary_model = model.strip() or "google/gemini-2.5-flash-lite"
        self.fallback_models = ["nex-agi/nex-n2.5-pro:free", "inclusionai/ling-3.0-flash-vl:free"]
        self.vision_model = self.primary_model
        self.base_url = "https://openrouter.ai/api/v1/chat/completions"

    def _call_openrouter(self, messages: list, max_tokens: int = 8192, model_override: str = None, temperature: float = 0.2) -> str:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": "http://localhost:8000",
            "X-Title": "Dove lo AI messo",
            "Content-Type": "application/json"
        }
        target_model = model_override or self.primary_model
        payload = {
            "model": target_model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature
        }
        
        # Prova fino a 2 tentativi con backoff breve su rate limit
        for attempt in range(2):
            try:
                res = httpx.post(self.base_url, headers=headers, json=payload, timeout=60.0)
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
                elif res.status_code == 429 and attempt == 0:
                    import time; time.sleep(1.5)
                    continue
                else:
                    logger.warning(f"OpenRouter errore modello {target_model}: {res.status_code} - {res.text[:100]}")
            except Exception as e:
                logger.warning(f"OpenRouter eccezione modello {target_model}: {e}")
                
        raise RuntimeError(f"Modello OpenRouter {target_model} non disponibile al momento.")

    def extract_document(self, file_bytes: bytes, mime_type: str, filename: str = "") -> ExtractedDocument:
        try:
            fn = filename.lower()
            mt = (mime_type or "").lower()
            is_pdf = "pdf" in mt or fn.endswith(".pdf") or file_bytes.startswith(b"%PDF")

            # 1. GESTIONE DOCUMENTI PDF (Estrazione del testo reale delle pagine)
            if is_pdf:
                pdf_text = ""
                try:
                    reader = pypdf.PdfReader(io.BytesIO(file_bytes))
                    for p in reader.pages:
                        page_str = p.extract_text()
                        if page_str:
                            pdf_text += page_str + "\n"
                except Exception as p_err:
                    logger.warning(f"Errore lettura pypdf: {p_err}")

                if pdf_text.strip():
                    pdf_prompt = f"""Sei l'assistente 'Dove lo AI messo'. Analizza questo testo estratto dal documento PDF caricato dall'utente:
---
{pdf_text[:3500]}
---

Identifica con la massima precisione:
1. 'title': un titolo chiaro, elegante e sintetico per il documento (es. 'Certificato TOLC-E CISIA', 'Bolletta Enel Energia Luce', 'Modello F24 IVA')
2. 'doc_type': tipo documento (certificato, bolletta, f24, contratto, ricevuta, fattura, generico)
3. 'issuer': nome ente, università, azienda o fornitore (oppure null)
4. Se è una bolletta o tributo da pagare con scadenza, estrai 'amount' e 'due_date'. Se NON è una bolletta da pagare, imposta amount=null e due_date=null!
5. 'summary': spiegazione chiara e completa di 2-3 frasi in italiano che riassume tutti i dettagli (punteggi, codici, esiti, intestatario, date).
6. 'suggest_rename': false (i documenti formali hanno già un titolo chiaro).

Rispondi ESCLUSIVAMENTE in formato JSON valido con questa struttura esatta:
{{
  "title": "titolo chiaro ed elegante",
  "doc_type": "certificato" | "bolletta" | "f24" | "contratto" | "ricevuta" | "fattura" | "generico",
  "issuer": "nome ente o fornitore" o null,
  "amount": null oppure numero decimale,
  "due_date": null oppure "YYYY-MM-DD",
  "summary": "riassunto dettagliato in 2-3 frasi in italiano",
  "tags": ["tag1", "tag2", "tag3"],
  "suggest_rename": false
}}
"""
                    messages = [{"role": "user", "content": pdf_prompt}]
                    resp_text = self._call_openrouter(messages, max_tokens=4096, model_override=self.primary_model, temperature=0.1)
                    parsed = _extract_json_object(resp_text)
                    return ExtractedDocument(**parsed)

            # 2. GESTIONE DOCUMENTI OFFICE & FOGLI DI CALCOLO (.docx, .doc, .xlsx, .xls, .csv, .txt, .json)
            is_office = any(fn.endswith(ext) for ext in [".docx", ".doc", ".xlsx", ".xls", ".csv", ".tsv", ".txt", ".json", ".md"])
            if is_office:
                from app.services.archive_service import extract_text_from_office_file
                office_text = extract_text_from_office_file(file_bytes, filename)
                if office_text:
                    office_prompt = f"""Sei l'assistente 'Dove lo AI messo'. Analizza questo testo e tabelle estratti dal file Word/Excel/CSV caricato ({filename}):
---
{office_text[:3500]}
---

Identifica con la massima precisione:
1. 'title': un titolo chiaro, elegante e sintetico (es. 'Contratto di Consulenza Software', 'Foglio Spese e Scadenze Aziendali', 'Elenco Fornitori')
2. 'doc_type': scegli tra 'contratto', 'foglio_calcolo', 'spese', 'fattura', 'ricevuta', 'documento_word', 'report', 'generico'
3. 'issuer': nome ente, azienda, autore o controparte (oppure null)
4. Se contiene importi da pagare o scadenze specifiche di pagamento, estrai 'amount' e 'due_date' (YYYY-MM-DD), altrimenti null.
5. 'summary': spiegazione chiara e completa di 2-3 frasi in italiano con i punti chiave, intestatari, colonne o dati più importanti.
6. 'suggest_rename': false.

Rispondi ESCLUSIVAMENTE in formato JSON valido con questa struttura esatta:
{{
  "title": "titolo chiaro ed elegante",
  "doc_type": "contratto" | "foglio_calcolo" | "spese" | "fattura" | "ricevuta" | "documento_word" | "report" | "generico",
  "issuer": "nome ente o fornitore" o null,
  "amount": null oppure numero decimale,
  "due_date": null oppure "YYYY-MM-DD",
  "summary": "riassunto dettagliato in 2-3 frasi in italiano",
  "tags": ["tag1", "tag2", "tag3"],
  "suggest_rename": false
}}
"""
                    messages = [{"role": "user", "content": office_prompt}]
                    resp_text = self._call_openrouter(messages, max_tokens=4096, model_override=self.primary_model, temperature=0.1)
                    parsed = _extract_json_object(resp_text)
                    return ExtractedDocument(**parsed)

            # 3. GESTIONE ARCHIVI ZIP (.zip)
            if fn.endswith(".zip") or "archivio" in fn:
                import zipfile
                try:
                    with zipfile.ZipFile(io.BytesIO(file_bytes), "r") as zf:
                        names = [n for n in zf.namelist() if not n.startswith("__MACOSX") and not Path(n).name.startswith(".")]
                        clean_stem = Path(filename).stem.replace("_", " ").capitalize()
                        return ExtractedDocument(
                            title=f"Archivio {clean_stem}",
                            doc_type="archivio_zip",
                            issuer="Dove lo AI messo",
                            amount=None,
                            due_date=None,
                            summary=f"Archivio compresso contenente {len(names)} file: {', '.join(names[:5])}{'...' if len(names) > 5 else ''}.",
                            tags=["zip", "archivio", "compresso"],
                            suggest_rename=False
                        )
                except Exception:
                    pass

            # 4. GESTIONE IMMAGINI (Foto, screenshot, scansioni grafiche)
            b64_img = base64.b64encode(file_bytes).decode("utf-8")
            data_url = f"data:{mt or 'image/jpeg'};base64,{b64_img}"

            prompt = (
                "Sei l'assistente 'Dove lo AI messo'. Analizza con precisione visiva questa immagine caricata dall'utente.\n\n"
                "Istruzioni:\n"
                "1. 'title': genera un titolo sintetico e descrittivo (massimo 4-6 parole) di ciò che vedi nell'immagine. "
                "Ad esempio se vedi un volante o quick release scrivi 'Base Volante con attacco rapido', se vedi delle chiavi scrivi 'Mazzo chiavi con telecomando', se vedi una bolletta scrivi 'Bolletta Enel Energia', se vedi una patente scrivi 'Patente di Guida'. "
                "NON usare MAI 'Generico File Utente' o nomi anonimi!\n"
                "2. 'doc_type': scegli tra 'bolletta', 'f24', 'ricevuta', 'fattura', 'patente', 'documento_identita', 'foto', 'screenshot', 'oggetto_fisico', 'generico'.\n"
                "3. 'issuer': se riconosci un ente, azienda o marchio visibile (es. 'Enel', 'Fanatec', 'Apple', 'Bosch', 'INPS'), indicalo; altrimenti imposta null.\n"
                "4. Se è una bolletta, fattura o tributo con scadenza di pagamento reale, estrai 'amount' e 'due_date' (YYYY-MM-DD). Altrimenti imposta rigorosamente amount=null e due_date=null.\n"
                "5. 'summary': descrizione ricca ed accurata in 1-2 frasi in italiano di ciò che si vede visivamente nell'immagine (colori, forme, dettagli, marchi o testi visibili).\n"
                "6. 'suggest_rename': imposta true se si tratta della foto di un oggetto fisico, componente, dispositivo, screenshot o allegato non formale per cui è opportuno chiedere all'utente se desidera assegnargli un nome specifico o dove lo ripone. Imposta false per bollette ed F24 con mittente certo.\n\n"
                "Rispondi ESCLUSIVAMENTE in formato JSON valido con questa struttura esatta:\n"
                "{\n"
                '  "title": "Titolo descrittivo intelligente",\n'
                '  "doc_type": "bolletta" | "f24" | "ricevuta" | "foto" | "screenshot" | "oggetto_fisico" | "generico",\n'
                '  "issuer": "marchio/ente oppure null",\n'
                '  "amount": null oppure numero decimale,\n'
                '  "due_date": null oppure "YYYY-MM-DD",\n'
                '  "summary": "descrizione accurata in italiano di cosa si vede",\n'
                '  "tags": ["tag1", "tag2"],\n'
                '  "suggest_rename": true\n'
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
            response_text = self._call_openrouter(messages, max_tokens=4096, model_override=self.vision_model, temperature=0.1)
            parsed = _extract_json_object(response_text)
            if not parsed.get("title"):
                clean_name = Path(filename).stem.replace("_", " ").replace("-", " ").strip()
                parsed["title"] = f"Foto {clean_name}" if "foto" in parsed.get("doc_type", "") else (clean_name or "Documento")
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
            response_text = self._call_openrouter(messages, max_tokens=4096, model_override=self.primary_model, temperature=0.1)
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

            reply = self._call_openrouter(messages, max_tokens=4096, model_override=self.primary_model, temperature=0.4)
            reply = re.sub(r"<thought>.*?</thought>", "", reply, flags=re.DOTALL | re.IGNORECASE)
            reply = re.sub(r"<think>.*?</think>", "", reply, flags=re.DOTALL | re.IGNORECASE)
            reply = re.sub(r"</?(?:thought|think)[^>]*>", "", reply, flags=re.IGNORECASE)
            return reply.strip()
        except Exception as e:
            logger.error(f"Errore OpenRouter generate_conversational_reply: {e}. Uso fallback Mock.")
            return MockAIService().generate_conversational_reply(text, chat_history)


def get_ai_service(db=None) -> AIServiceInterface:
    settings = get_settings()
    if settings.OPENROUTER_API_KEY and settings.OPENROUTER_API_KEY.strip():
        model_name = settings.OPENROUTER_MODEL
        try:
            from app.models.database import get_db, get_app_setting
            if db is not None:
                model_name = get_app_setting(db, "ai_model", default=model_name)
            else:
                session_gen = get_db()
                s = next(session_gen)
                model_name = get_app_setting(s, "ai_model", default=model_name)
                s.close()
        except Exception:
            pass
        return OpenRouterAIService(
            api_key=settings.OPENROUTER_API_KEY.strip(),
            model=model_name
        )
    if settings.GEMINI_API_KEY and settings.GEMINI_API_KEY.strip():
        from app.services.ai_service import GeminiAIService
        logger.info("Utilizzo Google Gemini AI Service")
        return GeminiAIService(api_key=settings.GEMINI_API_KEY.strip())
    
    return MockAIService()
