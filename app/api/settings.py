import logging
from typing import Dict, Any, List
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.database import get_db, get_app_setting, set_app_setting

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings", tags=["settings"])

AVAILABLE_MODELS = [
    {
        "id": "google/gemini-2.5-flash-lite",
        "name": "Google Gemini 2.5 Flash Lite",
        "tag": "⚡ Consigliato",
        "tier": "paid",
        "is_free": False,
        "cost_info": "~0,0001 € / msg (.10 / 1M in, .40 / 1M out)",
        "features": "Visione multimodale ad alta precisione + Tool Calling ultra-rapido."
    },
    {
        "id": "nex-agi/nex-n2.5-pro:free",
        "name": "Nex-AGI Nex-N2.5-Pro (Free)",
        "tag": "🆓 100% Gratuito",
        "tier": "free",
        "is_free": True,
        "cost_info": "0,00 € (Nessun addebito)",
        "features": "Modello open gratuito con supporto a visione e tool calling."
    }
]

class ModelUpdateRequest(BaseModel):
    model_id: str

@router.get("/ai-model")
def get_ai_model_setting(db: Session = Depends(get_db)) -> Dict[str, Any]:
    default_model = get_settings().OPENROUTER_MODEL
    current_model = get_app_setting(db, "ai_model", default=default_model)
    
    active_info = next((m for m in AVAILABLE_MODELS if m["id"] == current_model), None)
    if not active_info:
        active_info = {
            "id": current_model,
            "name": current_model,
            "tag": "Personalizzato",
            "tier": "free" if ":free" in current_model else "paid",
            "is_free": ":free" in current_model,
            "cost_info": "0,00 €" if ":free" in current_model else "Pay-as-you-go",
            "features": "Modello configurato manualmente"
        }
        
    return {
        "current_model": current_model,
        "current_info": active_info,
        "is_free": active_info["is_free"],
        "available_models": AVAILABLE_MODELS
    }

@router.post("/ai-model")
def update_ai_model_setting(payload: ModelUpdateRequest, db: Session = Depends(get_db)) -> Dict[str, Any]:
    valid_ids = [m["id"] for m in AVAILABLE_MODELS]
    if payload.model_id not in valid_ids and not payload.model_id.endswith(":free"):
        raise HTTPException(status_code=400, detail="Modello non supportato")

    set_app_setting(db, "ai_model", payload.model_id)
    logger.info(f"Modello AI aggiornato a: {payload.model_id}")
    
    return get_ai_model_setting(db)
