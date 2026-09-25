import io
import json
import zipfile
import logging
from datetime import datetime
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, File, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.models.database import get_db, Document, PhysicalItem, WatchedFolder
from app.services.document_service import read_decrypted_file, determine_document_status

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


@router.post("/import")
async def import_vault_zip(
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """
    Importa e ripristina un archivio ZIP nel caveau.
    Se contiene metadata.json, ripristina la struttura completa (documenti, scadenze, oggetti).
    Se è uno ZIP generico di file, estrae e cataloga ciascun file con l'AI.
    """
    from datetime import timezone
    from app.services.document_service import save_uploaded_file
    from app.services.archive_service import fast_extract_document_metadata

    contents = await file.read()
    if not contents or not zipfile.is_zipfile(io.BytesIO(contents)):
        raise HTTPException(status_code=400, detail="Il file fornito non è un archivio ZIP valido.")

    restored_docs = 0
    restored_items = 0
    restored_folders = 0

    try:
        with zipfile.ZipFile(io.BytesIO(contents), "r") as zf:
            namelist = zf.namelist()

            if "metadata.json" in namelist:
                # 1. Archivio di backup completo di Dove lo AI messo
                try:
                    meta = json.loads(zf.read("metadata.json").decode("utf-8"))
                except Exception as e:
                    raise HTTPException(status_code=400, detail=f"Errore lettura metadata.json: {str(e)}")

                id_map = {}

                for d in meta.get("documents", []):
                    # Ricerca del file corrispondente nella cartella documents/ dello ZIP
                    matched_entry = None
                    orig_name = Path(d.get("original_path") or "").name
                    for candidate in namelist:
                        if candidate.startswith("documents/") and not candidate.endswith("/"):
                            cand_name = Path(candidate).name
                            if orig_name and cand_name == orig_name:
                                matched_entry = candidate
                                break
                    if not matched_entry:
                        for candidate in namelist:
                            if candidate.startswith("documents/") and not candidate.endswith("/") and not candidate.startswith("documents/_errore"):
                                cand_name = Path(candidate).name
                                if d.get("file_type") and cand_name.endswith(f".{d['file_type']}"):
                                    matched_entry = candidate
                                    break

                    saved_path = ""
                    if matched_entry:
                        try:
                            file_bytes = zf.read(matched_entry)
                            fname = Path(matched_entry).name
                            saved_path = save_uploaded_file(file_bytes, fname)
                        except Exception as fe:
                            logger.warning(f"Errore salvataggio file {matched_entry}: {fe}")

                    due_date_obj = None
                    if d.get("due_date"):
                        try:
                            due_date_obj = datetime.strptime(d["due_date"][:10], "%Y-%m-%d").date()
                        except Exception:
                            due_date_obj = None

                    created_at_obj = datetime.now(timezone.utc)
                    if d.get("created_at"):
                        try:
                            created_at_obj = datetime.fromisoformat(d["created_at"])
                        except Exception:
                            pass

                    # Verifica duplicato
                    existing_doc = db.query(Document).filter(
                        Document.title == d.get("title"),
                        Document.amount == d.get("amount"),
                        Document.due_date == due_date_obj
                    ).first()

                    if existing_doc:
                        id_map[d.get("id")] = existing_doc.id
                        restored_docs += 1
                    else:
                        new_doc = Document(
                            thread_id=d.get("thread_id") or "general",
                            title=d.get("title") or "Documento Ripristinato",
                            file_path=saved_path or "storage/uploads/placeholder.bin",
                            file_type=d.get("file_type") or "pdf",
                            doc_type=d.get("doc_type") or "generico",
                            issuer=d.get("issuer"),
                            amount=d.get("amount"),
                            due_date=due_date_obj,
                            status=d.get("status") or "archiviato",
                            summary=d.get("summary") or "",
                            is_local_file=bool(d.get("is_local_file", False)),
                            original_path=d.get("original_path"),
                            category=d.get("category"),
                            category_label=d.get("category_label"),
                            category_icon=d.get("category_icon"),
                            created_at=created_at_obj
                        )
                        db.add(new_doc)
                        db.flush()
                        id_map[d.get("id")] = new_doc.id
                        restored_docs += 1

                for i in meta.get("physical_items", []):
                    existing_item = db.query(PhysicalItem).filter(
                        PhysicalItem.item_name == i.get("item_name"),
                        PhysicalItem.primary_location == i.get("primary_location")
                    ).first()

                    if not existing_item:
                        doc_id_ref = id_map.get(i.get("document_id")) if i.get("document_id") else None
                        new_item = PhysicalItem(
                            item_name=i.get("item_name") or "Oggetto",
                            primary_location=i.get("primary_location") or "Casa",
                            detailed_location=i.get("detailed_location"),
                            category=i.get("category") or "Altro",
                            notes=i.get("notes"),
                            thread_id=i.get("thread_id") or "general",
                            document_id=doc_id_ref
                        )
                        db.add(new_item)
                        restored_items += 1

                for f in meta.get("watched_folders", []):
                    if f.get("path"):
                        existing_folder = db.query(WatchedFolder).filter(WatchedFolder.path == f.get("path")).first()
                        if not existing_folder:
                            new_folder = WatchedFolder(
                                name=f.get("name") or Path(f["path"]).name,
                                path=f["path"],
                                is_active=bool(f.get("is_active", True)),
                                auto_scan=bool(f.get("auto_scan", True))
                            )
                            db.add(new_folder)
                            restored_folders += 1

                db.commit()
                return {
                    "success": True,
                    "type": "backup",
                    "message": f"Backup ripristinato con successo: {restored_docs} documenti, {restored_items} oggetti.",
                    "restored": {
                        "documents": restored_docs,
                        "physical_items": restored_items,
                        "watched_folders": restored_folders
                    }
                }

            else:
                # 2. ZIP Generico: estrazione e catalogazione immediata dei singoli file
                for info in zf.infolist():
                    if info.is_dir() or "__MACOSX" in info.filename or Path(info.filename).name.startswith("."):
                        continue
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

                    doc_status = determine_document_status(extracted, due_date_obj)

                    new_doc = Document(
                        thread_id="general",
                        title=title,
                        file_path=saved_path,
                        file_type=file_ext,
                        doc_type=extracted.doc_type,
                        issuer=extracted.issuer,
                        amount=extracted.amount,
                        due_date=due_date_obj,
                        status=doc_status,
                        summary=extracted.summary,
                        category=extracted.category,
                        category_label=extracted.category_label,
                        category_icon=extracted.category_icon,
                        created_at=datetime.now(timezone.utc)
                    )
                    db.add(new_doc)
                    restored_docs += 1

                db.commit()
                return {
                    "success": True,
                    "type": "archive",
                    "message": f"Archivio ZIP importato: {restored_docs} documenti estratti e catalogati nel caveau.",
                    "restored": {
                        "documents": restored_docs,
                        "physical_items": 0,
                        "watched_folders": 0
                    }
                }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Errore importazione ZIP: {e}")
        raise HTTPException(status_code=500, detail=f"Errore importazione archivio: {str(e)}")

