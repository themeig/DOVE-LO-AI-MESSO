"""
Modulo di estrazione e ispezione dati tabellari per documenti Office, PDF, CSV, Excel e Word.
"""
import io
import re
import csv
import json
import zipfile
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any
import html
from datetime import datetime, date, timezone
from sqlalchemy.orm import Session
from sqlalchemy import or_

import docx
import openpyxl
from openpyxl.utils import get_column_letter
import pypdf
import xlrd

from app.models.database import Document
from app.services.document_service import read_decrypted_file

logger = logging.getLogger(__name__)

def _format_cell_value(val: Any) -> str:
    """Formatta i valori delle celle di un foglio di calcolo."""
    if val is None:
        return ""
    if isinstance(val, (datetime, )):
        return val.strftime("%d/%m/%Y %H:%M")
    if isinstance(val, date):
        return val.strftime("%d/%m/%Y")
    if isinstance(val, float):
        if val.is_integer():
            return str(int(val))
        return f"{val:.2f}"
    return str(val).strip()


def extract_text_from_office_file(file_bytes: bytes, filename: str) -> str:
    """
    Estrae il testo e i dati tabellari da file Word (.docx, .doc),
    fogli di calcolo Excel (.xlsx, .xls, .xlsm) o file di testo (.csv, .tsv, .txt, .json, .md).
    """
    fn = (filename or "").lower()
    extracted_text = ""

    is_word = fn.endswith((".docx", ".doc"))
    is_excel_ooxml = fn.endswith((".xlsx", ".xlsm"))
    is_excel_xls = fn.endswith(".xls")
    is_csv = fn.endswith((".csv", ".tsv"))

    # Se l'estensione è ambigua ma presenta il magic-byte ZIP PK\x03\x04, ispeziona l'archivio
    if not (is_word or is_excel_ooxml or is_excel_xls or is_csv) and file_bytes.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(file_bytes), "r") as zf:
                names = zf.namelist()
                if any(n.startswith("xl/") for n in names):
                    is_excel_ooxml = True
                elif any(n.startswith("word/") for n in names):
                    is_word = True
        except Exception:
            pass

    # 1. Documenti Word (.docx, .doc)
    if is_word and not is_excel_ooxml:
        try:
            doc = docx.Document(io.BytesIO(file_bytes))
            paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
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
            # Fallback estrazione stringhe binarie per vecchi file Word 97-2003 (.doc)
            try:
                ascii_matches = re.findall(rb"[\x20-\x7E\r\n\t]{4,}", file_bytes)
                extracted_lines = [m.decode("latin-1").strip() for m in ascii_matches if len(m.strip()) > 3]
                if extracted_lines:
                    extracted_text = "\n".join(extracted_lines[:150])
            except Exception:
                pass

    # 2. Fogli di calcolo Excel (.xlsx, .xlsm)
    if not extracted_text and is_excel_ooxml:
        try:
            wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
            sheet_parts = []
            for sheet_name in wb.sheetnames[:10]:
                ws = wb[sheet_name]
                rows_text = []
                for row_idx, row in enumerate(ws.iter_rows(values_only=True)):
                    if row_idx > 80:
                        rows_text.append("... [ulteriori righe omesse]")
                        break
                    non_empty_cells = [_format_cell_value(c) for c in row if c is not None and str(c).strip()]
                    if non_empty_cells:
                        rows_text.append(" | ".join(non_empty_cells))
                if rows_text:
                    sheet_parts.append(f"=== Foglio: {sheet_name} ===\n" + "\n".join(rows_text))
            extracted_text = "\n\n".join(sheet_parts)
        except Exception as e:
            logger.warning(f"Errore lettura xlsx {filename}: {e}")

    # 3. Fogli di calcolo Excel legacy (.xls)
    if not extracted_text and is_excel_xls:
        try:
            wb = xlrd.open_workbook(file_contents=file_bytes)
            sheet_parts = []
            for sheet_idx in range(min(len(wb.sheets()), 10)):
                ws = wb.sheet_by_index(sheet_idx)
                rows_text = []
                for row_idx in range(min(ws.nrows, 80)):
                    row_vals = [_format_cell_value(ws.cell_value(row_idx, col_idx)) for col_idx in range(ws.ncols)]
                    non_empty_cells = [c for c in row_vals if c]
                    if non_empty_cells:
                        rows_text.append(" | ".join(non_empty_cells))
                if rows_text:
                    sheet_parts.append(f"=== Foglio: {ws.name} ===\n" + "\n".join(rows_text))
            extracted_text = "\n\n".join(sheet_parts)
        except Exception as e:
            logger.warning(f"Errore lettura xls {filename}: {e}")

    # 4. File CSV e TSV
    if not extracted_text and is_csv:
        try:
            text_content = ""
            for enc in ["utf-8-sig", "utf-8", "latin-1", "cp1252"]:
                try:
                    text_content = file_bytes.decode(enc)
                    break
                except UnicodeDecodeError:
                    continue
            if text_content:
                lines = []
                reader = csv.reader(io.StringIO(text_content))
                for idx, row in enumerate(reader):
                    if idx > 100:
                        lines.append("... [ulteriori righe CSV omesse]")
                        break
                    if any(row):
                        lines.append(" | ".join(c.strip() for c in row))
                extracted_text = "\n".join(lines)
        except Exception as e:
            logger.warning(f"Errore lettura csv {filename}: {e}")

    # 5. File di testo generico (.txt, .md, .json, .xml)
    if not extracted_text and (fn.endswith((".txt", ".md", ".json", ".xml", ".log", ".yaml", ".yml"))):
        for enc in ["utf-8-sig", "utf-8", "latin-1", "cp1252"]:
            try:
                extracted_text = file_bytes.decode(enc)
                break
            except Exception:
                continue

    return extracted_text.strip()


