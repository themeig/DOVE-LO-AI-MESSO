from app.services.document_service import save_uploaded_file, get_safe_filename
from pathlib import Path

def test_save_uploaded_file(tmp_path):
    safe_name = get_safe_filename("bolletta luce.pdf")
    assert safe_name.endswith(".pdf")
    assert " " not in safe_name
    
    saved_path = save_uploaded_file(b"test file content", "bolletta.pdf", target_dir=tmp_path)
    assert Path(saved_path).exists()
    assert Path(saved_path).read_bytes() == b"test file content"
