from typing import Literal, Optional, List
from pydantic import BaseModel, Field

class ExtractedDocument(BaseModel):
    doc_type: str = Field(default="generico", description="Tipo documento")
    issuer: str = Field(default="Sconosciuto", description="Ente o fornitore")
    amount: Optional[float] = Field(default=None, description="Importo in euro")
    due_date: Optional[str] = Field(default=None, description="Data scadenza YYYY-MM-DD")
    summary: str = Field(default="", description="Spiegazione semplice del documento")
    tags: List[str] = Field(default_factory=list)

class MessageIntent(BaseModel):
    intent: Literal["STORE_LOCATION", "QUERY_LOCATION", "QUERY_DEADLINES", "GENERAL"]
    item_name: Optional[str] = None
    primary_location: Optional[str] = None
    detailed_location: Optional[str] = None
    query_text: Optional[str] = None

class ChatRequest(BaseModel):
    message: str

class ChatResponse(BaseModel):
    reply: str
    action: str = "REPLY"
    data: Optional[dict] = None
    documents: Optional[List[dict]] = None

class DocumentStatusUpdate(BaseModel):
    status: Literal["da_pagare", "quietanzato", "archiviato"]

class RecordItem(BaseModel):
    id: int
    type: str  # 'document' or 'physical_item'
    title: str
    source: str
    amount: Optional[float] = None
    due_date: Optional[str] = None
    status: str
    location_or_notes: Optional[str] = None
    badge_color: str
    file_url: Optional[str] = None
    file_type: Optional[str] = None

class DashboardKPI(BaseModel):
    total_upcoming_amount: float
    pending_deadlines_count: int
    total_documents_count: int
    total_items_count: int

class DashboardResponse(BaseModel):
    kpi: DashboardKPI
    records: List[RecordItem]
