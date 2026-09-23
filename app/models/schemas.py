from typing import Literal, Optional, List
from pydantic import BaseModel, Field

class ExtractedDocument(BaseModel):
    title: Optional[str] = Field(default=None, description="Titolo sintetico descrittivo del file o documento")
    doc_type: str = Field(default="generico", description="Tipo documento")
    issuer: Optional[str] = Field(default=None, description="Ente, azienda o fornitore")
    amount: Optional[float] = Field(default=None, description="Importo in euro")
    due_date: Optional[str] = Field(default=None, description="Data scadenza YYYY-MM-DD")
    summary: str = Field(default="", description="Spiegazione semplice del documento")
    tags: List[str] = Field(default_factory=list)
    suggest_rename: bool = Field(default=False, description="True se è utile chiedere all'utente se vuole dare un nome personalizzato")
    category: Optional[str] = Field(default=None, description="Slug della sezione/categoria scelto dall'AI (es. canzoni_testi, ricette, utenze)")
    category_label: Optional[str] = Field(default=None, description="Titolo visibile della sezione creato o scelto dall'AI (es. Canzoni & Testi Musicali, Ricette & Cucina)")
    category_icon: Optional[str] = Field(default=None, description="Icona FontAwesome adatta scelta dall'AI (es. fa-music, fa-utensils, fa-graduation-cap)")
    subfolder: Optional[str] = Field(default=None, description="Sottocartella tematica o temporale (es. '2026', '2025', 'Locazioni', 'Bozze')")

class MessageIntent(BaseModel):
    intent: Literal["STORE_LOCATION", "QUERY_LOCATION", "QUERY_DEADLINES", "GENERAL"]
    item_name: Optional[str] = None
    primary_location: Optional[str] = None
    detailed_location: Optional[str] = None
    query_text: Optional[str] = None

class ChatRequest(BaseModel):
    message: Optional[str] = ""
    thread_id: Optional[str] = "general"
    quoted_message: Optional[dict] = None
    audio_base64: Optional[str] = None
    audio_format: Optional[str] = "wav"
    audio_duration: Optional[float] = None

class ChatThreadCreate(BaseModel):
    name: str = Field(..., description="Nome del gruppo o area tematica")
    thread_type: Literal["group", "thematic"] = Field(default="group", description="Tipo di chat")
    icon: Optional[str] = Field(default=None, description="Icona FontAwesome")
    color: Optional[str] = Field(default=None, description="Colore classe Tailwind")
    description: Optional[str] = Field(default=None, description="Descrizione dell'area o gruppo")
    members: Optional[List[str]] = Field(default_factory=list, description="Elenco membri del gruppo")

class ChatThreadResponse(BaseModel):
    id: str
    name: str
    thread_type: str
    icon: str
    color: str
    description: Optional[str] = None
    members: Optional[List[str]] = None
    created_at: Optional[str] = None
    last_message: Optional[str] = None
    last_message_time: Optional[str] = None
    message_count: int = 0
    unread_count: int = 0

class ThreadListResponse(BaseModel):
    threads: List[ChatThreadResponse]

class ChatResponse(BaseModel):
    reply: str
    action: str = "REPLY"
    data: Optional[dict] = None
    documents: Optional[List[dict]] = None
    confirmation: Optional[dict] = None
    routed_model: Optional[str] = None
    transcription: Optional[str] = None


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
    thread_id: Optional[str] = None
    thread_name: Optional[str] = None
    days_remaining: Optional[int] = None
    urgency: Optional[str] = None
    urgency_label: Optional[str] = None
    category: Optional[str] = None
    category_label: Optional[str] = None
    category_icon: Optional[str] = None
    subfolder: Optional[str] = None
    room: Optional[str] = None
    detailed_location: Optional[str] = None
    document_id: Optional[int] = None
    physical_item_id: Optional[int] = None
    image_url: Optional[str] = None
    has_photo: Optional[bool] = None
    is_local_file: Optional[bool] = None
    original_path: Optional[str] = None

class DashboardKPI(BaseModel):
    total_upcoming_amount: float
    pending_deadlines_count: int
    total_documents_count: int
    total_items_count: int
    quietanzati_count: Optional[int] = 0

class DashboardResponse(BaseModel):
    kpi: DashboardKPI
    records: List[RecordItem]
    app_version: Optional[str] = None

