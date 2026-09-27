import io
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.models.database import init_db
from app.services.document_service import detect_media_type, save_uploaded_file, read_decrypted_file
from app.services.archive_service import render_office_file_to_html

client = TestClient(app)

def setup_module():
    init_db()

def test_detect_media_type_magic_bytes_and_ext():
    # PDF
    assert detect_media_type(b"%PDF-1.5 test", "document.pdf") == "application/pdf"
    assert detect_media_type(b"%PDF-1.4 test", "random_uuid.bin") == "application/pdf"

    # JPEG
    assert detect_media_type(b"\xff\xd8\xff\xe0 test", "photo.jpg") == "image/jpeg"
    assert detect_media_type(b"\xff\xd8\xff\xe1 test", "file.bin") == "image/jpeg"

    # PNG
    assert detect_media_type(b"\x89PNG\r\n\x1a\n test", "photo.png") == "image/png"
    assert detect_media_type(b"\x89PNG\r\n\x1a\n test", "unknown.bin") == "image/png"

    # WEBP
    assert detect_media_type(b"RIFF\x00\x00\x00\x00WEBPtest", "img.webp") == "image/webp"

    # Excel / Word / Text / ZIP
    assert "spreadsheetml" in detect_media_type(b"fake", "foglio.xlsx")
    assert "wordprocessingml" in detect_media_type(b"fake", "lettera.docx")
    assert "text/plain" in detect_media_type(b"hello", "note.txt")
    assert "application/zip" in detect_media_type(b"PK\x03\x04test", "archivio.zip")

def test_preview_content_pdf_html():
    # Test valid PDF generation for preview-content
    from app.services.document_service import compile_images_to_pdf
    from PIL import Image

    im = Image.new("RGB", (100, 100), color="blue")
    buf = io.BytesIO()
    im.save(buf, format="JPEG")
    pdf_bytes = compile_images_to_pdf([buf.getvalue()])

    res = render_office_file_to_html(pdf_bytes, "documento_fiscale.pdf")
    assert res["success"] is True
    assert res["format"] == "pdf"
    assert res["page_count"] == 1
    assert "PDF PROTETTO" in res["html_content"]

def test_get_document_file_endpoint_pdf():
    fake_pdf = io.BytesIO(b"%PDF-1.4 test content")
    upload_res = client.post(
        "/api/documents/upload",
        files={"file": ("fattura_test.pdf", fake_pdf, "application/pdf")}
    )
    assert upload_res.status_code == 201
    doc_id = upload_res.json()["document_id"]

    # Test GET /api/documents/{id}/file
    file_res = client.get(f"/api/documents/{doc_id}/file")
    assert file_res.status_code == 200
    assert file_res.headers["content-type"] == "application/pdf"
    assert file_res.headers.get("accept-ranges") == "bytes"
    assert b"%PDF-1.4" in file_res.content

    # Test GET /api/documents/preview-content with document_id
    prev_res = client.get(f"/api/documents/preview-content?document_id={doc_id}")
    assert prev_res.status_code == 200
    prev_data = prev_res.json()
    assert prev_data["success"] is True
    assert prev_data["format"] == "pdf"
    assert "html_content" in prev_data

def test_get_document_preview_content_with_file_url():
    fake_pdf = io.BytesIO(b"%PDF-1.4 test url resolution")
    upload_res = client.post(
        "/api/documents/upload",
        files={"file": ("ricevuta_url.pdf", fake_pdf, "application/pdf")}
    )
    assert upload_res.status_code == 201
    doc_id = upload_res.json()["document_id"]
    file_url = upload_res.json().get("file_url") or f"/api/documents/{doc_id}/file"

    prev_res = client.get(f"/api/documents/preview-content?file_url={file_url}")
    assert prev_res.status_code == 200
    data = prev_res.json()
    assert data["success"] is True
    assert data["format"] == "pdf"
