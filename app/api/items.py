from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.models.database import get_db, PhysicalItem

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
