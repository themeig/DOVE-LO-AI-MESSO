"""
Package app.services.archive
Architettura modulare per la gestione di file Office, ispezione anti-allucinazione e archivi ZIP.
"""
from app.services.archive.inspectors import (
    _format_cell_value,
    extract_text_from_office_file,
    _filter_rows_by_query,
    inspect_document_content,
    render_office_file_to_html,
)
from app.services.archive.metadata import fast_extract_document_metadata
from app.services.archive.zip_ops import (
    create_zip_from_documents,
    unzip_document_to_vault,
)
from app.services.ai_service import get_ai_service

__all__ = [
    "_format_cell_value",
    "extract_text_from_office_file",
    "_filter_rows_by_query",
    "inspect_document_content",
    "render_office_file_to_html",
    "fast_extract_document_metadata",
    "create_zip_from_documents",
    "unzip_document_to_vault",
    "get_ai_service",
]
