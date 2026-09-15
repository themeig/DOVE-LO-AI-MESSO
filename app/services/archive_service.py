import io
import re
import csv
import json
import zipfile
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import or_

import docx
import openpyxl
import pypdf

from app.models.database import Document
from app.models.schemas import ExtractedDocument
from app.services.document_service import save_uploaded_file, read_decrypted_file
from app.services.ai_service import get_ai_service

logger = logging.getLogger(__name__)


def extract_text_from_office_file(file_bytes: bytes, filename: str) -> str:
    """
    Estrae il testo e i dati tabellari da file Word (.docx, .doc),
    fogli di calcolo Excel (.xlsx, .xls) o file di testo (.csv, .txt, .json, .md).
    """
    fn = (filename or "").lower()
    extracted_text = ""

    # 1. Documenti Word (.docx)
    if fn.endswith(".docx") or file_bytes.startswith(b"PK\x03\x04"):
        try:
            doc = docx.Document(io.BytesIO(file_bytes))
            paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
            
            # Estrai anche testo dalle tabelle
            table_lines = []
            for table in doc.tables:
                for row in table.rows:
                    row_cells = [c.text.strip() for c in row.cells if c.text.strip()]
                    if row_cells:
                        table_lines.append(" | ".join(row_cells))
            
            full_parts = []
            if paragraphs:
                full_parts.append("\n".join(paragraphs))
            if table_lines:
                full_parts.append("\n--- Tabelle nel Documento ---\n" + "\n".join(table_lines))
            extracted_text = "\n\n".join(full_parts)
        except Exception as e:
            logger.warning(f"Errore lettura docx {filename}: {e}")

    # 2. Fogli di calcolo Excel (.xlsx)
    if not extracted_text and (fn.endswith(".xlsx") or fn.endswith(".xlsm")):
        try:
            wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
            sheet_parts = []
            for sheet_name in wb.sheetnames[:5]:  # fino a 5 fogli
                ws = wb[sheet_name]
                rows_text = []
                for row_idx, row in enumerate(ws.iter_rows(values_only=True)):
                    if row_idx > 60:  # prime 60 righe
                        rows_text.append("... [ulteriori righe omesse]")
                        break
                    non_empty_cells = [str(c).strip() for c in row if c is not None and str(c).strip()]
                    if non_empty_cells:
                        rows_text.append(" | ".join(non_empty_cells))
                if rows_text:
                    sheet_parts.append(f"=== Foglio: {sheet_name} ===\n" + "\n".join(rows_text))
            extracted_text = "\n\n".join(sheet_parts)
        except Exception as e:
            logger.warning(f"Errore lettura xlsx {filename}: {e}")

    # 3. File CSV
    if not extracted_text and (fn.endswith(".csv") or fn.endswith(".tsv")):
        try:
            # Prova decodifiche utf-8 e latin-1
            text_content = ""
            for enc in ["utf-8", "latin-1", "cp1252"]:
                try:
                    text_content = file_bytes.decode(enc)
                    break
                except UnicodeDecodeError:
                    continue

            if text_content:
                lines = []
                reader = csv.reader(io.StringIO(text_content))
                for idx, row in enumerate(reader):
                    if idx > 80:
                        lines.append("... [ulteriori righe CSV omesse]")
                        break
                    if any(row):
                        lines.append(" | ".join(c.strip() for c in row))
                extracted_text = "\n".join(lines)
        except Exception as e:
            logger.warning(f"Errore lettura csv {filename}: {e}")

    # 4. File di testo generico (.txt, .md, .json, .xml)
    if not extracted_text and (fn.endswith(".txt") or fn.endswith(".md") or fn.endswith(".json") or fn.endswith(".xml") or fn.endswith(".log") or fn.endswith(".doc")):
        for enc in ["utf-8", "latin-1", "cp1252"]:
            try:
                extracted_text = file_bytes.decode(enc)
                break
            except Exception:
                continue

    return extracted_text.strip()


