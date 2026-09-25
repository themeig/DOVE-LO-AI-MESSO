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
def optimize_image_for_vision(image_bytes: bytes, max_bytes: int = 3 * 1024 * 1024, max_dim: int = 1600) -> tuple[bytes, str]:
    """Ridimensiona e comprime l'immagine per evitare errori 413 (>30MB payload) e velocizzare le chiamate Vision."""
    if len(image_bytes) <= max_bytes:
        return image_bytes, "image/jpeg"
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(image_bytes))
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=82, optimize=True)
        return buf.getvalue(), "image/jpeg"
    except Exception as e:
        logger.warning(f"Ottimizzazione immagine per Vision non riuscita: {e}")
        return image_bytes, "image/jpeg"


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
        doc = self._raw_extract_document(file_bytes, mime_type, filename)
        from app.services.category_service import resolve_or_create_category_and_subfolder
        slug, label, icon, subfolder = resolve_or_create_category_and_subfolder(
            proposed_label=doc.category_label,
            document_text=doc.summary,
            doc_type=doc.doc_type,
            due_date=doc.due_date,
            proposed_slug=doc.category,
            proposed_icon=doc.category_icon,
            proposed_subfolder=doc.subfolder,
            filename=filename
        )
        doc.category = slug
        doc.category_label = label
        doc.category_icon = icon
        doc.subfolder = subfolder
        return doc

    def _raw_extract_document(self, file_bytes: bytes, mime_type: str, filename: str = "") -> ExtractedDocument:
        fn = filename.lower()
        clean_name = Path(filename).stem.replace("_", " ").replace("-", " ").strip().title()
        from app.services.document_service import QUIETANZA_REGEX
        is_already_paid = bool(QUIETANZA_REGEX.search(fn)) or any(k in fn for k in ["pagat", "saldat", "quietanz"])

        if "tolc" in fn or "certificate" in fn or "certificat" in fn:
            return ExtractedDocument(
                title="Certificato Test TOLC-E CISIA",
                doc_type="certificato",
                issuer="CISIA / Università degli Studi di Milano",
                amount=None,
                due_date=None,
                is_payable=False,
                is_paid=None,
                payment_status="non_richiesto",
                summary="Certificato ufficiale esiti del test TOLC-E svolto da Riccardo Maggi. Punteggio totale: 22.5.",
                tags=["tolc", "università", "esame", "cisia"],
                suggest_rename=False,
                category="formazione_certificati",
                category_label="Formazione & Certificati",
                category_icon="fa-graduation-cap"
            )
        if "f24" in fn or "tribut" in fn:
            return ExtractedDocument(
                title="Modello F24 Versamento IVA" if not is_already_paid else "Modello F24 Quietanzato",
                doc_type="f24",
                issuer="Agenzia delle Entrate",
                amount=2450.00,
                due_date="2026-09-16",
                is_payable=not is_already_paid,
                is_paid=is_already_paid,
                payment_status="quietanzato" if is_already_paid else "da_pagare",
                summary="Modello F24 versamento IVA con attestazione di avvenuto pagamento (PAGATO)." if is_already_paid else "Modello F24 versamento IVA trimestrale.",
                tags=["f24", "fisco", "iva", "pagato"] if is_already_paid else ["f24", "fisco", "iva"],
                suggest_rename=False,
                category="fisco_tributi",
                category_label="Fisco, Tributi & F24",
                category_icon="fa-landmark"
            )
        if any(k in fn for k in ["identit", "patente", "passaporto", "cie"]):
            return ExtractedDocument(
                title=f"Carta d'Identità {clean_name}" if "identit" in fn or "cie" in fn else f"Documento {clean_name}",
                doc_type="documento_identita",
                issuer="Ministero dell'Interno",
                amount=None,
                due_date="2034-05-18",
                is_payable=True,
                is_paid=None,
                payment_status="non_richiesto",
                summary="Documento di riconoscimento in corso di validità con data di scadenza.",
                tags=["identità", "documento", "personale", "scadenza"],
                suggest_rename=False,
                category="documenti_identita",
                category_label="Documenti Personali & Identità",
                category_icon="fa-id-card"
            )
        if any(k in fn for k in ["canzon", "music", "poesi", "brano", "strof", "liric"]):
            return ExtractedDocument(
                title=f"Testo di {clean_name or 'Canzone'}",
                doc_type="testo_personale",
                issuer=None,
                amount=None,
                due_date=None,
                is_payable=False,
                is_paid=None,
                payment_status="non_richiesto",
                summary=f"Testo o brano musicale '{filename}' archiviato nel caveau.",
                tags=["musica", "testo", "canzone", "personale"],
                suggest_rename=False,
                category="canzoni_musica",
                category_label="Canzoni & Testi Musicali",
                category_icon="fa-music"
            )
        if any(k in fn for k in ["bollett", "enel", "utenza", "facture"]) or (("luce" in fn or "gas" in fn or "acqua" in fn) and any(w in fn for w in ["bollett", "fattur", "enel", "servizio", "utenz", "bimestre"])):
            return ExtractedDocument(
                title="Bolletta Enel Energia (Saldata)" if is_already_paid else "Bolletta Enel Energia",
                doc_type="bolletta",
                issuer="Enel Energia",
                amount=64.20,
                due_date="2026-10-28",
                is_payable=not is_already_paid,
                is_paid=is_already_paid,
                payment_status="quietanzato" if is_already_paid else "da_pagare",
                summary="Bolletta Enel Luce saldata con timbro PAGATO." if is_already_paid else "Bolletta Enel Luce bimestre agosto-settembre.",
                tags=["luce", "energia", "utenze", "pagato"] if is_already_paid else ["luce", "energia", "utenze"],
                suggest_rename=False,
                category="utenze_bollette",
                category_label="Utenze & Bollette",
                category_icon="fa-bolt"
            )
        if any(k in fn for k in ["fattur", "parcell", "spesa"]) or is_already_paid:
            return ExtractedDocument(
                title=f"Fattura {clean_name}" + (" (Pagata)" if is_already_paid else ""),
                doc_type="fattura" if not is_already_paid else "ricevuta",
                issuer="Studio Professionale",
                amount=120.00,
                due_date="2026-10-15",
                is_payable=not is_already_paid,
                is_paid=is_already_paid,
                payment_status="quietanzato" if is_already_paid else "da_pagare",
                summary=f"Fattura/ricevuta {'con avvenuto pagamento registrato (PAGATO).' if is_already_paid else 'in scadenza.'}",
                tags=["fattura", "spese"] + (["pagato"] if is_already_paid else []),
                suggest_rename=False,
                category="ricevute_spese",
                category_label="Fatture, Spese & Ricevute",
                category_icon="fa-receipt"
            )
        # Supporto Word (.docx, .doc)
        if any(fn.endswith(ext) for ext in [".docx", ".doc"]):
            from app.services.archive_service import extract_text_from_office_file
            docx_text = extract_text_from_office_file(file_bytes, filename)
            detected_amount = None
            detected_date = None
            if docx_text:
                amt_m = re.findall(r"(?:€|eur|euro)?\s*(\d+[.,]\d{2})\b", docx_text, flags=re.IGNORECASE)
                if amt_m:
                    try:
                        detected_amount = float(amt_m[0].replace(".", "").replace(",", "."))
                    except Exception:
                        pass
                date_m = re.findall(r"\b(\d{4}-\d{2}-\d{2})\b", docx_text)
                if date_m:
                    detected_date = date_m[0]
            clean_stem = Path(filename).stem.replace('_', ' ').capitalize()
            is_ct = "contratt" in fn
            return ExtractedDocument(
                title=f"Documento Word {clean_stem}",
                doc_type="contratto" if is_ct else "documento_word",
                issuer="Studio Legale / Società",
                amount=detected_amount or (3500.0 if is_ct else None),
                due_date=detected_date or ("2026-12-31" if is_ct else None),
                summary=(f"Documento Word '{filename}' con testo estratto:\n{docx_text[:250]}" if docx_text else f"Documento di testo Word '{filename}' elaborato con successo."),
                tags=["word", "documento", "docx"],
                suggest_rename=False,
                category="contratti_polizze" if is_ct else "documenti_testo",
                category_label="Contratti, Polizze & Assicurazioni" if is_ct else "Documenti di Testo & Note",
                category_icon="fa-file-signature" if is_ct else "fa-file-lines"
            )
        # Supporto Excel / CSV (.xlsx, .xls, .xlsm, .csv, .tsv)
        if any(fn.endswith(ext) for ext in [".xlsx", ".xls", ".xlsm", ".csv", ".tsv"]):
            from app.services.archive_service import extract_text_from_office_file
            xlsx_text = extract_text_from_office_file(file_bytes, filename)
            detected_amount = None
            detected_date = None
            if xlsx_text:
                amt_m = re.findall(r"(?:€|eur|euro)?\s*(\d+[.,]\d{2})\b", xlsx_text, flags=re.IGNORECASE)
                if amt_m:
                    try:
                        detected_amount = float(amt_m[0].replace(".", "").replace(",", "."))
                    except Exception:
                        pass
                date_m = re.findall(r"\b(\d{4}-\d{2}-\d{2})\b", xlsx_text)
                if date_m:
                    detected_date = date_m[0]
            clean_stem = Path(filename).stem.replace('_', ' ').capitalize()
            is_spese = bool(detected_amount or "spese" in fn)
            return ExtractedDocument(
                title=f"Foglio Calcolo {clean_stem}",
                doc_type="foglio_calcolo" if not detected_amount else "spese",
                issuer="Contabilità / Amministrazione",
                amount=detected_amount or (570.50 if "spese" in fn else None),
                due_date=detected_date or ("2026-12-01" if "spese" in fn else None),
                summary=(f"Foglio di calcolo Excel '{filename}' elaborato con successo. Dati e colonne estratti:\n{xlsx_text[:250]}" if xlsx_text else f"Foglio di calcolo Excel/CSV '{filename}' con tabelle di dati e riepilogo spese."),
                tags=["excel", "tabelle", "dati", "spese"],
                suggest_rename=False,
                category="spese_contabilita" if is_spese else "fogli_calcolo",
                category_label="Fatture, Spese & Ricevute" if is_spese else "Fogli di Calcolo & Dati",
                category_icon="fa-receipt" if is_spese else "fa-table"
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
                suggest_rename=False,
                category="archivi_zip",
                category_label="Archivi Compressi & ZIP",
                category_icon="fa-file-zipper"
            )

        # Supporto Scansioni
        if "scansion" in fn:
            return ExtractedDocument(
                title=f"Documento Scansionato {clean_name}",
                doc_type="generico",
                issuer="Ente / Mittente",
                amount=None,
                due_date=None,
                summary=f"Documento scansionato '{filename}' acquisito ed elaborato nel caveau.",
                tags=["scansione", "documento"],
                suggest_rename=False,
                category="documenti_testo",
                category_label="Documenti Personali & Note",
                category_icon="fa-file-lines"
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
            suggest_rename=True,
            category="screenshot_catture" if is_screen else "foto_immagini",
            category_label="Screenshot & Catture" if is_screen else "Foto & Immagini",
            category_icon="fa-camera-retro" if is_screen else "fa-image"
        )

    def classify_and_extract_intent(self, text: str) -> MessageIntent:
        t = text.lower()
        if any(w in t for w in ["dov'è", "dov'e", "dove si trova", "dove ho messo", "dove sono", "dove sta"]):
            item = re.sub(r".*?(?:dov'è|dov'e|dove si trova|dove ho messo|dove sono|dove sta)\s*(?:il|lo|la|i|gli|le|l')?\s*", "", t).strip(" ?.")
            if item:
                return MessageIntent(intent="QUERY_LOCATION", item_name=item, query_text=text)

        if any(w in t for w in ["scadenz", "da pagare", "quanto devo pagare", "bollette da pagare"]):
            return MessageIntent(intent="QUERY_DEADLINES", query_text=text)

        if any(re.search(rf"\b{w}\b", t) for w in ["messo", "riposto", "lasciato", "salvato", "conservato", "posizionato"]):
            m = re.search(r"\b(?:ho\s+)?(?:messo|riposto|salvato|lasciato|conservato|posizionato)\b\s+(?:il\s+|la\s+|le\s+|i\s+|l\')?(.+?)\s+\b(?:nel|nella|nello|nei|negli|nelle|in|su|sul|sulla|sullo|sui|sugli|sulle|sotto|a)\b\s+(.+)", t)
            if m:
                item = m.group(1).strip(" .?!\"'[]:;,")
                loc = m.group(2).strip(" .?!\"'[]:;,")
                if item and loc and "dove lo ai messo" not in item.lower() and len(item) >= 2:
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
        self.api_key = api_key
        chosen_model = (model or "").strip()
        if not chosen_model or chosen_model == "auto":
            chosen_model = "google/gemini-2.5-flash-lite"
        self.primary_model = chosen_model
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

            def _finalize(doc: ExtractedDocument) -> ExtractedDocument:
                from app.services.category_service import resolve_or_create_category_and_subfolder
                slug, label, icon, subfolder = resolve_or_create_category_and_subfolder(
                    proposed_label=doc.category_label,
                    document_text=doc.summary,
                    doc_type=doc.doc_type,
                    due_date=doc.due_date,
                    proposed_slug=doc.category,
                    proposed_icon=doc.category_icon,
                    proposed_subfolder=doc.subfolder,
                    filename=filename
                )
                doc.category = slug
                doc.category_label = label
                doc.category_icon = icon
                doc.subfolder = subfolder
                return doc

            # 1. GESTIONE DOCUMENTI PDF (Estrazione del testo reale delle pagine o scansioni visive multipagina)
            if is_pdf:
                pdf_text = ""
                scanned_images = []
                try:
                    reader = pypdf.PdfReader(io.BytesIO(file_bytes))
                    for i, p in enumerate(reader.pages[:20]):
                        page_str = p.extract_text()
                        if page_str and page_str.strip():
                            pdf_text += f"\n--- PAGINA {i+1} ---\n" + page_str.strip() + "\n"
                        # Ispeziona immagini incorporate nelle pagine per gestire PDF scansionati
                        if len(scanned_images) < 8:
                            try:
                                page_imgs = []
                                for img in p.images:
                                    if img.data and len(img.data) > 1024:
                                        page_imgs.append((len(img.data), img.data))
                                if page_imgs:
                                    page_imgs.sort(key=lambda x: x[0], reverse=True)
                                    scanned_images.append(page_imgs[0][1])
                            except Exception as p_img_err:
                                logger.warning(f"Errore estrazione immagine pagina PDF {i+1}: {p_img_err}")
                except Exception as p_err:
                    logger.warning(f"Errore lettura pypdf: {p_err}")

                if len(pdf_text.strip()) >= 30:
                    pdf_prompt = f"""Sei l'assistente 'Dove lo AI messo'. Analizza questo testo estratto dal documento PDF caricato dall'utente:
---
{pdf_text[:12000]}
---

Identifica con la massima precisione:
1. 'title': un titolo chiaro, elegante e sintetico per il documento (es. 'Certificato TOLC-E CISIA', 'Bolletta Enel Energia Luce', 'Modello F24 IVA', 'Carta d'Identità Mario Rossi')
2. 'doc_type': tipo documento (certificato, bolletta, f24, contratto, ricevuta, fattura, documento_identita, patente, polizza, testo_personale, generico)
3. 'issuer': nome ente, università, azienda, fornitore o ministero (oppure null)
4. 'due_date': se il documento presenta una data di scadenza, termine di pagamento o fine validità (es. bollette, fatture, F24, ma anche carte d'identità, patenti, passaporti, contratti di affitto, polizze assicurative, abbonamenti, tessere sanitarie), estrai la data nel formato YYYY-MM-DD. ATTENZIONE: estrai ESCLUSIVAMENTE la data di scadenza ('valido fino al', 'scade il', 'data di scadenza', 'termine'); NON confondere la data di rilascio, stipula o emissione con la scadenza! Se non c'è alcuna scadenza o termine, imposta rigorosamente due_date=null.
5. 'amount': se è presente un importo monetario da pagare o saldare, estrailo come numero decimale (es. 64.20). Se il documento NON richiede un pagamento in denaro (es. carta d'identità, patente, certificato o contratto senza importo pendente), imposta rigorosamente amount=null.
6. 'is_paid' & 'payment_status' & 'is_payable':
   VERIFICA ACCURATAMENTE SE IL DOCUMENTO RIPORTA TIMBRO, DICITURA O QUIETANZA DI PAGAMENTO:
   Cerca con estrema attenzione parole come 'PAGATO', 'SALDATO', 'QUIETANZATO', 'PAGATA', 'SALDATA', 'quietanza di pagamento', 'bonifico eseguito', 'ricevuta di versamento', 'addebito su c/c eseguito'.
   - Se il documento riporta timbro o attestazione di avvenuto pagamento:
     imposta "is_paid": true, "payment_status": "quietanzato", "is_payable": false (il debito è estinto, non va aperto un debito da pagare).
   - Se è una bolletta, fattura, F24 o tributo ancora aperto da pagare:
     imposta "is_paid": false, "payment_status": "da_pagare", "is_payable": true.
   - Per documenti personali, carte d'identità, patenti, certificati o contratti senza importo monetario pendente:
     imposta "is_paid": null, "payment_status": "non_richiesto", "is_payable": false.
7. 'summary': spiegazione chiara e completa di 2-3 frasi in italiano che riassume tutti i dettagli (punteggi, codici, esiti, intestatario, date).
8. 'suggest_rename': false (i documenti formali hanno già un titolo chiaro).
9. 'category_label': consulta PRIMA queste cartelle generali di sistema: 'Utenze & Bollette', 'Fisco, Tributi & F24', 'Fatture, Spese & Ricevute', 'Contratti, Polizze & Assicurazioni', 'Documenti Personali & Identità', 'Sanità & Spese Mediche', 'Formazione, Studio & Certificati', 'Automobili & Veicoli', 'Canzoni, Musica & Testi Personali', 'Archivi Compressi & ZIP', 'Foto, Immagini & Ricordi'. Se il file è inerente a una di esse, USA QUELLA CARTELLA per evitare doppioni! Crea una nuova sezione tematica SOLO se il file non ha alcuna pertinenza con quelle sopra.
10. 'category': slug normalizzato in minuscolo con underscore (es. 'canzoni_musica', 'utenze_bollette', 'fisco_tributi', 'documenti_identita').
11. 'category_icon': l'icona FontAwesome 6 più appropriata (es. 'fa-music', 'fa-bolt', 'fa-landmark', 'fa-id-card', 'fa-file-signature', 'fa-receipt', 'fa-heart-pulse', 'fa-graduation-cap', 'fa-utensils', 'fa-car', 'fa-paw', 'fa-plane', 'fa-folder-closed').
12. 'subfolder': estrai l'anno a 4 cifre (es. '2026', '2025', '2024') se presente una data/scadenza, oppure un sotto-tema (es. 'Locazioni', 'Album'); altrimenti imposta null.

Rispondi ESCLUSIVAMENTE in formato JSON valido con questa struttura esatta:
{{
  "title": "titolo chiaro ed elegante",
  "doc_type": "certificato" | "bolletta" | "f24" | "contratto" | "ricevuta" | "fattura" | "documento_identita" | "polizza" | "generico",
  "issuer": "nome ente o fornitore" o null,
  "amount": null oppure numero decimale,
  "due_date": null oppure "YYYY-MM-DD",
  "is_payable": true oppure false,
  "is_paid": true oppure false oppure null,
  "payment_status": "da_pagare" | "quietanzato" | "non_richiesto",
  "summary": "riassunto dettagliato in 2-3 frasi in italiano",
  "tags": ["tag1", "tag2", "tag3"],
  "suggest_rename": false,
  "category": "slug_sezione",
  "category_label": "Titolo Sezione Scelto Dall'AI",
  "category_icon": "fa-icon",
  "subfolder": "2026" oppure null
}}
"""
                    messages = [{"role": "user", "content": pdf_prompt}]
                    resp_text = self._call_openrouter(messages, max_tokens=4096, model_override=self.primary_model, temperature=0.1)
                    parsed = _extract_json_object(resp_text)
                    return _finalize(ExtractedDocument(**parsed))
                elif scanned_images:
                    # PDF SCANSIONATO GRAFICO MULTIPAGINA (es. da Google ML Kit Scanner o fotocopiatrice multifunzione)
                    logger.info(f"Rilevato PDF scansionato con {len(scanned_images)} pagine/immagini ({filename}). Elaborazione con AI multimodale integrale.")
                    multi_prompt = f"""Sei l'assistente 'Dove lo AI messo'. Analizza questo documento PDF scansionato composto da {len(scanned_images)} pagine (allegati visivi in ordine cronologico di pagina).
Nome file originale: '{filename}'.

Esamina attentamente TUTTE le pagine visive fornite per comprendere ed estrarre i dati completi del documento:
1. 'title': un titolo descrittivo, chiaro, elegante e sintetico (es. 'Bolletta Enel Energia', 'Modello F24 Versamento Tributi', 'Contratto di Locazione Commerciale', 'Fattura Professionale', 'Certificato Medico').
2. 'doc_type': tipo documento formale ('bolletta', 'f24', 'contratto', 'fattura', 'ricevuta', 'documento_identita', 'patente', 'polizza', 'certificato', 'generico'). NON classificarlo MAI come 'foto' o 'screenshot' se è un documento o modulo scansionato!
3. 'issuer': nome ente, università, azienda, fornitore o ministero emittente (oppure null se non rilevabile).
4. 'due_date': se è presente una data di scadenza, fine validità, termine pagamento o rinnovo in una qualsiasi delle pagine (es. bollette, fatture, F24, patenti, carte identità, polizze, contratti), estrai la data nel formato YYYY-MM-DD. NON confondere la data di rilascio, stipula o emissione con la scadenza! Se non c'è scadenza o termine, imposta rigorosamente due_date=null.
5. 'amount': se è presente un importo monetario da pagare o saldare (es. totale bolletta, saldo F24, totale fattura, importo scontrino), estrailo come numero decimale (es. 64.20). Se il documento NON richiede un pagamento pendente, imposta rigorosamente amount=null.
6. 'is_paid' & 'payment_status' & 'is_payable':
   VERIFICA ACCURATAMENTE SE IL DOCUMENTO RIPORTA TIMBRO, DICITURA O QUIETANZA DI PAGAMENTO:
   Cerca con estrema attenzione parole o timbri come 'PAGATO', 'SALDATO', 'QUIETANZATO', 'PAGATA', 'SALDATA', 'quietanza di pagamento', 'bonifico eseguito', 'ricevuta di versamento', 'addebito su c/c eseguito'.
   - Se il documento riporta timbro o attestazione di avvenuto pagamento:
     imposta "is_paid": true, "payment_status": "quietanzato", "is_payable": false (il debito è estinto, non va aperto un debito da pagare).
   - Se è una bolletta, fattura, F24 o tributo ancora aperto da pagare:
     imposta "is_paid": false, "payment_status": "da_pagare", "is_payable": true.
   - Per documenti personali, carte d'identità, patenti, certificati o contratti senza importo monetario pendente:
     imposta "is_paid": null, "payment_status": "non_richiesto", "is_payable": false.
7. 'summary': spiegazione dettagliata, ricca e completa di 2-3 frasi in italiano che riassume tutte le pagine, nominativi, intestatari, importi, codici fiscali o dettagli essenziali rilevati nelle varie pagine.
8. 'suggest_rename': false (è un documento formale o scansionato).
9. 'category_label': consulta PRIMA queste cartelle generali di sistema per evitare doppioni: 'Utenze & Bollette', 'Fisco, Tributi & F24', 'Fatture, Spese & Ricevute', 'Contratti, Polizze & Assicurazioni', 'Documenti Personali & Identità', 'Sanità & Spese Mediche', 'Formazione, Studio & Certificati', 'Automobili & Veicoli', 'Canzoni, Musica & Testi Personali', 'Archivi Compressi & ZIP', 'Foto, Immagini & Ricordi'. Se il file è inerente a una di esse, USA QUELLA CARTELLA!
10. 'category': slug normalizzato in minuscolo con underscore (es. 'utenze_bollette', 'fisco_tributi', 'documenti_identita', 'contratti_polizze').
11. 'category_icon': l'icona FontAwesome 6 più appropriata.
12. 'subfolder': estrai l'anno a 4 cifre se presente una scadenza o competenza, oppure un sotto-tema; altrimenti null.

Rispondi ESCLUSIVAMENTE in formato JSON valido:
{{
  "title": "titolo chiaro ed elegante",
  "doc_type": "bolletta" | "f24" | "contratto" | "ricevuta" | "fattura" | "documento_identita" | "polizza" | "generico",
  "issuer": "nome ente o fornitore" o null,
  "amount": null oppure numero decimale,
  "due_date": null oppure "YYYY-MM-DD",
  "is_payable": true oppure false,
  "is_paid": true oppure false oppure null,
  "payment_status": "da_pagare" | "quietanzato" | "non_richiesto",
  "summary": "riassunto completo in 2-3 frasi in italiano con tutti i dati delle pagine",
  "tags": ["tag1", "tag2"],
  "suggest_rename": false,
  "category": "slug_sezione",
  "category_label": "Titolo Sezione",
  "category_icon": "fa-icon",
  "subfolder": "2026" oppure null
}}
"""
                    content_parts = [{"type": "text", "text": multi_prompt}]
                    for img_b in scanned_images[:8]:
                        opt_b, opt_m = optimize_image_for_vision(img_b)
                        b64_str = base64.b64encode(opt_b).decode("utf-8")
                        content_parts.append({
                            "type": "image_url",
                            "image_url": {"url": f"data:{opt_m};base64,{b64_str}"}
                        })

                    messages = [{"role": "user", "content": content_parts}]
                    resp_text = self._call_openrouter(messages, max_tokens=4096, model_override=self.primary_model, temperature=0.1)
                    parsed = _extract_json_object(resp_text)
                    return _finalize(ExtractedDocument(**parsed))
                else:
                    # PDF senza layer di testo e senza immagini estraibili
                    return MockAIService().extract_document(file_bytes, mime_type, filename)

            # 2. GESTIONE DOCUMENTI OFFICE & FOGLI DI CALCOLO (.docx, .doc, .xlsx, .xls, .xlsm, .csv, .txt, .json)
            is_office = (
                any(fn.endswith(ext) for ext in [".docx", ".doc", ".xlsx", ".xls", ".xlsm", ".csv", ".tsv", ".txt", ".json", ".md"])
                or any(k in mt for k in ["sheet", "excel", "word", "officedocument", "csv"])
            )
            if is_office:
                from app.services.archive_service import extract_text_from_office_file
                office_text = extract_text_from_office_file(file_bytes, filename)
                if office_text:
                    try:
                        office_prompt = f"""Sei l'assistente 'Dove lo AI messo'. Analizza questo testo e tabelle estratti dal file Word/Excel/CSV caricato ({filename}):
---
{office_text[:3500]}
---

Identifica con la massima precisione:
1. 'title': un titolo chiaro, elegante e sintetico (es. 'Contratto di Consulenza Software', 'Foglio Spese e Scadenze Aziendali', 'Elenco Fornitori', 'Testo Canzone ...')
2. 'doc_type': scegli liberamente il tipo più adatto (es. 'canzone', 'poesia', 'testo_personale', 'ricetta', 'contratto', 'foglio_calcolo', 'spese', 'fattura', 'ricevuta', 'documento_word', 'report', 'generico'). Se il testo contiene strofe, canzoni, versi, rime o poesie, NON classificarlo MAI come bolletta o utenza!
3. 'issuer': nome ente, azienda, autore, artista o controparte (oppure null)
4. 'due_date': se contiene una data di scadenza, fine validità, termine o rinnovo (es. termine contratto, scadenza polizza, termine pagamento fattura/canone, foglio scadenze), estraila in formato YYYY-MM-DD. NON confondere la data di stipula con la scadenza! Se non c'è una scadenza o termine, imposta null.
5. 'amount': se è presente un importo monetario da saldare o pagare, estrailo come numero decimale (es. 1500.00), altrimenti null.
6. 'is_paid' & 'payment_status' & 'is_payable':
   VERIFICA ACCURATAMENTE SE IL FILE O FOGLIO RIPORTA STATO DI PAGAMENTO, QUIETANZA O SALDO:
   Cerca parole come 'PAGATO', 'SALDATO', 'QUIETANZATO', 'PAGATA', 'SALDATA', 'bonifico eseguito', 'ricevuta', 'quietanza'.
   - Se il documento/foglio indica che la spesa o fattura è già stata pagata/saldata:
     imposta "is_paid": true, "payment_status": "quietanzato", "is_payable": false (il debito è estinto).
   - Se è una spesa, fattura o canone da pagare con scadenza aperta:
     imposta "is_paid": false, "payment_status": "da_pagare", "is_payable": true.
   - Per contratti, note, testi musicali o file senza scadenze monetarie pendenti:
     imposta "is_paid": null, "payment_status": "non_richiesto", "is_payable": false.
7. 'summary': spiegazione chiara e completa di 2-3 frasi in italiano con i punti chiave, autore, argomenti, intestatari o dati più importanti.
8. 'suggest_rename': false.
9. 'category_label': consulta PRIMA queste cartelle generali di sistema: 'Utenze & Bollette', 'Fisco, Tributi & F24', 'Fatture, Spese & Ricevute', 'Contratti, Polizze & Assicurazioni', 'Documenti Personali & Identità', 'Sanità & Spese Mediche', 'Formazione, Studio & Certificati', 'Automobili & Veicoli', 'Canzoni, Musica & Testi Personali', 'Archivi Compressi & ZIP', 'Foto, Immagini & Ricordi'. Se il file è inerente a una di esse (es. testo canzone/poesia -> 'Canzoni, Musica & Testi Personali', scontrino/ricevuta -> 'Fatture, Spese & Ricevute'), USA QUELLA CARTELLA per evitare doppioni! Crea una nuova sezione tematica SOLO se il file non ha alcuna pertinenza con quelle sopra.
10. 'category': slug normalizzato in minuscolo con underscore (es. 'canzoni_musica', 'ricette_cucina', 'fogli_calcolo', 'contratti_polizze').
11. 'category_icon': l'icona FontAwesome 6 più appropriata (es. 'fa-music', 'fa-utensils', 'fa-graduation-cap', 'fa-car', 'fa-paw', 'fa-plane', 'fa-table', 'fa-file-lines', 'fa-bolt', 'fa-landmark', 'fa-receipt', 'fa-file-signature').
12. 'subfolder': estrai l'anno a 4 cifre (es. '2026', '2025', '2024') se presente una data, competenza o scadenza, oppure un sotto-tema (es. 'Locazioni', 'Bozze'); altrimenti imposta null.

Rispondi ESCLUSIVAMENTE in formato JSON valido con questa struttura esatta:
{{
  "title": "titolo chiaro ed elegante",
  "doc_type": "contratto" | "foglio_calcolo" | "spese" | "fattura" | "ricevuta" | "documento_word" | "testo_personale" | "canzone" | "report" | "generico",
  "issuer": "nome ente o fornitore" o null,
  "amount": null oppure numero decimale,
  "due_date": null oppure "YYYY-MM-DD",
  "is_payable": true oppure false,
  "is_paid": true oppure false oppure null,
  "payment_status": "da_pagare" | "quietanzato" | "non_richiesto",
  "summary": "riassunto dettagliato in 2-3 frasi in italiano",
  "tags": ["tag1", "tag2", "tag3"],
  "suggest_rename": false,
  "category": "slug_sezione",
  "category_label": "Titolo Sezione Scelto Dall'AI",
  "category_icon": "fa-icon",
  "subfolder": "2026" oppure null
}}
"""
                        messages = [{"role": "user", "content": office_prompt}]
                        resp_text = self._call_openrouter(messages, max_tokens=4096, model_override=self.primary_model, temperature=0.1)
                        parsed = _extract_json_object(resp_text)
                        return _finalize(ExtractedDocument(**parsed))
                    except Exception as off_err:
                        logger.warning(f"OpenRouter errore estrazione office {filename}: {off_err}. Fallback a parser locale.")
                return MockAIService().extract_document(file_bytes, mime_type, filename)

            # 3. GESTIONE ARCHIVI ZIP (.zip)
            if fn.endswith(".zip") or "archivio" in fn:
                import zipfile
                try:
                    with zipfile.ZipFile(io.BytesIO(file_bytes), "r") as zf:
                        names = [n for n in zf.namelist() if not n.startswith("__MACOSX") and not Path(n).name.startswith(".")]
                        clean_stem = Path(filename).stem.replace("_", " ").capitalize()
                        return _finalize(ExtractedDocument(
                            title=f"Archivio {clean_stem}",
                            doc_type="archivio_zip",
                            issuer="Dove lo AI messo",
                            amount=None,
                            due_date=None,
                            summary=f"Archivio compresso contenente {len(names)} file: {', '.join(names[:5])}{'...' if len(names) > 5 else ''}.",
                            tags=["zip", "archivio", "compresso"],
                            suggest_rename=False,
                            category="archivi_zip",
                            category_label="Archivi Compressi & ZIP",
                            category_icon="fa-file-zipper"
                        ))
                except Exception:
                    pass

            # 4. GESTIONE IMMAGINI (Foto, screenshot, scansioni grafiche)
            opt_bytes, opt_mt = optimize_image_for_vision(file_bytes)
            b64_img = base64.b64encode(opt_bytes).decode("utf-8")
            data_url = f"data:{opt_mt};base64,{b64_img}"

            prompt = (
                "Sei l'assistente 'Dove lo AI messo'. Analizza con precisione visiva questa immagine caricata dall'utente.\n\n"
                "Istruzioni:\n"
                "1. 'title': genera un titolo sintetico e descrittivo (massimo 4-6 parole) di ciò che vedi nell'immagine. "
                "Ad esempio se vedi un volante o quick release scrivi 'Base Volante con attacco rapido', se vedi delle chiavi scrivi 'Mazzo chiavi con telecomando', se vedi una bolletta scrivi 'Bolletta Enel Energia', se vedi una patente scrivi 'Patente di Guida', se vedi una carta d'identità scrivi 'Carta d'Identità'. "
                "NON usare MAI 'Generico File Utente' o nomi anonimi!\n"
                "2. 'doc_type': scegli tra 'bolletta', 'f24', 'ricevuta', 'fattura', 'patente', 'documento_identita', 'polizza', 'contratto', 'foto', 'screenshot', 'oggetto_fisico', 'generico'.\n"
                "3. 'issuer': se riconosci un ente, azienda, marchio o ministero visibile (es. 'Enel', 'Fanatec', 'Apple', 'Ministero Interno', 'INPS'), indicalo; altrimenti imposta null.\n"
                "4. 'due_date': se l'immagine mostra un documento con una data di scadenza o fine validità (es. scadenza carta d'identità, patente, passaporto, bolletta, revisione auto, contratti, polizze), estrai la data nel formato YYYY-MM-DD. NON confondere la data di rilascio con la scadenza! Se non c'è una data di scadenza, imposta null.\n"
                "5. 'amount': se è visibile un importo monetario da pagare o saldare, estrailo come numero decimale (es. 45.50); per documenti di identità, patenti, passaporti, foto o oggetti personali, imposta rigorosamente amount=null.\n"
                "6. 'is_paid' & 'payment_status' & 'is_payable':\n"
                "   VERIFICA ACCURATAMENTE SE NELL'IMMAGINE O DOCUMENTO È PRESENTE UN TIMBRO, SCRITTA O QUIETANZA DI PAGAMENTO:\n"
                "   Cerca con estrema attenzione timbri (anche rossi, blu o circolari), watermark o scritte come 'PAGATO', 'SALDATO', 'QUIETANZATO', 'PAGATA', 'SALDATA', ricevuta di bonifico o quietanza.\n"
                "   - Se è visibile il timbro 'PAGATO', dicitura di avvenuto pagamento o ricevuta di quietanza:\n"
                "     imposta 'is_paid': true, 'payment_status': 'quietanzato', 'is_payable': false (il pagamento è già stato effettuato, non va aperta una scadenza da pagare).\n"
                "   - Se è una bolletta, fattura, F24 o avviso ancora da pagare:\n"
                "     imposta 'is_paid': false, 'payment_status': 'da_pagare', 'is_payable': true.\n"
                "   - Per documenti di identità, patenti, passaporti, foto o oggetti senza transazione monetaria:\n"
                "     imposta 'is_paid': null, 'payment_status': 'non_richiesto', 'is_payable': false.\n"
                "7. 'summary': descrizione ricca ed accurata in 1-2 frasi in italiano di ciò che si vede visivamente nell'immagine (colori, forme, dettagli, marchi o testi visibili).\n"
                "8. 'suggest_rename': imposta true se si tratta della foto di un oggetto fisico, componente, dispositivo, screenshot o allegato non formale per cui è opportuno chiedere all'utente se desidera assegnargli un nome specifico o dove lo ripone. Imposta false per bollette, F24 e documenti d'identità con mittente certo.\n"
                "9. 'category_label': consulta PRIMA queste macro-cartelle generali di sistema per evitare doppioni: 'Utenze & Bollette', 'Fisco, Tributi & F24', 'Documenti Personali & Identità', 'Fatture, Spese & Ricevute', 'Sanità & Spese Mediche', 'Formazione, Studio & Certificati', 'Automobili & Veicoli', 'Canzoni, Musica & Testi Personali', 'Foto, Immagini & Ricordi', 'Archivi Compressi & ZIP'. Se il file è inerente a una di esse, USA QUELLA CARTELLA! Altrimenti crea una nuova sezione specifica. REGOLA TASSATIVA: NON usare MAI 'Oggetti Fisici' o 'Oggetto Fisico' come 'category_label' o 'category'! Se l'immagine ritrae un oggetto o un ambiente, assegna SEMPRE 'Foto & Immagini' (slug 'foto_immagini', icona 'fa-image'). Gli oggetti fisici appartengono all'inventario separato del caveau e non creano cartelle di documenti.\n"
                "10. 'category': slug minuscolo con underscore (es. 'utenze_bollette', 'documenti_identita', 'foto_immagini', 'contratti_polizze').\n"
                "11. 'category_icon': icona FontAwesome 6 adatta (es. 'fa-bolt', 'fa-landmark', 'fa-id-card', 'fa-receipt', 'fa-camera', 'fa-image', 'fa-music').\n"
                "12. 'subfolder': estrai l'anno a 4 cifre se presente una scadenza o data (es. '2026') oppure un sotto-tema; altrimenti imposta null.\n\n"
                "Rispondi ESCLUSIVAMENTE in formato JSON valido con questa struttura esatta:\n"
                "{\n"
                '  "title": "Titolo descrittivo intelligente",\n'
                '  "doc_type": "bolletta" | "f24" | "ricevuta" | "fattura" | "patente" | "documento_identita" | "polizza" | "foto" | "screenshot" | "oggetto_fisico" | "generico",\n'
                '  "issuer": "marchio/ente oppure null",\n'
                '  "amount": null oppure numero decimale,\n'
                '  "due_date": null oppure "YYYY-MM-DD",\n'
                '  "is_payable": true oppure false,\n'
                '  "is_paid": true oppure false oppure null,\n'
                '  "payment_status": "da_pagare" | "quietanzato" | "non_richiesto",\n'
                '  "summary": "descrizione accurata in italiano di cosa si vede",\n'
                '  "tags": ["tag1", "tag2"],\n'
                '  "suggest_rename": true,\n'
                '  "category": "slug_sezione",\n'
                '  "category_label": "Titolo Sezione Scelto Dall\'AI",\n'
                '  "category_icon": "fa-icon",\n'
                '  "subfolder": "2026" oppure null\n'
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
            return _finalize(ExtractedDocument(**parsed))
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
                "Sei l'assistente virtuale intelligente e cordiale di 'Dove lo AI messo' (Registro Dattiloscritto Olivetti). "
                "Aiuti famiglie e professionisti a ricordare dove hanno riposto oggetti importanti, "
                "a catalogare bollette e documenti (che l'utente può inviare allegando file o foto), "
                "e a tenere d'occhio le scadenze nella Dashboard in alto a destra.\n"
                "Rispondi in modo naturale, caldo, professionale e conciso in italiano. "
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