class DeadlineAlertItem(BaseModel):
    id: int
    document_id: int
    title: str
    issuer: Optional[str] = None
    amount: Optional[float] = None
    due_date: str
    days_remaining: int
    urgency: str  # 'overdue', 'today', 'urgent', 'soon', 'future'
    urgency_label: str
    file_url: Optional[str] = None
    download_url: str
    file_type: Optional[str] = None
    thread_id: Optional[str] = None

class DeadlineAlertsResponse(BaseModel):
    has_alerts: bool
    overdue_count: int
    due_soon_count: int
    total_alerts: int
    total_amount: float
    summary_message: str
    today: str
    alerts: List[DeadlineAlertItem]

class BulkDeleteRequest(BaseModel):
    document_ids: Optional[List[int]] = None
    thread_id: Optional[str] = None
    delete_all: bool = False

class BulkDeleteResponse(BaseModel):
    success: bool
    count: int
    message: str
    deleted_ids: List[int]

class UnzipVaultRequest(BaseModel):
    document_id: Optional[int] = None
    file_url: Optional[str] = None
    thread_id: Optional[str] = None

class UIEventCreate(BaseModel):
    thread_id: Optional[str] = "general"
    event_type: str
    target_type: Optional[str] = None
    target_id: Optional[int] = None
    title: Optional[str] = None
    error_details: Optional[str] = None

class UIEventItem(BaseModel):
    id: int
    thread_id: str
    event_type: str
    target_type: Optional[str] = None
    target_id: Optional[int] = None
    title: Optional[str] = None
    error_details: Optional[str] = None
    created_at: Optional[str] = None

class UIEventResponse(BaseModel):
    status: str = "ok"
    event_id: int

class UIEventsListResponse(BaseModel):
    events: List[UIEventItem]

class LinkDocumentItemRequest(BaseModel):
    item_id: Optional[int] = None
    item_name: Optional[str] = None
    document_id: int
    thread_id: Optional[str] = "general"

class WatchedFolderCreate(BaseModel):
    path: str = Field(..., description="Percorso cartella locale su PC")
    name: Optional[str] = Field(default=None, description="Nome o etichetta personalizzata")
    thread_id: Optional[str] = Field(default="general", description="Spazio/Gruppo associato")
    auto_scan: bool = Field(default=True, description="Scansiona subito la cartella")

class WatchedFolderResponse(BaseModel):
    id: int
    path: str
    name: str
    thread_id: str
    is_active: bool
    auto_scan: bool
    last_scanned_at: Optional[str] = None
    file_count: int
    created_at: Optional[str] = None

class FolderScanResult(BaseModel):
    folder_id: Optional[int] = None
    folder_path: str
    scanned_files_count: int
    new_indexed_count: int
    skipped_count: int
    error_count: int
    details: List[str] = Field(default_factory=list)

class FolderSelectResponse(BaseModel):
    selected_path: Optional[str] = None
    cancelled: bool = False

class OpenInExplorerRequest(BaseModel):
    path: Optional[str] = None
    document_id: Optional[int] = None


class FolderPresetItem(BaseModel):
    key: str
    name: str
    path: str
    exists: bool
    is_watched: bool
    icon: str


class FolderPresetsResponse(BaseModel):
    presets: List[FolderPresetItem]


class PendingFileProposalResponse(BaseModel):
    id: int
    folder_id: Optional[int] = None
    folder_name: Optional[str] = None
    file_path: str
    file_name: str
    file_size: int
    doc_type: str
    issuer: Optional[str] = None
    amount: Optional[float] = None
    due_date: Optional[str] = None
    sensitivity_reason: str
    summary: str
    status: str
    thread_id: str
    detected_at: Optional[str] = None


class PendingProposalsListResponse(BaseModel):
    proposals: List[PendingFileProposalResponse]
    count: int


class ApproveProposalResponse(BaseModel):
    success: bool
    message: str
    document_id: Optional[int] = None
    title: Optional[str] = None


class DismissProposalResponse(BaseModel):
    success: bool
    message: str
    proposal_id: int


class WipeDatabaseRequest(BaseModel):
    password: str
    delete_drive: bool = False


class WipeDatabaseResponse(BaseModel):
    success: bool
    message: str
    deleted_documents: int = 0
    deleted_items: int = 0
    deleted_messages: int = 0
    deleted_folders: int = 0
    drive_deleted: bool = False



