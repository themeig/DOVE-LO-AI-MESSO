"""
Package app.services.agent
Architettura modulare per l'Agente Conversazionale e i Tool del Caveau.
"""
from app.services.agent.helpers import (
    WEEKDAYS_IT,
    MONTHS_IT,
    get_current_date_info,
    categorize_deadline,
    is_tool_payload,
    strip_tool_tags,
    filter_relevant_documents,
    extract_rename_title,
    extract_item_and_location,
    extract_bulk_delete_target,
    extract_link_photo_item,
)
from app.services.agent.tools_spec import TOOLS_DEFINITION
from app.services.agent.prompts import SYSTEM_PROMPT
from app.services.agent.context_builder import (
    get_recent_ui_events,
    build_ui_telemetry_prompt_note,
    build_system_prompt,
)
from app.services.agent.tools_executor import execute_vault_tool
from app.services.agent.orchestrator import AgenticChatService, AgentService

__all__ = [
    "WEEKDAYS_IT",
    "MONTHS_IT",
    "get_current_date_info",
    "categorize_deadline",
    "is_tool_payload",
    "strip_tool_tags",
    "filter_relevant_documents",
    "extract_rename_title",
    "extract_item_and_location",
    "extract_bulk_delete_target",
    "extract_link_photo_item",
    "TOOLS_DEFINITION",
    "SYSTEM_PROMPT",
    "get_recent_ui_events",
    "build_ui_telemetry_prompt_note",
    "build_system_prompt",
    "execute_vault_tool",
    "AgenticChatService",
    "AgentService",
]
