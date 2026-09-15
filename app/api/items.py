from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status
from sqlalchemy.orm import Session
from app.models.database import get_db, PhysicalItem
from app.services.document_service import save_uploaded_file

router = APIRouter(prefix="/api/items", tags=["items"])

@router.post("", status_code=status.HTTP_201_CREATED)
def create_physical_item(payload: dict, db: Session = Depends(get_db)):
    item_name = (payload.get("item_name") or "").strip()
    primary_location = (payload.get("primary_location") or "").strip()
    detailed_location = (payload.get("detailed_location") or "").strip() or None
    category = (payload.get("category") or "").strip() or "generico"
    thread_id = payload.get("thread_id", "general")

    if not item_name or not primary_location:
        raise HTTPException(status_code=400, detail="item_name e primary_location sono obbligatori")

    item = PhysicalItem(
        thread_id=thread_id,
        item_name=item_name,
        primary_location=primary_location,
        detailed_location=detailed_location,
        category=category
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return {
        "id": item.id,
        "item_id": item.id,
        "item_name": item.item_name,
        "primary_location": item.primary_location,
        "detailed_location": item.detailed_location,
        "category": item.category,
        "has_photo": False
    }

@router.delete("/{item_id}")
def delete_physical_item(item_id: int, db: Session = Depends(get_db)):
    item = db.query(PhysicalItem).filter(PhysicalItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Oggetto non trovato")

    name = item.item_name
    db.delete(item)
    db.commit()
    return {
        "success": True,
        "message": f"Oggetto '{name}' eliminato con successo.",
        "item_id": item_id
    }

@router.post("/{item_id}/photo")
async def upload_item_photo(
    item_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    item = db.query(PhysicalItem).filter(PhysicalItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Oggetto non trovato")

    contents = await file.read()
    saved_path = save_uploaded_file(contents, file.filename or "photo.jpg")
    item.image_path = saved_path
    db.commit()
    db.refresh(item)

    fn = Path(saved_path).name
    return {
        "success": True,
        "item_id": item.id,
        "item_name": item.item_name,
        "image_path": saved_path,
        "image_url": f"/api/files/{fn}",
        "message": f"Foto della posizione di '{item.item_name}' salvata con successo."
    }

@router.post("/with-photo", status_code=status.HTTP_201_CREATED)
async def create_item_with_photo(
    item_name: str = Form(...),
    primary_location: str = Form(...),
    detailed_location: Optional[str] = Form(None),
    category: Optional[str] = Form(None),
    thread_id: str = Form("general"),
    file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db)
):
    saved_path = None
    if file:
        contents = await file.read()
        saved_path = save_uploaded_file(contents, file.filename or "photo.jpg")

    item = PhysicalItem(
        thread_id=thread_id,
        item_name=item_name.strip(),
        primary_location=primary_location.strip(),
        detailed_location=detailed_location.strip() if detailed_location else None,
        category=category.strip() if category else "generico",
        image_path=saved_path
    )
    db.add(item)
    db.commit()
    db.refresh(item)

    fn = Path(saved_path).name if saved_path else None
    return {
        "success": True,
        "item_id": item.id,
        "item_name": item.item_name,
        "primary_location": item.primary_location,
        "detailed_location": item.detailed_location,
        "image_url": f"/api/files/{fn}" if fn else None,
        "message": f"Oggetto '{item.item_name}' memorizzato con successo."
    }

@router.post("/{item_id}/link-document/{document_id}")
def link_document_to_item_by_ids(item_id: int, document_id: int, db: Session = Depends(get_db)):
    from app.models.database import Document
    item = db.query(PhysicalItem).filter(PhysicalItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Oggetto non trovato")
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Documento non trovato")

    item.document_id = doc.id
    item.image_path = doc.file_path
    doc.physical_item_id = item.id
    db.commit()
    db.refresh(item)

    fn = Path(item.image_path).name if item.image_path else None
    return {
        "success": True,
        "item_id": item.id,
        "item_name": item.item_name,
        "document_id": doc.id,
        "document_title": doc.title,
        "has_photo": True,
        "image_url": f"/api/files/{fn}" if fn else None,
        "item": {
            "id": item.id,
            "item_name": item.item_name,
            "primary_location": item.primary_location,
            "detailed_location": item.detailed_location,
            "document_id": doc.id,
            "has_photo": True,
            "image_url": f"/api/files/{fn}" if fn else None
        },
        "message": f"Documento '{doc.title}' collegato con successo all'oggetto '{item.item_name}'."
    }

@router.post("/link")
def link_document_to_item_payload(payload: dict, db: Session = Depends(get_db)):
    from app.models.database import Document
    from app.services.search_service import search_vault_items
    doc_id = payload.get("document_id")
    item_id = payload.get("item_id")
    item_name = (payload.get("item_name") or "").strip()
    thread_id = payload.get("thread_id", "general")

    if not doc_id:
        raise HTTPException(status_code=400, detail="document_id è obbligatorio")

    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Documento non trovato")

    item = None
    if item_id:
        item = db.query(PhysicalItem).filter(PhysicalItem.id == item_id).first()
    elif item_name:
        item = db.query(PhysicalItem).filter(PhysicalItem.item_name.ilike(item_name)).first()
        if not item:
            s_items = search_vault_items(db, item_name, thread_id=thread_id)
            if s_items:
                item = db.query(PhysicalItem).filter(PhysicalItem.id == s_items[0]["item_id"]).first()

    if not item:
        # Se non esiste, crea la posizione per l'oggetto
        item = PhysicalItem(
            thread_id=thread_id,
            item_name=item_name or "Oggetto",
            primary_location="Posizione da foto",
            category="generico",
            document_id=doc.id,
            image_path=doc.file_path
        )
        db.add(item)
    else:
        item.document_id = doc.id
        item.image_path = doc.file_path

    doc.physical_item_id = item.id
    db.commit()
    db.refresh(item)

    fn = Path(item.image_path).name if item.image_path else None
    return {
        "success": True,
        "item_id": item.id,
        "item_name": item.item_name,
        "document_id": doc.id,
        "document_title": doc.title,
        "image_url": f"/api/files/{fn}" if fn else None,
        "message": f"Documento '{doc.title}' collegato con successo all'oggetto '{item.item_name}'."
    }
