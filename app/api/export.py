import io
import json
import zipfile
import logging
from datetime import datetime
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.models.database import get_db, Document, PhysicalItem, WatchedFolder
from app.services.document_service import read_decrypted_file

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/export", tags=["export"])


def _build_metadata(db):
    """Costruisce i metadati completi del caveau."""
    documents = db.query(Document).order_by(Document.created_at.desc()).all()
    items = db.query(PhysicalItem).order_by(PhysicalItem.updated_at.desc()).all()
    folders = db.query(WatchedFolder).all()

    docs_data = [
        {
            "id": d.id, "title": d.title, "doc_type": d.doc_type, "issuer": d.issuer,
            "amount": d.amount, "due_date": d.due_date.isoformat() if d.due_date else None,
            "status": d.status, "summary": d.summary, "thread_id": d.thread_id,
            "file_type": d.file_type, "is_local_file": bool(d.is_local_file),
            "original_path": d.original_path,
            "created_at": d.created_at.isoformat() if d.created_at else None,
        }
        for d in documents
    ]
    items_data = [
        {
            "id": i.id, "item_name": i.item_name, "primary_location": i.primary_location,
            "detailed_location": i.detailed_location, "category": i.category,
            "thread_id": i.thread_id, "document_id": i.document_id,
            "updated_at": i.updated_at.isoformat() if i.updated_at else None,
        }
        for i in items
    ]
    folders_data = [
        {
            "id": f.id, "name": f.name, "path": f.path, "is_active": f.is_active,
            "auto_scan": f.auto_scan, "file_count": f.file_count,
            "last_scanned_at": f.last_scanned_at.isoformat() if f.last_scanned_at else None,
        }
        for f in folders
    ]
    return {
        "export_date": datetime.now().isoformat(),
        "version": "1.0",
        "app": "Dove lo AI messo",
        "stats": {
            "total_documents": len(docs_data),
            "total_physical_items": len(items_data),
            "total_watched_folders": len(folders_data),
        },
        "documents": docs_data,
        "physical_items": items_data,
        "watched_folders": folders_data,
    }


@router.get("/vault")
def export_vault_zip(db: Session = Depends(get_db)):
    """Scarica il caveau completo come archivio ZIP (file decifrati + metadata.json)."""
    try:
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            metadata = _build_metadata(db)
            zf.writestr("metadata.json", json.dumps(metadata, ensure_ascii=False, indent=2))

            copied_files = set()
            for doc in db.query(Document).all():
                if doc.is_local_file or not doc.file_path:
                    continue
                file_path = Path(doc.file_path)
                zip_name = f"documents/{file_path.name}"
                if zip_name in copied_files:
                    continue
                try:
                    decrypted_bytes = read_decrypted_file(file_path)
                    zf.writestr(zip_name, decrypted_bytes)
                    copied_files.add(zip_name)
                except Exception as e:
                    logger.warning(f"Export: impossibile leggere {file_path}: {e}")
                    zf.writestr(f"documents/_errore_{file_path.name}.txt", f"Errore: {e}")

        zip_buffer.seek(0)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        fn = f"caveau_backup_{ts}.zip"
        return StreamingResponse(
            zip_buffer,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{fn}"'}
        )
    except Exception as e:
        logger.error(f"Errore export caveau: {e}")
        raise HTTPException(status_code=500, detail=f"Errore esportazione: {str(e)}")


@router.get("/metadata")
def export_metadata_json(db: Session = Depends(get_db)):
    """Esporta solo i metadati del caveau in formato JSON."""
    try:
        metadata = _build_metadata(db)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        fn = f"metadata_{ts}.json"
        return StreamingResponse(
            io.BytesIO(json.dumps(metadata, ensure_ascii=False, indent=2).encode("utf-8")),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{fn}"'}
        )
    except Exception as e:
        logger.error(f"Errore export metadata: {e}")
        raise HTTPException(status_code=500, detail=f"Errore esportazione: {str(e)}")