def _filter_rows_by_query(all_rows: List[Any], query: Optional[str], max_rows: int = 100) -> List[Any]:
    """Filtra le righe di un foglio/tabella per query o parole chiave significative, preservando la tabella se non ci sono filtri."""
    if not query or not query.strip():
        return all_rows[:max_rows]
    q_clean = query.strip().lower()
    from app.services.search_service import ITALIAN_STOPWORDS
    extra_stop = {"foglio", "excel", "file", "tabella", "riga", "righe", "colonna", "colonne", "cella", "celle", "cliente", "cosa", "trova", "cerca", "mostra", "qual", "quale"}
    tokens = [w for w in re.split(r"[^\w]+", q_clean) if len(w) > 1 and w not in ITALIAN_STOPWORDS and w not in extra_stop]

    matching_rows = []
    for r_num, r_cells in all_rows:
        row_text = " ".join(r_cells).lower()
        if q_clean in row_text:
            matching_rows.append((r_num, r_cells))
        elif tokens and all(t in row_text for t in tokens):
            matching_rows.append((r_num, r_cells))

    # Se 'all tokens' non ha trovato nulla, prova con almeno un token significativo
    if not matching_rows and tokens:
        for r_num, r_cells in all_rows:
            row_text = " ".join(r_cells).lower()
            if any(t in row_text for t in tokens):
                matching_rows.append((r_num, r_cells))

    # Se ancora vuoto (es. domanda generica senza parole presenti nelle celle), ritorna le prime righe del foglio
    if not matching_rows:
        return all_rows[:max_rows]
    return matching_rows[:max_rows]


