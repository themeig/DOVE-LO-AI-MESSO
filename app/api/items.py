from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status
from sqlalchemy.orm import Session
from app.models.database import get_db, PhysicalItem
from app.services.document_service import save_uploaded_file

router = APIRouter(prefix="/api/items", tags=["items"])

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
