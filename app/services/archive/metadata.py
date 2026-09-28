"""
Modulo di estrazione metadati rapida e rule-based per file importati e archivi batch.
"""
import io
import re
import logging
from pathlib import Path
from datetime import datetime, date
from typing import Optional, List, Dict, Any
import pypdf

from app.models.schemas import ExtractedDocument
from app.services.document_service import determine_document_status, QUIETANZA_REGEX
from app.services.archive.inspectors import extract_text_from_office_file

logger = logging.getLogger(__name__)

def fast_extract_document_metadata(file_bytes: bytes, filename: str, mime_type: str = "") -> ExtractedDocument:
    """
    Estrazione ad altissima velocità e zero latenza di metadati, testo, importi e scadenze
    per documenti PDF, Office e immagini estratti da archivi o batch.
    """
    fn = (filename or "").lower()
    clean_stem = Path(filename).stem.replace("_", " ").replace("-", " ").strip()

    # 1. Estrazione testo reale
    text = ""
    if "pdf" in (mime_type or "") or fn.endswith(".pdf") or file_bytes.startswith(b"%PDF"):
        try:
            reader = pypdf.PdfReader(io.BytesIO(file_bytes))
            for p in reader.pages[:4]:
                t = p.extract_text()
                if t:
                    text += t + "\n"
        except Exception:
            pass
    elif any(fn.endswith(ext) for ext in [".docx", ".doc", ".xlsx", ".xls", ".csv", ".tsv", ".txt", ".json", ".md"]):
        text = extract_text_from_office_file(file_bytes, filename)

    text_lower = text.lower() if text else ""
    combo = f"{fn} {text_lower}"

    doc_type = "generico"
    issuer = None
    amount = None
    due_date = None
    tags = []
    is_paid = None
    payment_status = None
    is_payable = None

    if QUIETANZA_REGEX.search(combo):
        is_paid = True
        payment_status = "quietanzato"
        is_payable = False

    # Classificazione per tipo ed emittente
    # 0. Canzoni, musica, poesie e testi personali (PRIORITÀ)
    is_song_or_art = bool(re.search(
        r"\b(?:canzon[ei]|brano\s+musicale|testo\s+musicale|testo\s+di\s+un\s+brano|poesi[ae]|liric[ae]|strof[ae]|ritornell[oi]|cantautor[ei]|sfogo\s+emotivo|riflessioni\s+personali|pensieri\s+e\s+rimpianti|spartito|accordi)\b",
        combo
    ))
    if is_song_or_art:
        doc_type = "testo_personale"
        tags.extend(["musica", "testo", "canzone", "personale"])

    elif bool(re.search(r"\b(?:bollett[ae]|utenz[ae]|fornitur[ae]|servizio\s+elettrico|servizio\s+idrico|energia\s+elettrica)\b", combo)) or (
        bool(re.search(r"\b(?:enel|a2a|plenitude|eni\s+gas|iren|hera|sorgenia|acea|edison|vodafone|fastweb|iliad|windtre|\btim\b)\b", combo))
        and bool(re.search(r"\b(?:bollett[ae]|utenz[ae]|fornitur[ae]|fattur[ae]|consum[oi]|contatore|luce|gas|acqua)\b", combo))
    ):
        doc_type = "bolletta"
        tags.extend(["bolletta", "utenza", "energia"])
        if re.search(r"\benel\b", combo):
            issuer = "Enel Energia"
        elif re.search(r"\ba2a\b", combo):
            issuer = "A2A"
        elif re.search(r"\b(?:eni|plenitude)\b", combo):
            issuer = "Eni Plenitude"
        elif re.search(r"\biren\b", combo):
            issuer = "Iren"
        elif re.search(r"\bhera\b", combo):
            issuer = "Hera"
        elif re.search(r"\bsorgenia\b", combo):
            issuer = "Sorgenia"
        elif re.search(r"\bacea\b", combo):
            issuer = "Acea"
        elif re.search(r"\btim\b", combo):
            issuer = "TIM"
        elif re.search(r"\bvodafone\b", combo):
            issuer = "Vodafone"
        elif re.search(r"\bwind\b", combo):
            issuer = "WindTre"
        elif re.search(r"\biliad\b", combo):
            issuer = "Iliad"
        elif re.search(r"\bfastweb\b", combo):
            issuer = "Fastweb"

    elif any(k in combo for k in ["f24", "agenzia delle entrate", "modello f24", "tributo", "versamento unificato", "imu", "tari", "irpef", "iva"]):
        doc_type = "f24"
        issuer = "Agenzia delle Entrate"
        tags.extend(["f24", "fisco", "tributi", "tasse"])

    elif any(k in combo for k in ["730", "dichiarazione dei redditi", "modello 730", "redditi pf", "certificazione unica", "cu 20"]):
        doc_type = "dichiarazione_redditi"
        issuer = "Agenzia delle Entrate"
        tags.extend(["730", "fisco", "redditi", "fiscale"])

    elif any(k in combo for k in ["trenitalia", "italo", "biglietto", "ticket", "boarding pass", "carta imbarco", "volo", "ryanair", "easyjet", "ita airways"]):
        doc_type = "biglietto"
        if "trenitalia" in combo or "frecciarossa" in combo:
            issuer = "Trenitalia"
        elif "italo" in combo:
            issuer = "Italo NTV"
        elif "ryanair" in combo:
            issuer = "Ryanair"
        elif "easyjet" in combo:
            issuer = "EasyJet"
        elif "ita airways" in combo or "alitalia" in combo:
            issuer = "ITA Airways"
        tags.extend(["viaggio", "trasporti", "biglietto"])

    elif any(k in combo for k in ["certificato", "tolc", "cisia", "attestato", "laurea", "diploma", "esame", "iscrizione", "universit"]):
        doc_type = "certificato"
        if "cisia" in combo or "tolc" in combo:
            issuer = "CISIA"
        elif "universit" in combo:
            issuer = "Università"
        tags.extend(["certificato", "studio", "formazione"])

    elif any(k in combo for k in ["contratto", "accordo", "locazione", "affitto", "assunzione", "consulenza"]):
        doc_type = "contratto"
        tags.extend(["contratto", "legale", "accordo"])

    elif any(k in combo for k in ["ricevuta", "scontrino", "pos", "fattura", "quietanza", "pagamento"]):
        doc_type = "ricevuta"
        tags.extend(["ricevuta", "spese", "pagamento"])

    elif any(fn.endswith(ext) for ext in [".xlsx", ".xls", ".csv", ".tsv"]):
        doc_type = "foglio_calcolo"
        tags.extend(["excel", "tabelle", "dati"])

    elif any(fn.endswith(ext) for ext in [".docx", ".doc"]):
        doc_type = "documento_word"
        tags.extend(["word", "documento"])

    elif any(fn.endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"]):
        if any(k in fn for k in ["screen", "cattura", "screenshot"]):
            doc_type = "screenshot"
            tags.append("screenshot")
        else:
            doc_type = "foto"
            tags.append("foto")

    # Estrazione importo (da testo o pattern)
    amount_matches = re.findall(r'(?:totale|importo|da pagare|euro|eur|€)?\s*[:\s]?\s*(?:€|eur)?\s*(\d{1,5}[,\.]\d{2})\s*(?:€|eur|\b)', text, re.IGNORECASE)
    if amount_matches:
        try:
            val_str = amount_matches[0].replace(',', '.')
            parsed_amt = float(val_str)
            if 0.5 <= parsed_amt <= 50000.0:
                amount = parsed_amt
        except Exception:
            pass

    # Estrazione data scadenza (da testo o pattern)
    date_patterns = [
        r'(?:scadenza|entro il|scade il|termine|data scadenza|valido fino al|valida fino al|validità fino al)[:\s]+(\d{1,2})[/\.-](\d{1,2})[/\.-](\d{2,4})',
        r'(\d{4})-(\d{2})-(\d{2})'
    ]
    for pat in date_patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            try:
                if len(m.groups()) == 3 and len(m.group(3)) in [2, 4]:
                    d, month, y = m.group(1), m.group(2), m.group(3)
                    if len(y) == 2:
                        y = f"20{y}"
                    due_date = f"{int(y):04d}-{int(month):02d}-{int(d):02d}"
                    break
                elif len(m.groups()) == 3:
                    due_date = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
                    break
            except Exception:
                pass

    # Titolo pulito e comprensibile
    title_parts = []
    if doc_type != "generico":
        title_parts.append(doc_type.replace("_", " ").capitalize())
    if issuer:
        title_parts.append(issuer)

    words = [w.capitalize() for w in re.split(r'[_\-\s]+', clean_stem) if w.lower() not in ["pdf", "doc", "docx", "file", "documento", "archivio", "test", "dataset"]]
    if words:
        extra = [w for w in words if w.lower() not in (issuer or "").lower() and w.lower() not in doc_type]
        if extra:
            title = f"{' '.join(title_parts)} {' '.join(extra[:3])}".strip() if title_parts else " ".join(words)
        else:
            title = " ".join(title_parts) if title_parts else " ".join(words)
    else:
        title = " ".join(title_parts) if title_parts else clean_stem.capitalize()

    # Riassunto conciso
    sum_parts = [f"Documento '{filename}' catalogato come {doc_type}."]
    if issuer:
        sum_parts.append(f"Emittente: {issuer}.")
    if amount is not None:
        sum_parts.append(f"Importo: € {amount:.2f}.")
    if due_date:
        sum_parts.append(f"Scadenza: {due_date}.")
    summary = " ".join(sum_parts)

    # Determinazione categoria ed icona
    if is_song_or_art:
        category = "canzoni_musica"
        category_label = "Canzoni & Testi Musicali"
        category_icon = "fa-music"
    elif doc_type == "bolletta":
        category = "utenze_bollette"
        category_label = "Utenze & Bollette"
        category_icon = "fa-bolt"
    elif doc_type in ["f24", "dichiarazione_redditi"]:
        category = "fisco_tributi"
        category_label = "Fisco, Tributi & F24"
        category_icon = "fa-landmark"
    elif doc_type == "biglietto":
        category = "viaggi_trasporti"
        category_label = "Viaggi & Biglietti"
        category_icon = "fa-plane-departure"
    elif doc_type == "certificato":
        category = "formazione_studio"
        category_label = "Formazione & Certificati"
        category_icon = "fa-graduation-cap"
    elif doc_type == "contratto":
        category = "contratti_polizze"
        category_label = "Contratti, Polizze & Assicurazioni"
        category_icon = "fa-file-signature"
    elif doc_type == "ricevuta":
        category = "ricevute_spese"
        category_label = "Fatture, Spese & Ricevute"
        category_icon = "fa-receipt"
    elif doc_type == "foglio_calcolo":
        category = "fogli_calcolo"
        category_label = "Fogli di Calcolo & Dati"
        category_icon = "fa-table"
    elif doc_type == "documento_word":
        category = "documenti_testo"
        category_label = "Documenti di Testo & Note"
        category_icon = "fa-file-lines"
    elif doc_type in ["foto", "screenshot"]:
        category = "foto_immagini"
        category_label = "Foto & Immagini"
        category_icon = "fa-image"
    else:
        category = "altro"
        category_label = "Altri Documenti"
        category_icon = "fa-folder-closed"

    from app.services.category_service import resolve_or_create_category_and_subfolder
    slug, label, icon, subfolder = resolve_or_create_category_and_subfolder(
        proposed_label=category_label,
        document_text=summary,
        doc_type=doc_type,
        due_date=due_date,
        proposed_slug=category,
        proposed_icon=category_icon,
        filename=filename
    )

    return ExtractedDocument(
        title=title or clean_stem.capitalize() or filename,
        doc_type=doc_type,
        issuer=issuer,
        amount=amount,
        due_date=due_date,
        is_payable=is_payable,
        is_paid=is_paid,
        payment_status=payment_status,
        summary=summary,
        tags=tags or ["archivio", "documento"],
        suggest_rename=False,
        category=slug,
        category_label=label,
        category_icon=icon,
        subfolder=subfolder
    )


