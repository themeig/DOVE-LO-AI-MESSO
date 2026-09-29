import os
import uuid
import logging
from contextlib import contextmanager
from datetime import datetime, date, timedelta, timezone
from typing import Protocol, Optional, List, Dict, Any
import httpx

from app.models.database import Document, GoogleDriveCredential

logger = logging.getLogger(__name__)

DEDICATED_CALENDAR_SUMMARY = "Dove Lo AI Messo - Scadenze"
DEDICATED_CALENDAR_DESCRIPTION = "Scadenze fiscali, utenze, documenti personali e polizze sincronizzati dall'archivio Dove Lo AI Messo."


class GoogleCalendarServiceInterface(Protocol):
    def get_or_create_dedicated_calendar(self, access_token: str) -> str:
        """Restituisce l'ID del calendario 'Dove Lo AI Messo - Scadenze', creandolo se assente."""
        ...

    def sync_deadline_event(
        self,
        doc: Document,
        calendar_id: str,
        access_token: str,
    ) -> Dict[str, Any]:
        """Crea o aggiorna un evento per la scadenza nel calendario specificato."""
        ...

    def delete_deadline_event(
        self,
        event_id: str,
        calendar_id: str,
        access_token: str,
    ) -> bool:
        """Elimina un evento dal calendario Google."""
        ...

    def sync_all_deadlines(
        self,
        docs: List[Document],
        access_token: str,
        calendar_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Sincronizza in blocco tutti i documenti con scadenza."""
        ...


class MockGoogleCalendarService:
    """Implementazione mock deterministica per test e sviluppo locale senza chiavi API."""

    def __init__(self):
        self.events_db: Dict[str, dict] = {}
        self.calendars: Dict[str, str] = {DEDICATED_CALENDAR_SUMMARY: "mock-cal-scadenze-id"}

    def get_or_create_dedicated_calendar(self, access_token: str) -> str:
        return self.calendars[DEDICATED_CALENDAR_SUMMARY]

    def sync_deadline_event(
        self,
        doc: Document,
        calendar_id: str,
        access_token: str,
    ) -> Dict[str, Any]:
        if not doc.due_date:
            return {}
        ev_id = doc.google_calendar_event_id or f"mock-cal-ev-{doc.id}-{uuid.uuid4().hex[:6]}"
        html_link = f"https://calendar.google.com/calendar/event?eid={ev_id}"
        cat_label = doc.category_label or doc.category or "Scadenza"
        title_prefix = "[PAGATO] " if doc.status == "quietanzato" else ""
        event_title = f"{title_prefix}[{cat_label}] {doc.title}"
        self.events_db[ev_id] = {
            "id": ev_id,
            "title": event_title,
            "status": doc.status,
            "due_date": doc.due_date.isoformat(),
            "amount": doc.amount,
            "calendar_id": calendar_id,
            "htmlLink": html_link,
        }
        return {"event_id": ev_id, "html_link": html_link}

    def delete_deadline_event(
        self,
        event_id: str,
        calendar_id: str,
        access_token: str,
    ) -> bool:
        self.events_db.pop(event_id, None)
        return True

    def sync_all_deadlines(
        self,
        docs: List[Document],
        access_token: str,
        calendar_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        cal_id = calendar_id or self.get_or_create_dedicated_calendar(access_token)
        synced = []
        for d in docs:
            if d.due_date:
                res = self.sync_deadline_event(d, cal_id, access_token)
                d.google_calendar_event_id = res.get("event_id")
                synced.append(d.id)
        return {
            "success": True,
            "calendar_id": cal_id,
            "synced_count": len(synced),
            "synced_doc_ids": synced,
            "errors": [],
        }


class RealGoogleCalendarService:
    """Implementazione reale con Google Calendar API v3 REST."""

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        http_client: Optional[httpx.Client] = None,
    ):
        self.client_id = client_id or os.getenv("GOOGLE_CLIENT_ID", "")
        self.client_secret = client_secret or os.getenv("GOOGLE_CLIENT_SECRET", "")
        self._http_client = http_client

    @contextmanager
    def _client_ctx(self):
        if self._http_client is not None:
            yield self._http_client
        else:
            with httpx.Client(timeout=30.0) as client:
                yield client

    def get_or_create_dedicated_calendar(self, access_token: str) -> str:
        headers = {"Authorization": f"Bearer {access_token}"}
        with self._client_ctx() as client:
            # 1. Cerca nei calendari esistenti dell'utente
            try:
                resp = client.get(
                    "https://www.googleapis.com/calendar/v3/users/me/calendarList",
                    headers=headers,
                )
                if resp.status_code == 200:
                    items = resp.json().get("items", [])
                    for item in items:
                        if item.get("summary") == DEDICATED_CALENDAR_SUMMARY:
                            return item["id"]
            except Exception as e:
                logger.warning(f"Errore ricerca calendario dedicato: {e}")

            # 2. Crea un nuovo calendario secondario
            create_payload = {
                "summary": DEDICATED_CALENDAR_SUMMARY,
                "description": DEDICATED_CALENDAR_DESCRIPTION,
                "timeZone": "Europe/Rome",
            }
            create_resp = client.post(
                "https://www.googleapis.com/calendar/v3/calendars",
                headers=headers,
                json=create_payload,
            )
            create_resp.raise_for_status()
            cal_id = create_resp.json()["id"]
            return cal_id

    def sync_deadline_event(
        self,
        doc: Document,
        calendar_id: str,
        access_token: str,
    ) -> Dict[str, Any]:
        if not doc.due_date:
            return {}

        headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
        start_date = doc.due_date.isoformat()
        # Per evento tutto il giorno, end_date è il giorno successivo in Google Calendar
        end_date = (doc.due_date + timedelta(days=1)).isoformat()

        cat_label = doc.category_label or doc.category or "Scadenza"
        title_prefix = "[PAGATO] " if doc.status == "quietanzato" else ""
        summary_title = f"{title_prefix}[{cat_label}] {doc.title}"

        lines = [
            f"Atto archiviato: {doc.title}",
            f"Categoria: {cat_label}",
        ]
        if doc.issuer:
            lines.append(f"Ente/Fornitore: {doc.issuer}")
        if doc.amount is not None:
            lines.append(f"Importo: € {doc.amount:.2f}")
        if doc.status == "quietanzato":
            lines.append("Stato atto: QUIETANZATO / SALDATO ✅")
        elif doc.status:
            lines.append(f"Stato atto: {doc.status.upper()}")
        if doc.summary:
            lines.append(f"\nNote & Sintesi:\n{doc.summary}")
        lines.append(f"\nArchivio: Dove Lo AI Messo (ID Documento #{doc.id})")

        payload = {
            "summary": summary_title,
            "description": "\n".join(lines),
            "start": {"date": start_date},
            "end": {"date": end_date},
            "reminders": {
                "useDefault": False,
                "overrides": [
                    {"method": "popup", "minutes": 1440},  # 1 giorno prima
                    {"method": "popup", "minutes": 120},   # 2 ore prima del giorno
                ],
            },
        }

        with self._client_ctx() as client:
            cal_enc = calendar_id.replace("#", "%23")
            # Se ha già un event_id, prova l'aggiornamento
            if doc.google_calendar_event_id:
                ev_id = doc.google_calendar_event_id
                url = f"https://www.googleapis.com/calendar/v3/calendars/{cal_enc}/events/{ev_id}"
                resp = client.put(url, headers=headers, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    return {"event_id": data["id"], "html_link": data.get("htmlLink", "")}
                elif resp.status_code == 404:
                    # Evento eliminato su Google Calendar, ricrealo
                    pass
                else:
                    resp.raise_for_status()

            # Creazione nuovo evento
            url = f"https://www.googleapis.com/calendar/v3/calendars/{cal_enc}/events"
            resp = client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            return {"event_id": data["id"], "html_link": data.get("htmlLink", "")}

    def delete_deadline_event(
        self,
        event_id: str,
        calendar_id: str,
        access_token: str,
    ) -> bool:
        if not event_id:
            return True
        headers = {"Authorization": f"Bearer {access_token}"}
        cal_enc = calendar_id.replace("#", "%23")
        url = f"https://www.googleapis.com/calendar/v3/calendars/{cal_enc}/events/{event_id}"
        with self._client_ctx() as client:
            resp = client.delete(url, headers=headers)
            if resp.status_code in (200, 204, 404, 410):
                return True
            logger.warning(f"Errore eliminazione evento Google Calendar: {resp.status_code}")
            return False

    def sync_all_deadlines(
        self,
        docs: List[Document],
        access_token: str,
        calendar_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        cal_id = calendar_id or self.get_or_create_dedicated_calendar(access_token)
        synced = []
        errors = []
        for d in docs:
            if d.due_date:
                try:
                    res = self.sync_deadline_event(d, cal_id, access_token)
                    if res and res.get("event_id"):
                        d.google_calendar_event_id = res["event_id"]
                        synced.append(d.id)
                except Exception as e:
                    logger.error(f"Errore sincronizzazione evento per doc #{d.id}: {e}")
                    errors.append({"doc_id": d.id, "error": str(e)})

        return {
            "success": True,
            "calendar_id": cal_id,
            "synced_count": len(synced),
            "synced_doc_ids": synced,
            "errors": errors,
        }


_calendar_service_instance: Optional[GoogleCalendarServiceInterface] = None


def get_calendar_service() -> GoogleCalendarServiceInterface:
    """Restituisce il servizio Google Calendar (Real se GOOGLE_CLIENT_ID configurato, altrimenti Mock)."""
    global _calendar_service_instance
    if _calendar_service_instance is not None:
        return _calendar_service_instance

    client_id = os.getenv("GOOGLE_CLIENT_ID")
    if client_id:
        return RealGoogleCalendarService(
            client_id=client_id,
            client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
        )
    return MockGoogleCalendarService()


def set_calendar_service(service: Optional[GoogleCalendarServiceInterface]):
    """Consente l'iniezione del servizio per scopi di testing."""
    global _calendar_service_instance
    _calendar_service_instance = service


def auto_sync_calendar_event(doc: Document, db: Any) -> Optional[Dict[str, Any]]:
    """Se Google Calendar è collegato e attivo e il documento ha data di scadenza (o aveva un evento associato), sincronizza o aggiorna l'evento."""
    cred = db.query(GoogleDriveCredential).first()
    if not cred or not cred.access_token:
        return None
    if getattr(cred, "calendar_enabled", True) is False:
        return None

    # Rinnova il token automaticamente se scaduto
    from app.services.drive_service import get_fresh_access_token
    access_token = get_fresh_access_token(cred, db)
    if not access_token:
        logger.warning("Token Google non disponibile per Calendar sync — operazione saltata.")
        return None

    service = get_calendar_service()
    try:
        cal_target = getattr(cred, "calendar_target", "dedicated")
        if cal_target == "primary":
            cal_id = "primary"
        else:
            cal_id = cred.google_calendar_id or service.get_or_create_dedicated_calendar(access_token)
            if not cred.google_calendar_id:
                cred.google_calendar_id = cal_id
                db.commit()

        if doc.due_date:
            res = service.sync_deadline_event(doc, cal_id, access_token)
            if res and res.get("event_id"):
                doc.google_calendar_event_id = res["event_id"]
                db.commit()
            return res
        elif doc.google_calendar_event_id:
            # Se la scadenza è stata rimossa dal documento, elimina l'evento esistente
            service.delete_deadline_event(doc.google_calendar_event_id, cal_id, access_token)
            doc.google_calendar_event_id = None
            db.commit()
    except Exception as e:
        logger.warning(f"Errore auto_sync_calendar_event per doc #{doc.id}: {e}")
    return None


def auto_delete_calendar_event(doc: Document, db: Any) -> bool:
    """Se il documento ha un evento su Google Calendar, lo rimuove prima dell'eliminazione del record dal caveau."""
    if not doc.google_calendar_event_id:
        return False
    cred = db.query(GoogleDriveCredential).first()
    if not cred or not cred.access_token:
        return False
    from app.services.drive_service import get_fresh_access_token
    access_token = get_fresh_access_token(cred, db)
    if not access_token:
        return False
    service = get_calendar_service()
    try:
        cal_id = cred.google_calendar_id or "primary"
        res = service.delete_deadline_event(doc.google_calendar_event_id, cal_id, access_token)
        doc.google_calendar_event_id = None
        db.commit()
        return res
    except Exception as e:
        logger.warning(f"Errore auto_delete_calendar_event per doc #{doc.id}: {e}")
        return False


def auto_sync_all_deadlines(db: Any) -> Optional[Dict[str, Any]]:
    """Sincronizza tutte le scadenze presenti nel caveau verso Google Calendar se connesso e attivo."""
    cred = db.query(GoogleDriveCredential).first()
    if not cred or not cred.access_token:
        return None
    if getattr(cred, "calendar_enabled", True) is False:
        return None
    from app.services.drive_service import get_fresh_access_token
    access_token = get_fresh_access_token(cred, db)
    if not access_token:
        return None
    service = get_calendar_service()
    try:
        cal_target = getattr(cred, "calendar_target", "dedicated")
        if cal_target == "primary":
            cal_id = "primary"
        else:
            cal_id = cred.google_calendar_id or service.get_or_create_dedicated_calendar(access_token)
            if not cred.google_calendar_id:
                cred.google_calendar_id = cal_id
                db.commit()
        docs = db.query(Document).filter(Document.due_date.isnot(None)).all()
        res = service.sync_all_deadlines(docs, access_token, cal_id)
        db.commit()
        return res
    except Exception as e:
        logger.warning(f"Errore auto_sync_all_deadlines: {e}")
        return None