def create_zip_from_documents(
    db: Session,
    document_ids: Optional[List[int]] = None,
    query: Optional[str] = None,
    category: Optional[str] = None,
    archive_title: Optional[str] = None,
    thread_id: str = "general"
) -> Optional[Document]:
    """
    Crea un nuovo file compresso ZIP a partire da una selezione di documenti presenti nel caveau,
    lo salva cifrato nel caveau e crea il relativo record Document in SQLite.
    """
    q = db.query(Document)
    if thread_id and thread_id != "all":
        q = q.filter(Document.thread_id == thread_id)

    all_docs = q.order_by(Document.created_at.desc()).all()
    if document_ids:
        docs = [d for d in all_docs if d.id in document_ids]
    elif query and query.strip().lower() not in ["all", "tutti", "tutto", "*"]:
        from app.services.search_service import search_vault_documents
        matches = search_vault_documents(db, query, thread_id=thread_id)
        matched_ids = {m["id"] for m in matches}
        docs = [d for d in all_docs if d.id in matched_ids]
        if not docs:
            q_lower = query.strip().lower()
            docs = [
                d for d in all_docs
                if q_lower in (d.title or "").lower()
                or q_lower in (d.summary or "").lower()
                or q_lower in (d.issuer or "").lower()
                or q_lower in (d.doc_type or "").lower()
                or q_lower in Path(d.file_path or "").name.lower()
            ]
    elif category and category.strip().lower() != "all":
        cat_lower = category.strip().lower()
        docs = [d for d in all_docs if (d.doc_type or "").lower() == cat_lower]
    else:
        docs = all_docs

    if not docs:
        logger.warning("Nessun documento trovato per la creazione dello ZIP")
        return None

    zip_buffer = io.BytesIO()
    included_names = []

    with zipfile.ZipFile(zip_buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        # 1. Includi ciascun file decifrato
        for d in docs:
            if not d.file_path:
                continue
            fp = Path(d.file_path)
            if not fp.exists():
                continue
            try:
                decrypted = read_decrypted_file(fp)
                # Crea un nome descrittivo pulito
                ext = fp.suffix or (f".{d.file_type}" if d.file_type else ".bin")
                clean_name = f"{d.id}_{d.title[:40].replace(' ', '_').replace('/', '_')}{ext}"
                zf.writestr(clean_name, decrypted)
                included_names.append(d.title)
            except Exception as e:
                logger.warning(f"Errore aggiunta {d.title} allo ZIP: {e}")

        # 2. Aggiungi un file indice riassuntivo all'interno dello ZIP
        index_txt = f"Archivio creato da Dove lo AI messo in data {datetime.now().strftime('%d/%m/%Y %H:%M')}\n\n"
        index_txt += f"Documenti inclusi ({len(included_names)}):\n"
        for idx, name in enumerate(included_names, 1):
            index_txt += f"{idx}. {name}\n"
        zf.writestr("INDICE_DOCUMENTI.txt", index_txt.encode("utf-8"))

    zip_buffer.seek(0)
    zip_bytes = zip_buffer.getvalue()

    ts = datetime.now().strftime("%Y%m%d_%H%M")
    default_name = f"Archivio_{len(included_names)}_documenti_{ts}.zip"
    final_title = (archive_title or default_name).strip()
    if not final_title.lower().endswith(".zip"):
        final_filename = f"{final_title}.zip"
    else:
        final_filename = final_title

    saved_path = save_uploaded_file(zip_bytes, final_filename)

    summary_desc = f"Archivio compresso contenente {len(included_names)} documenti: {', '.join(included_names[:4])}"
    if len(included_names) > 4:
        summary_desc += f" e altri {len(included_names) - 4} file."

    zip_doc = Document(
        thread_id=thread_id,
        title=final_title.replace(".zip", "").replace("_", " "),
        file_path=saved_path,
        file_type="zip",
        doc_type="archivio_zip",
        issuer="Dove lo AI messo",
        amount=None,
        due_date=None,
        status="archiviato",
        summary=summary_desc,
        created_at=datetime.now(timezone.utc)
    )
    db.add(zip_doc)
    db.commit()
    db.refresh(zip_doc)

    return zip_doc


def unzip_document_to_vault(
    db: Session,
    document_id: Optional[int] = None,
    document_title: Optional[str] = None,
    thread_id: str = "general"
) -> List[Document]:
    """
    Estrae tutti i file contenuti all'interno di un documento ZIP del caveau,
    analizza ciascun file con l'AI e registra i nuovi documenti nel database.
    """
    doc = None
    if document_id:
        doc = db.query(Document).filter(Document.id == document_id).first()
    elif document_title:
        term = document_title.strip().lower()
        all_zips = db.query(Document).filter(
            or_(Document.file_type == "zip", Document.doc_type == "archivio_zip")
        ).all()
        doc = next((d for d in all_zips if term in (d.title or "").lower() or term in (d.summary or "").lower()), None)

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

    # Classificazione per tipo ed emittente
    if any(k in combo for k in ["bolletta", "fattura energia", "servizio elettrico", "luce", "gas", "acqua", "utenza", "enel", "a2a", "eni", "iren", "hera", "sorgenia", "acea", "edison", "tim", "vodafone", "wind", "iliad", "fastweb"]):
        doc_type = "bolletta"
        tags.extend(["bolletta", "utenza", "energia"])
        if "enel" in combo:
            issuer = "Enel Energia"
        elif "a2a" in combo:
            issuer = "A2A"
        elif "eni" in combo or "plenitude" in combo:
            issuer = "Eni Plenitude"
        elif "iren" in combo:
            issuer = "Iren"
        elif "hera" in combo:
            issuer = "Hera"
        elif "sorgenia" in combo:
            issuer = "Sorgenia"
        elif "acea" in combo:
            issuer = "Acea"
        elif "tim" in combo:
            issuer = "TIM"
        elif "vodafone" in combo:
            issuer = "Vodafone"
        elif "wind" in combo:
            issuer = "WindTre"
        elif "iliad" in combo:
            issuer = "Iliad"
        elif "fastweb" in combo:
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
        r'(?:scadenza|entro il|scade il|termine|data scadenza)[:\s]+(\d{1,2})[/\.-](\d{1,2})[/\.-](\d{2,4})',
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

    return ExtractedDocument(
        title=title or clean_stem.capitalize() or filename,
        doc_type=doc_type,
        issuer=issuer,
        amount=amount,
        due_date=due_date,
        summary=summary,
        tags=tags or ["archivio", "documento"],
        suggest_rename=False
    )


def unzip_document_to_vault(
    db: Session,
    document_id: Optional[int] = None,
    document_title: Optional[str] = None,
    thread_id: str = "general"
) -> List[Document]:
    """
    Estrae tutti i file contenuti all'interno di un documento ZIP del caveau,
    analizza istantaneamente ciascun file con parser ad altissima velocità e registra i nuovi documenti nel database.
    """
    doc = None
    if document_id:
        doc = db.query(Document).filter(Document.id == document_id).first()
    elif document_title:
        term = document_title.strip().lower()
        all_zips = db.query(Document).filter(
            or_(Document.file_type == "zip", Document.doc_type == "archivio_zip")
        ).all()
        doc = next((d for d in all_zips if term in (d.title or "").lower() or term in (d.summary or "").lower()), None)

    if not doc:
        # Cerca l'ultimo zip caricato
        doc = db.query(Document).filter(
            or_(Document.file_type == "zip", Document.doc_type == "archivio_zip")
        ).order_by(Document.created_at.desc()).first()

    if not doc or not doc.file_path:
        logger.warning(f"Nessun documento ZIP trovato con ID {document_id}")
        return []

    fp = Path(doc.file_path)
    if not fp.exists():
        logger.warning(f"File zip {fp} non trovato su disco")
        return []

    zip_bytes = read_decrypted_file(fp)
    extracted_docs: List[Document] = []

    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
            for info in zf.infolist():
                # Salta directory e file nascosti di sistema
                if info.is_dir() or "__MACOSX" in info.filename or Path(info.filename).name.startswith("."):
                    continue
                # Salta file di indice generati
                if Path(info.filename).name == "INDICE_DOCUMENTI.txt":
                    continue

                raw_inner_bytes = zf.read(info.filename)
                if not raw_inner_bytes:
                    continue

                inner_filename = Path(info.filename).name
                saved_path = save_uploaded_file(raw_inner_bytes, inner_filename)

                file_ext = Path(inner_filename).suffix.lstrip(".").lower() or "bin"
                mime = "application/pdf" if file_ext == "pdf" else (
                    f"image/{file_ext}" if file_ext in ["jpg", "jpeg", "png", "webp"] else "application/octet-stream"
                )

                # Estrazione immediata ad altissima velocità
                extracted = fast_extract_document_metadata(raw_inner_bytes, inner_filename, mime)

                due_date_obj = None
                if extracted.due_date:
                    try:
                        due_date_obj = datetime.strptime(extracted.due_date, "%Y-%m-%d").date()
                    except ValueError:
                        due_date_obj = None

                title = (extracted.title or "").strip()
                if not title:
                    clean_stem = Path(inner_filename).stem.replace("_", " ").strip()
                    title = clean_stem.capitalize()

                is_payable = (extracted.amount is not None) and (extracted.doc_type in ["bolletta", "f24", "fattura", "tributo", "avviso"])
                doc_status = "da_pagare" if is_payable else "archiviato"

                new_doc = Document(
                    thread_id=thread_id,
                    title=title,
                    file_path=saved_path,
                    file_type=file_ext,
                    doc_type=extracted.doc_type,
                    issuer=extracted.issuer,
                    amount=extracted.amount,
                    due_date=due_date_obj,
                    status=doc_status,
                    summary=extracted.summary,
                    created_at=datetime.now(timezone.utc)
                )
                db.add(new_doc)
                extracted_docs.append(new_doc)

        db.commit()
        for d in extracted_docs:
            db.refresh(d)

    except Exception as e:
        logger.error(f"Errore durante l'unzip di {doc.title}: {e}")

    return extracted_docs