def inspect_document_content(
    file_bytes: bytes,
    file_type: str = "",
    filename: str = "",
    sheet_name: Optional[str] = None,
    query: Optional[str] = None,
    max_rows: int = 100
) -> Dict[str, Any]:
    """
    Ispeziona ed estrae il contenuto tabellare e testuale reale e puntuale di un file memorizzato nel caveau.
    Supporta Excel (.xlsx, .xlsm, .xls), CSV, TSV, Word (.docx, .doc), PDF (.pdf) e file di testo (.txt, .json, .md).
    Fornisce tabelle Markdown con coordinate, numeri di riga e lettere colonna (es. A, B, C) e valori calcolati delle formule.
    """
    fn = (filename or "").lower()
    ft = (file_type or "").lower()

    is_docx = fn.endswith((".docx", ".doc")) or ft in ["docx", "doc", "word"]
    is_xlsx = fn.endswith((".xlsx", ".xlsm", ".xltx")) or ft in ["xlsx", "xlsm", "excel", "spreadsheet"]
    is_xls = fn.endswith(".xls") or ft == "xls"
    is_csv = fn.endswith((".csv", ".tsv")) or ft in ["csv", "tsv"]
    is_pdf = fn.endswith(".pdf") or ft in ["pdf", "application/pdf"]
    is_txt = fn.endswith((".txt", ".md", ".json", ".xml", ".log", ".yaml", ".yml", ".py", ".sql")) or ft in ["txt", "text"]

    # Se archivio zip non marcato, controlla se ha cartella xl/ o word/
    if not (is_docx or is_xlsx or is_xls or is_csv or is_pdf or is_txt) and file_bytes.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(file_bytes), "r") as zf:
                names = zf.namelist()
                if any(n.startswith("xl/") for n in names):
                    is_xlsx = True
                elif any(n.startswith("word/") for n in names):
                    is_docx = True
        except Exception:
            pass

    # 1. FOGLI DI CALCOLO EXCEL MODERNI (.xlsx, .xlsm)
    if is_xlsx:
        try:
            wb_data = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
            # Carica anche versione formule se disponibile per arricchire celle calcolate
            try:
                wb_formula = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=False)
            except Exception:
                wb_formula = None

            available_sheets = list(wb_data.sheetnames)
            if not available_sheets:
                return {
                    "success": False,
                    "error": "Nessun foglio di lavoro trovato nella cartella Excel.",
                    "filename": filename
                }

            target_sheet = available_sheets[0]
            if sheet_name:
                s_clean = sheet_name.strip().lower()
                for sn in available_sheets:
                    if sn.lower() == s_clean or s_clean in sn.lower():
                        target_sheet = sn
                        break

            ws_d = wb_data[target_sheet]
            ws_f = wb_formula[target_sheet] if (wb_formula and target_sheet in wb_formula.sheetnames) else None

            all_rows = []
            max_cols = 0

            # Estrai righe mantenendo l'indice 1-based originale di Excel
            rows_data = list(ws_d.iter_rows(values_only=True))
            rows_form = list(ws_f.iter_rows(values_only=True)) if ws_f else [None] * len(rows_data)

            for r_idx, (r_d, r_f) in enumerate(zip(rows_data, rows_form), start=1):
                row_cells = []
                r_f_cells = r_f if r_f else [None] * (len(r_d) if r_d else 0)

                for cd, cf in zip(r_d or [], r_f_cells or []):
                    c_formatted = _format_cell_value(cd)
                    c_formula = str(cf).strip() if (cf is not None and str(cf).startswith("=")) else ""

                    if c_formatted and c_formula and c_formula != c_formatted:
                        row_cells.append(f"{c_formatted} (formula: {c_formula})")
                    elif c_formatted:
                        row_cells.append(c_formatted)
                    elif c_formula:
                        row_cells.append(c_formula)
                    else:
                        row_cells.append("")

                while row_cells and not row_cells[-1]:
                    row_cells.pop()

                if any(c for c in row_cells):
                    all_rows.append((r_idx, row_cells))
                    if len(row_cells) > max_cols:
                        max_cols = len(row_cells)

            if not all_rows:
                return {
                    "success": True,
                    "filename": filename,
                    "file_type": "xlsx",
                    "sheets": available_sheets,
                    "active_sheet": target_sheet,
                    "total_rows": 0,
                    "total_cols": 0,
                    "markdown_table": "_Il foglio di lavoro selezionato è vuoto._",
                    "summary": f"Foglio '{target_sheet}' vuoto. Fogli disponibili: {', '.join(available_sheets)}."
                }

            # Intestazioni con lettere di colonna (A, B, C...)
            first_row_num, first_row_cells = all_rows[0]
            headers = []
            for c_i in range(max_cols):
                col_letter = get_column_letter(c_i + 1)
                h_name = first_row_cells[c_i] if c_i < len(first_row_cells) and first_row_cells[c_i] else f"Colonna_{col_letter}"
                headers.append(f"{col_letter} ({h_name})")

            # Filtra per query
            matching_rows = _filter_rows_by_query(all_rows, query, max_rows)

            header_line = "| Riga | " + " | ".join(headers) + " |"
            sep_line = "| :--- | " + " | ".join([":---"] * max_cols) + " |"
            data_lines = []
            for r_num, r_cells in matching_rows[:max_rows]:
                padded = r_cells + [""] * (max_cols - len(r_cells))
                escaped = [c.replace("|", "\\|").replace("\n", " ") for c in padded]
                data_lines.append(f"| {r_num} | " + " | ".join(escaped) + " |")

            table_md = "\n".join([header_line, sep_line] + data_lines)
            msg = (
                f"File Excel '{filename}' - Foglio '{target_sheet}' (Fogli presenti: {', '.join(available_sheets)}). "
                f"Trovate {len(matching_rows)} righe (su {len(all_rows)} totali nel foglio)."
            )

            return {
                "success": True,
                "filename": filename,
                "file_type": "xlsx",
                "sheets": available_sheets,
                "active_sheet": target_sheet,
                "total_rows": len(all_rows),
                "total_cols": max_cols,
                "displayed_rows_count": len(matching_rows[:max_rows]),
                "query": query,
                "markdown_table": table_md,
                "summary": msg
            }
        except Exception as e:
            logger.error(f"Errore ispezione excel {filename}: {e}", exc_info=True)
            return {"success": False, "error": str(e), "filename": filename}

    # 2. FOGLI DI CALCOLO EXCEL LEGACY (.xls)
    if is_xls:
        try:
            wb = xlrd.open_workbook(file_contents=file_bytes)
            available_sheets = wb.sheet_names()
            if not available_sheets:
                return {"success": False, "error": "Nessun foglio trovato nel file XLS.", "filename": filename}

            target_sheet = available_sheets[0]
            if sheet_name:
                s_clean = sheet_name.strip().lower()
                for sn in available_sheets:
                    if sn.lower() == s_clean or s_clean in sn.lower():
                        target_sheet = sn
                        break

            ws = wb.sheet_by_name(target_sheet)
            all_rows = []
            max_cols = ws.ncols

            for r_idx in range(ws.nrows):
                row_cells = [_format_cell_value(ws.cell_value(r_idx, c)) for c in range(ws.ncols)]
                while row_cells and not row_cells[-1]:
                    row_cells.pop()
                if any(row_cells):
                    all_rows.append((r_idx + 1, row_cells))

            if not all_rows:
                return {
                    "success": True,
                    "filename": filename,
                    "file_type": "xls",
                    "sheets": available_sheets,
                    "active_sheet": target_sheet,
                    "total_rows": 0,
                    "total_cols": 0,
                    "markdown_table": "_Foglio vuoto._",
                    "summary": f"Foglio '{target_sheet}' vuoto."
                }

            first_row_num, first_row_cells = all_rows[0]
            headers = []
            for c_i in range(max_cols):
                col_letter = get_column_letter(c_i + 1)
                h_name = first_row_cells[c_i] if c_i < len(first_row_cells) and first_row_cells[c_i] else f"Colonna_{col_letter}"
                headers.append(f"{col_letter} ({h_name})")

            matching_rows = _filter_rows_by_query(all_rows, query, max_rows)

            header_line = "| Riga | " + " | ".join(headers) + " |"
            sep_line = "| :--- | " + " | ".join([":---"] * max_cols) + " |"
            data_lines = []
            for r_num, r_cells in matching_rows[:max_rows]:
                padded = r_cells + [""] * (max_cols - len(r_cells))
                escaped = [c.replace("|", "\\|").replace("\n", " ") for c in padded]
                data_lines.append(f"| {r_num} | " + " | ".join(escaped) + " |")

            table_md = "\n".join([header_line, sep_line] + data_lines)
            return {
                "success": True,
                "filename": filename,
                "file_type": "xls",
                "sheets": available_sheets,
                "active_sheet": target_sheet,
                "total_rows": len(all_rows),
                "total_cols": max_cols,
                "displayed_rows_count": len(matching_rows[:max_rows]),
                "query": query,
                "markdown_table": table_md,
                "summary": f"File Excel XLS '{filename}' - Foglio '{target_sheet}'. Trovate {len(matching_rows)} righe."
            }
        except Exception as e:
            logger.error(f"Errore ispezione xls {filename}: {e}")
            return {"success": False, "error": str(e), "filename": filename}

    # 3. FILE CSV O TSV
    if is_csv:
        try:
            text_content = ""
            for enc in ["utf-8-sig", "utf-8", "latin-1", "cp1252"]:
                try:
                    text_content = file_bytes.decode(enc)
                    break
                except UnicodeDecodeError:
                    continue

            if not text_content.strip():
                return {"success": False, "error": "File CSV vuoto o non decodificabile.", "filename": filename}

            delimiter = ","
            sample = text_content[:2048]
            if sample.count(";") > sample.count(","):
                delimiter = ";"
            elif sample.count("\t") > sample.count(","):
                delimiter = "\t"

            reader = csv.reader(io.StringIO(text_content), delimiter=delimiter)
            all_rows = []
            max_cols = 0
            for r_idx, row in enumerate(reader, start=1):
                clean_row = [c.strip() for c in row]
                while clean_row and not clean_row[-1]:
                    clean_row.pop()
                if any(clean_row):
                    all_rows.append((r_idx, clean_row))
                    if len(clean_row) > max_cols:
                        max_cols = len(clean_row)

            if not all_rows:
                return {"success": True, "filename": filename, "file_type": "csv", "markdown_table": "_File CSV vuoto._", "total_rows": 0, "total_cols": 0}

            first_row_num, first_row_cells = all_rows[0]
            headers = []
            for c_i in range(max_cols):
                col_letter = get_column_letter(c_i + 1)
                h_name = first_row_cells[c_i] if c_i < len(first_row_cells) and first_row_cells[c_i] else f"Colonna_{col_letter}"
                headers.append(f"{col_letter} ({h_name})")

            matching_rows = _filter_rows_by_query(all_rows, query, max_rows)

            header_line = "| Riga | " + " | ".join(headers) + " |"
            sep_line = "| :--- | " + " | ".join([":---"] * max_cols) + " |"
            data_lines = []
            for r_num, r_cells in matching_rows[:max_rows]:
                padded = r_cells + [""] * (max_cols - len(r_cells))
                escaped = [c.replace("|", "\\|").replace("\n", " ") for c in padded]
                data_lines.append(f"| {r_num} | " + " | ".join(escaped) + " |")

            table_md = "\n".join([header_line, sep_line] + data_lines)
            return {
                "success": True,
                "filename": filename,
                "file_type": "csv",
                "total_rows": len(all_rows),
                "total_cols": max_cols,
                "displayed_rows_count": len(matching_rows[:max_rows]),
                "query": query,
                "markdown_table": table_md,
                "summary": f"File CSV '{filename}' ({len(all_rows)} righe, {max_cols} colonne). Delimitatore: '{delimiter}'."
            }
        except Exception as e:
            logger.error(f"Errore ispezione csv {filename}: {e}")
            return {"success": False, "error": str(e), "filename": filename}

    # 4. DOCUMENTI WORD (.docx, .doc)
    if is_docx:
        try:
            doc = docx.Document(io.BytesIO(file_bytes))
            blocks = []
            for t_idx, table in enumerate(doc.tables, start=1):
                t_rows = []
                t_max_cols = 0
                for r_idx, row in enumerate(table.rows, start=1):
                    row_cells = [c.text.strip().replace("\n", " ") for c in row.cells]
                    if any(row_cells):
                        t_rows.append((r_idx, row_cells))
                        if len(row_cells) > t_max_cols:
                            t_max_cols = len(row_cells)
                if t_rows:
                    t_hdr = "| Riga | " + " | ".join([f"Colonna {i+1}" for i in range(t_max_cols)]) + " |"
                    t_sep = "| :--- | " + " | ".join([":---"] * t_max_cols) + " |"
                    t_lines = []
                    for r_num, r_c in t_rows[:max_rows]:
                        padded = r_c + [""] * (t_max_cols - len(r_c))
                        escaped = [c.replace("|", "\\|") for c in padded]
                        t_lines.append(f"| {r_num} | " + " | ".join(escaped) + " |")
                    blocks.append(f"### Tabella {t_idx} nel documento Word:\n" + "\n".join([t_hdr, t_sep] + t_lines))

            paras = []
            for p_idx, p in enumerate(doc.paragraphs, start=1):
                txt = p.text.strip()
                if txt:
                    paras.append((p_idx, txt))

            matching_paras = []
            if query and query.strip():
                q_clean = query.strip().lower()
                for p_num, p_txt in paras:
                    if q_clean in p_txt.lower():
                        matching_paras.append((p_num, p_txt))
            else:
                matching_paras = paras[:max_rows]

            if matching_paras:
                p_text = "\n\n".join([f"**[Paragrafo {p_num}]**: {p_txt}" for p_num, p_txt in matching_paras[:max_rows]])
                blocks.append("### Testo Documento:\n" + p_text)

            content_text = "\n\n".join(blocks) if blocks else "_Nessun testo o tabella rilevata nel documento Word._"
            return {
                "success": True,
                "filename": filename,
                "file_type": "docx",
                "total_paragraphs": len(paras),
                "total_tables": len(doc.tables),
                "displayed_paragraphs_count": len(matching_paras),
                "query": query,
                "content_text": content_text,
                "markdown_table": blocks[0] if (blocks and blocks[0].startswith("### Tabella")) else "",
                "summary": f"Documento Word '{filename}': {len(paras)} paragrafi, {len(doc.tables)} tabelle."
            }
        except Exception as e:
            logger.error(f"Errore ispezione docx {filename}: {e}")
            return {"success": False, "error": str(e), "filename": filename}

    # 5. DOCUMENTI PDF (.pdf)
    if is_pdf:
        try:
            reader = pypdf.PdfReader(io.BytesIO(file_bytes))
            total_pages = len(reader.pages)
            page_blocks = []
            q_clean = query.strip().lower() if (query and query.strip()) else None

            for p_num, page in enumerate(reader.pages, start=1):
                raw_t = page.extract_text() or ""
                lines = [line.strip() for line in raw_t.splitlines() if line.strip()]
                if not lines:
                    continue

                if q_clean:
                    matching_lines = [l for l in lines if q_clean in l.lower()]
                    if matching_lines:
                        page_blocks.append(
                            f"### Pagina {p_num} di {total_pages} (trovate {len(matching_lines)} righe pertinenti):\n"
                            + "\n".join(f"- {l}" for l in matching_lines[:40])
                        )
                else:
                    if p_num <= 5:
                        page_blocks.append(f"### Pagina {p_num} di {total_pages}:\n" + "\n".join(lines[:60]))

            if not page_blocks and not q_clean:
                has_scanned_img = False
                try:
                    for p in reader.pages[:5]:
                        if hasattr(p, "images") and len(p.images) > 0:
                            has_scanned_img = True
                            break
                except Exception:
                    pass

                if has_scanned_img:
                    content_text = f"Documento PDF '{filename}': scansione fotografica/grafica di {total_pages} pagine (immagine ad alta risoluzione senza testo digitale)."
                else:
                    content_text = "_Nessun testo estratto dal PDF._"
            else:
                content_text = "\n\n".join(page_blocks) if page_blocks else f"_Nessuna riga corrispondente a '{query}' trovata nel PDF._"
            return {
                "success": True,
                "filename": filename,
                "file_type": "pdf",
                "total_pages": total_pages,
                "query": query,
                "content_text": content_text,
                "summary": f"Documento PDF '{filename}': {total_pages} pagine analizzate."
            }
        except Exception as e:
            logger.error(f"Errore ispezione pdf {filename}: {e}")
            return {"success": False, "error": str(e), "filename": filename}

    # 6. FILE TESTO GENERICO (.txt, .json, .md, .xml, .log)
    try:
        text_content = ""
        for enc in ["utf-8-sig", "utf-8", "latin-1", "cp1252"]:
            try:
                text_content = file_bytes.decode(enc)
                break
            except Exception:
                continue

        lines = text_content.splitlines()
        q_clean = query.strip().lower() if (query and query.strip()) else None

        if q_clean:
            matching_lines = [(i + 1, l) for i, l in enumerate(lines) if q_clean in l.lower()]
            out_lines = "\n".join(f"L{i}: {l}" for i, l in matching_lines[:max_rows])
            total_matched = len(matching_lines)
        else:
            out_lines = "\n".join(f"L{i+1}: {l}" for i, l in enumerate(lines[:max_rows]))
            total_matched = min(len(lines), max_rows)

        return {
            "success": True,
            "filename": filename,
            "file_type": "txt",
            "total_lines": len(lines),
            "displayed_lines_count": total_matched,
            "query": query,
            "content_text": out_lines,
            "summary": f"File di testo '{filename}': {len(lines)} righe totali."
        }
    except Exception as e:
        logger.error(f"Errore ispezione testo {filename}: {e}")
        return {"success": False, "error": str(e), "filename": filename}


