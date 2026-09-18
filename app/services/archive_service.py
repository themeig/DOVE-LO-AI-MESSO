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
import pypdf
import xlrd

from app.models.database import Document
from app.models.schemas import ExtractedDocument
from app.services.document_service import save_uploaded_file, read_decrypted_file
from app.services.ai_service import get_ai_service

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
    is_zip = fn.endswith(".zip") or ("zip" in fn and not (is_docx or is_xlsx))

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

    # D. FILE DI TESTO GENERICO (.txt, .md, .json, .xml)
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
        if not doc:
            logger.warning(f"Nessun documento ZIP trovato con ID {document_id}")
            return []
    elif document_title:
        term = document_title.strip().lower()
        all_zips = db.query(Document).filter(
            or_(Document.file_type == "zip", Document.doc_type == "archivio_zip")
        ).all()
        doc = next((d for d in all_zips if term in (d.title or "").lower() or term in (d.summary or "").lower()), None)
        if not doc:
            logger.warning(f"Nessun documento ZIP trovato con titolo '{document_title}'")
            return []

    if not doc:
        # Cerca l'ultimo zip caricato solo se nessun parametro specifico è stato fornito
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