def render_office_file_to_html(file_bytes: bytes, filename: str) -> dict:
    """
    Converte un documento Word (.docx, .doc), un foglio Excel (.xlsx, .xls),
    un CSV o un file di testo in una struttura dati con HTML pronto per il rendering
    nel modale anteprima del caveau.
    """
    fn = (filename or "").lower()
    clean_title = Path(filename).stem.replace("_", " ").replace("-", " ").strip().title()

    is_docx = fn.endswith((".docx", ".doc"))
    is_xlsx = fn.endswith((".xlsx", ".xlsm"))
    is_xls = fn.endswith(".xls")
    is_csv = fn.endswith((".csv", ".tsv"))
    is_txt = fn.endswith((".txt", ".md", ".json", ".xml", ".log", ".yaml", ".yml"))
    is_pdf = fn.endswith(".pdf") or file_bytes.startswith(b"%PDF")
    is_zip = (fn.endswith(".zip") or ("zip" in fn and not (is_docx or is_xlsx or is_pdf)))

    # Se archivio zip non marcato, controlla se ha cartella xl/ o word/
    if not (is_docx or is_xlsx or is_xls or is_csv or is_txt) and file_bytes.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(file_bytes), "r") as zf:
                names = zf.namelist()
                if any(n.startswith("xl/") for n in names):
                    is_xlsx = True
                elif any(n.startswith("word/") for n in names):
                    is_docx = True
                else:
                    is_zip = True
        except Exception:
            pass

    # A. FOGLI DI CALCOLO EXCEL / CSV
    if is_xlsx or is_xls or is_csv:
        sheets_data = []

        if is_xlsx:
            try:
                wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
                for s_name in wb.sheetnames[:10]:
                    ws = wb[s_name]
                    sheet_rows = []
                    for row_idx, row in enumerate(ws.iter_rows(values_only=True)):
                        if row_idx > 250:
                            break
                        row_vals = [_format_cell_value(c) for c in row]
                        while row_vals and row_vals[-1] == "":
                            row_vals.pop()
                        sheet_rows.append(row_vals)
                    while sheet_rows and not any(sheet_rows[-1]):
                        sheet_rows.pop()
                    if sheet_rows:
                        max_cols = max(len(r) for r in sheet_rows) if sheet_rows else 0
                        padded_rows = [r + [""] * (max_cols - len(r)) for r in sheet_rows]
                        sheets_data.append({
                            "name": s_name,
                            "row_count": len(padded_rows),
                            "col_count": max_cols,
                            "rows": padded_rows
                        })
            except Exception as e:
                logger.error(f"Errore rendering xlsx {filename}: {e}")

        elif is_xls:
            try:
                wb = xlrd.open_workbook(file_contents=file_bytes)
                for s_idx in range(min(len(wb.sheets()), 10)):
                    ws = wb.sheet_by_index(s_idx)
                    sheet_rows = []
                    for r_idx in range(min(ws.nrows, 250)):
                        row_vals = [_format_cell_value(ws.cell_value(r_idx, c_idx)) for c_idx in range(ws.ncols)]
                        while row_vals and row_vals[-1] == "":
                            row_vals.pop()
                        sheet_rows.append(row_vals)
                    while sheet_rows and not any(sheet_rows[-1]):
                        sheet_rows.pop()
                    if sheet_rows:
                        max_cols = max(len(r) for r in sheet_rows) if sheet_rows else 0
                        padded_rows = [r + [""] * (max_cols - len(r)) for r in sheet_rows]
                        sheets_data.append({
                            "name": ws.name,
                            "row_count": len(padded_rows),
                            "col_count": max_cols,
                            "rows": padded_rows
                        })
            except Exception as e:
                logger.error(f"Errore rendering xls {filename}: {e}")

        elif is_csv:
            try:
                text_content = ""
                for enc in ["utf-8-sig", "utf-8", "latin-1", "cp1252"]:
                    try:
                        text_content = file_bytes.decode(enc)
                        break
                    except Exception:
                        continue
                if text_content:
                    reader = csv.reader(io.StringIO(text_content))
                    sheet_rows = []
                    for r_idx, row in enumerate(reader):
                        if r_idx > 250:
                            break
                        row_vals = [c.strip() for c in row]
                        sheet_rows.append(row_vals)
                    while sheet_rows and not any(sheet_rows[-1]):
                        sheet_rows.pop()
                    if sheet_rows:
                        max_cols = max(len(r) for r in sheet_rows) if sheet_rows else 0
                        padded_rows = [r + [""] * (max_cols - len(r)) for r in sheet_rows]
                        sheets_data.append({
                            "name": "Foglio Dati",
                            "row_count": len(padded_rows),
                            "col_count": max_cols,
                            "rows": padded_rows
                        })
            except Exception as e:
                logger.error(f"Errore rendering csv {filename}: {e}")

        html_parts = []
        html_parts.append(f"""
        <div class="flex items-center justify-between gap-2 pb-3 mb-3 border-b border-slate-200 shrink-0">
            <div class="flex items-center gap-2.5">
                <div class="w-8 h-8 rounded-lg bg-emerald-100 text-emerald-700 flex items-center justify-center font-bold text-sm">
                    <i class="fa-solid fa-file-excel"></i>
                </div>
                <div>
                    <h3 class="text-xs font-bold text-slate-900">{html.escape(filename)}</h3>
                    <p class="text-[11px] text-slate-500">{len(sheets_data)} fogli{'o' if len(sheets_data) == 1 else 'i'} di calcolo rilevat{'o' if len(sheets_data) == 1 else 'i'}</p>
                </div>
            </div>
            <div class="text-[11px] text-slate-400 bg-slate-100 px-2.5 py-1 rounded-md">
                <span>Foglio di calcolo interattivo</span>
            </div>
        </div>
        """)

        if len(sheets_data) > 1:
            html_parts.append('<div class="flex items-center gap-1.5 border-b border-slate-200 bg-slate-50 p-1.5 rounded-t-lg overflow-x-auto mb-2 shrink-0" id="officeSheetTabBar">')
            for idx, s in enumerate(sheets_data):
                active_cls = "bg-white text-emerald-800 font-bold shadow-2xs border-emerald-300" if idx == 0 else "text-slate-600 hover:text-slate-900 hover:bg-slate-100 border-transparent"
                html_parts.append(f"""
                    <button type="button" onclick="switchOfficeSheet({idx})" id="officeSheetTab_{idx}" class="office-sheet-tab px-3 py-1 text-xs rounded-md border transition flex items-center gap-1.5 shrink-0 {active_cls}">
                        <i class="fa-regular fa-file-lines text-[11px]"></i>
                        <span>{html.escape(s['name'])}</span>
                        <span class="text-[10px] text-slate-400">({s['row_count']} r.)</span>
                    </button>
                """)
            html_parts.append('</div>')

        for idx, s in enumerate(sheets_data):
            hidden_cls = "" if idx == 0 else "hidden"
            html_parts.append(f'<div id="officeSheetPanel_{idx}" class="office-sheet-panel flex flex-col h-full overflow-hidden {hidden_cls}">')
            html_parts.append(f'<div class="flex items-center justify-between text-[11px] text-slate-500 mb-1.5 px-1 shrink-0"><span>Foglio: <strong class="text-slate-700">{html.escape(s["name"])}</strong> ({s["row_count"]} righe, {s["col_count"]} colonne)</span></div>')
            html_parts.append('<div class="overflow-auto border border-slate-200 rounded-lg shadow-2xs flex-1 max-h-[64vh] bg-white">')
            html_parts.append('<table class="w-full text-xs text-left border-collapse font-sans min-w-full">')

            if s["rows"]:
                first_row = s["rows"][0]
                html_parts.append('<thead class="sticky top-0 bg-slate-100 z-10 border-b border-slate-200 shadow-2xs"><tr>')
                html_parts.append('<th class="py-2 px-2.5 bg-slate-200 text-slate-500 font-mono text-[10px] w-10 text-center border-r border-slate-300 select-none">#</th>')
                for c_idx, cell in enumerate(first_row):
                    col_header = html.escape(str(cell)) if cell else f"Col {chr(65 + c_idx) if c_idx < 26 else c_idx+1}"
                    html_parts.append(f'<th class="py-2 px-3 text-slate-700 font-bold text-[11px] whitespace-nowrap border-r border-slate-200">{col_header}</th>')
                html_parts.append('</tr></thead>')

                html_parts.append('<tbody class="divide-y divide-slate-100">')
                for r_idx, row in enumerate(s["rows"][1:], start=2):
                    html_parts.append('<tr class="hover:bg-emerald-50/40 transition-colors odd:bg-white even:bg-slate-50/50">')
                    html_parts.append(f'<td class="py-1.5 px-2 bg-slate-100 text-slate-400 font-mono text-[10px] text-center border-r border-slate-200 select-none">{r_idx}</td>')
                    for cell in row:
                        val_str = html.escape(str(cell))
                        is_num = bool(re.match(r"^-?\d+(?:[.,]\d+)?\s*€?$", val_str.strip()))
                        align_cls = "text-right font-mono" if is_num else "text-left"
                        html_parts.append(f'<td class="py-1.5 px-3 text-slate-700 whitespace-nowrap border-r border-slate-100 {align_cls}">{val_str}</td>')
                    html_parts.append('</tr>')
                html_parts.append('</tbody>')
            else:
                html_parts.append('<tbody><tr><td class="p-8 text-center text-slate-400 italic">Il foglio di calcolo è vuoto.</td></tr></tbody>')

            html_parts.append('</table></div></div>')

        if not sheets_data:
            html_parts.append('<div class="p-8 text-center text-slate-400 italic">Nessun dato o foglio trovato nel file.</div>')

        return {
            "success": True,
            "format": "excel",
            "filename": filename,
            "title": clean_title,
            "sheets": sheets_data,
            "html_content": "\n".join(html_parts),
            "error": None
        }

    # B. DOCUMENTI WORD (.docx, .doc)
    elif is_docx:
        paragraphs_html = []
        try:
            doc = docx.Document(io.BytesIO(file_bytes))
            for p in doc.paragraphs:
                p_text = p.text.strip()
                if not p_text:
                    continue
                style_name = (p.style.name if p.style else "").lower()
                safe_t = html.escape(p_text)
                if "heading 1" in style_name or "title" in style_name:
                    paragraphs_html.append(f'<h1 class="text-xl font-bold text-slate-900 mt-5 mb-2 pb-1 border-b border-slate-200">{safe_t}</h1>')
                elif "heading 2" in style_name:
                    paragraphs_html.append(f'<h2 class="text-lg font-bold text-slate-800 mt-4 mb-2">{safe_t}</h2>')
                elif "heading 3" in style_name:
                    paragraphs_html.append(f'<h3 class="text-sm font-bold text-slate-800 mt-3 mb-1">{safe_t}</h3>')
                else:
                    paragraphs_html.append(f'<p class="text-slate-700 text-sm leading-relaxed mb-2.5">{safe_t}</p>')

            for table in doc.tables:
                table_html = ['<div class="overflow-auto my-4 rounded-xl border border-slate-200 shadow-2xs bg-white"><table class="w-full text-xs text-left border-collapse min-w-full">']
                for r_idx, row in enumerate(table.rows):
                    row_cells = [html.escape(c.text.strip()) for c in row.cells]
                    if r_idx == 0:
                        table_html.append('<thead class="bg-slate-100 border-b border-slate-200"><tr>')
                        for c in row_cells:
                            table_html.append(f'<th class="py-2 px-3 font-bold text-slate-800 border-r border-slate-200">{c}</th>')
                        table_html.append('</tr></thead><tbody class="divide-y divide-slate-100">')
                    else:
                        table_html.append('<tr class="odd:bg-white even:bg-slate-50/50 hover:bg-blue-50/30">')
                        for c in row_cells:
                            table_html.append(f'<td class="py-1.5 px-3 text-slate-700 border-r border-slate-100">{c}</td>')
                        table_html.append('</tr>')
                if len(table.rows) > 0:
                    table_html.append('</tbody>')
                table_html.append('</table></div>')
                paragraphs_html.append("\n".join(table_html))

        except Exception as e:
            logger.warning(f"Errore rendering docx {filename}: {e}")
            raw_text = extract_text_from_office_file(file_bytes, filename)
            if raw_text:
                for line in raw_text.splitlines():
                    l_str = line.strip()
                    if l_str:
                        paragraphs_html.append(f'<p class="text-slate-700 text-sm leading-relaxed mb-2">{html.escape(l_str)}</p>')

        word_html = f"""
        <div class="max-w-3xl mx-auto bg-white p-6 sm:p-8 rounded-xl border border-slate-200 shadow-2xs space-y-2 font-sans overflow-auto max-h-[68vh]">
            <div class="flex items-center gap-3 border-b border-slate-200 pb-3 mb-4">
                <div class="w-9 h-9 rounded-lg bg-blue-100 text-blue-700 flex items-center justify-center font-bold text-base">
                    <i class="fa-solid fa-file-word"></i>
                </div>
                <div>
                    <h2 class="text-sm font-bold text-slate-900">{html.escape(filename)}</h2>
                    <p class="text-[11px] text-slate-500">Documento di testo Word</p>
                </div>
            </div>
            {"".join(paragraphs_html) if paragraphs_html else '<p class="text-slate-400 italic text-sm">Nessun testo estraibile trovato nel documento.</p>'}
        </div>
        """
        return {
            "success": True,
            "format": "word",
            "filename": filename,
            "title": clean_title,
            "sheets": [],
            "html_content": word_html,
            "error": None
        }

    # C. ARCHIVI COMPRESSI ZIP (.zip)
    elif is_zip:
        zip_entries = []
        total_uncompressed_size = 0
        try:
            with zipfile.ZipFile(io.BytesIO(file_bytes), "r") as zf:
                for info in zf.infolist():
                    if info.is_dir() or "__MACOSX" in info.filename or Path(info.filename).name.startswith("."):
                        continue
                    fname = Path(info.filename).name
                    fext = Path(fname).suffix.lstrip(".").lower()
                    size_kb = max(1, round(info.file_size / 1024))
                    total_uncompressed_size += info.file_size

                    if fext == "pdf":
                        icon = "fa-solid fa-file-pdf text-red-500"
                        bg_icon = "bg-red-50"
                    elif fext in ["xlsx", "xls", "csv"]:
                        icon = "fa-solid fa-file-excel text-emerald-600"
                        bg_icon = "bg-emerald-50"
                    elif fext in ["docx", "doc"]:
                        icon = "fa-solid fa-file-word text-blue-600"
                        bg_icon = "bg-blue-50"
                    elif fext in ["jpg", "jpeg", "png", "webp", "gif"]:
                        icon = "fa-solid fa-file-image text-purple-600"
                        bg_icon = "bg-purple-50"
                    elif fext in ["mp3", "wav", "m4a"]:
                        icon = "fa-solid fa-file-audio text-amber-500"
                        bg_icon = "bg-amber-50"
                    else:
                        icon = "fa-regular fa-file-lines text-slate-500"
                        bg_icon = "bg-slate-100"

                    zip_entries.append({
                        "name": fname,
                        "path": info.filename,
                        "size_bytes": info.file_size,
                        "size_kb": size_kb,
                        "ext": fext,
                        "icon": icon,
                        "bg_icon": bg_icon
                    })
        except Exception as z_err:
            logger.error(f"Errore lettura archivio zip {filename}: {z_err}")

        total_mb = f"{total_uncompressed_size / (1024 * 1024):.1f} MB" if total_uncompressed_size > 1024 * 1024 else f"{max(1, round(total_uncompressed_size / 1024))} KB"

        entries_html = []
        for e in zip_entries:
            entries_html.append(f"""
            <div class="flex items-center justify-between p-2.5 rounded-xl bg-slate-50 hover:bg-slate-100/90 border border-slate-200/80 transition">
                <div class="flex items-center gap-2.5 min-w-0">
                    <div class="w-8 h-8 rounded-lg {e['bg_icon']} flex items-center justify-center shrink-0">
                        <i class="{e['icon']} text-sm"></i>
                    </div>
                    <div class="min-w-0">
                        <p class="text-xs font-semibold text-slate-800 truncate" title="{html.escape(e['path'])}">{html.escape(e['name'])}</p>
                        <p class="text-[10px] text-slate-400 font-mono">{e['ext'].upper()} • {e['size_kb']} KB</p>
                    </div>
                </div>
            </div>
            """)

        zip_html = f"""
        <div class="max-w-3xl mx-auto bg-white p-5 sm:p-7 rounded-xl border border-slate-200 shadow-2xs space-y-4 font-sans overflow-auto max-h-[68vh]">
            <!-- Header Archivio -->
            <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-4 border-b border-slate-200">
                <div class="flex items-center gap-3">
                    <div class="w-10 h-10 rounded-xl bg-amber-100 text-amber-700 flex items-center justify-center font-bold text-lg shadow-2xs">
                        <i class="fa-solid fa-file-zipper"></i>
                    </div>
                    <div>
                        <h2 class="text-sm font-bold text-slate-900">{html.escape(filename)}</h2>
                        <p class="text-[11px] text-slate-500">Archivio compresso ZIP • <strong>{len(zip_entries)} file</strong> ({total_mb})</p>
                    </div>
                </div>
                <!-- Pulsante Azione Decomprimi ed Estrai -->
                <button type="button" onclick="unzipCurrentModalArchive()" class="px-4 py-2 bg-[#075E54] hover:bg-[#128C7E] text-white rounded-xl text-xs font-bold flex items-center justify-center gap-2 shadow-sm transition active:scale-95 cursor-pointer shrink-0">
                    <i class="fa-solid fa-bolt text-amber-300"></i>
                    <span>Estrai tutti i file nel Caveau</span>
                </button>
            </div>

            <!-- Banner Informativo -->
            <div class="p-3 bg-amber-50/70 border border-amber-200/80 rounded-xl flex items-start gap-2.5 text-xs text-amber-900">
                <i class="fa-solid fa-circle-info text-amber-600 mt-0.5 shrink-0"></i>
                <div class="leading-relaxed">
                    Puoi estrarre automaticamente tutti i file contenuti in questo archivio: l'AI analizzerà ed indicizzerà ciascun documento, bolletta o immagine singolarmente.
                </div>
            </div>

            <!-- Elenco File Contenuti -->
            <div class="space-y-2">
                <h4 class="text-xs font-bold text-slate-700 uppercase tracking-wider">File contenuti nell'archivio ({len(zip_entries)})</h4>
                <div class="grid grid-cols-1 sm:grid-cols-2 gap-2 max-h-[42vh] overflow-y-auto pr-1">
                    {"".join(entries_html) if entries_html else '<p class="text-slate-400 italic text-xs col-span-2 p-4 text-center">Nessun file trovato nell\'archivio.</p>'}
                </div>
            </div>
        </div>
        """

        return {
            "success": True,
            "format": "zip",
            "filename": filename,
            "title": clean_title,
            "file_count": len(zip_entries),
            "files": zip_entries,
            "sheets": [],
            "html_content": zip_html,
            "error": None
        }

    # D. DOCUMENTI PDF (.pdf)
    elif is_pdf:
        pages_html = []
        num_pages = 0
        try:
            reader = pypdf.PdfReader(io.BytesIO(file_bytes))
            num_pages = len(reader.pages)
            for p_idx, page in enumerate(reader.pages):
                try:
                    p_text = page.extract_text() or ""
                except Exception:
                    p_text = ""
                p_text_clean = p_text.strip()
                if p_text_clean:
                    safe_p_text = html.escape(p_text_clean)
                    pages_html.append(f"""
                    <div class="bg-white p-4 sm:p-5 rounded-xs border border-[#E3DDD1] shadow-xs mb-3">
                        <div class="flex items-center justify-between border-b border-[#E3DDD1] pb-2 mb-3">
                            <span class="text-[10px] font-mono-code font-bold uppercase tracking-wider text-[#3C5A48] bg-[#F8F5EE] px-2 py-0.5 rounded-xs border border-[#E3DDD1]">
                                <i class="fa-regular fa-file-lines mr-1"></i> Pagina {p_idx + 1} di {num_pages}
                            </span>
                        </div>
                        <div class="font-mono-code text-xs text-[#222220] whitespace-pre-wrap leading-relaxed select-text">
                            {safe_p_text}
                        </div>
                    </div>
                    """)
                else:
                    pages_html.append(f"""
                    <div class="bg-white p-4 rounded-xs border border-[#E3DDD1] shadow-xs mb-3 text-center text-[#7A7568] font-mono-code text-xs">
                        <span class="text-[10px] uppercase font-bold text-[#3C5A48]">Pagina {p_idx + 1} di {num_pages}</span>
                        <p class="mt-1 italic">(Pagina grafica o scansione)</p>
                    </div>
                    """)
        except Exception as e:
            logger.warning(f"Errore estrazione PDF {filename}: {e}")
            pages_html.append(f'<div class="p-4 bg-amber-50 border border-amber-200 rounded-xs text-xs font-mono-code text-amber-800">Impossibile estrarre testo dal PDF: {html.escape(str(e))}</div>')

        pdf_view_html = f"""
        <div class="max-w-3xl mx-auto space-y-3 font-mono-code overflow-auto max-h-[68vh] p-2">
            <div class="flex items-center justify-between border-b border-[#E3DDD1] pb-3 mb-2 bg-[#F8F5EE] p-3 rounded-xs border border-[#E3DDD1]">
                <div class="flex items-center gap-3">
                    <div class="w-8 h-8 rounded-xs bg-[#C84B31] text-white flex items-center justify-center font-bold text-sm shadow-xs">
                        <i class="fa-solid fa-file-pdf"></i>
                    </div>
                    <div>
                        <h2 class="text-xs font-bold text-[#222220] uppercase font-space">{html.escape(filename)}</h2>
                        <p class="text-[10px] text-[#7A7568]">{num_pages} pagin{'a' if num_pages == 1 else 'e'} • Anteprima strutturata</p>
                    </div>
                </div>
                <div class="text-[10px] text-[#3C5A48] bg-white border border-[#E3DDD1] px-2.5 py-1 rounded-xs font-bold">
                    <span>PDF PROTETTO</span>
                </div>
            </div>
            {"".join(pages_html) if pages_html else '<p class="text-[#7A7568] italic text-xs p-4 text-center">Nessuna pagina o contenuto testuale estratto.</p>'}
        </div>
        """
        return {
            "success": True,
            "format": "pdf",
            "filename": filename,
            "title": clean_title,
            "page_count": num_pages,
            "sheets": [],
            "html_content": pdf_view_html,
            "error": None
        }

    # E. FILE DI TESTO GENERICO (.txt, .md, .json, .xml)
    else:
        raw_text = extract_text_from_office_file(file_bytes, filename)
        safe_text = html.escape(raw_text) if raw_text else "File vuoto o formato non testuale."
        text_html = f"""
        <div class="bg-white p-4 rounded-xl border border-slate-200 shadow-2xs overflow-auto max-h-[68vh]">
            <div class="flex items-center gap-2 pb-2 mb-2 border-b border-slate-100 text-slate-600 text-xs font-semibold">
                <i class="fa-regular fa-file-code"></i> <span>{html.escape(filename)}</span>
            </div>
            <pre class="font-mono text-xs text-slate-800 whitespace-pre-wrap leading-relaxed">{safe_text}</pre>
        </div>
        """
        return {
            "success": True,
            "format": "text",
            "filename": filename,
            "title": clean_title,
            "sheets": [],
            "html_content": text_html,
            "error": None
        }


