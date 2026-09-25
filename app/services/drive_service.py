import os
import json
import uuid
import urllib.parse
import logging
from contextlib import contextmanager
from datetime import date
from typing import Protocol, Optional
import httpx

import re

logger = logging.getLogger(__name__)


def sanitize_drive_folder_name(name: Optional[str], thread_id: Optional[str] = None) -> str:
    """
    Pulisce il nome della cartella per Google Drive:
    - Rimuove emoji, caratteri grafici speciali e simboli non adatti a percorsi cartelle.
    - Mappa 'general', 'all' o 'Dove lo AI messo' su 'Generale'.
    - Normalizza gli spazi multipli.
    - Garantisce una stringa valida e leggibile.
    """
    if thread_id in ("general", "all") or not name:
        return "Generale"

    clean_raw = str(name).strip()
    if clean_raw.lower() in ("dove lo ai messo", "generale", "general", "default", "tutti", "tutto"):
        return "Generale"

    # Rimuovi emoji e simboli grafici Unicode
    emoji_pattern = re.compile(
        "["
        "\U00010000-\U0010ffff"  # Supplemental symbols, emoji
        "\u2600-\u26ff"          # Miscellaneous Symbols
        "\u2700-\u27bf"          # Dingbats
        "\u2300-\u23ff"          # Miscellaneous Technical
        "\u2b50-\u2b55"
        "\u200d"                 # Zero-width joiner
        "\ufe0f"                 # Variation selector
        "]+",
        flags=re.UNICODE
    )
    clean_text = emoji_pattern.sub("", clean_raw)

    # Rimuovi caratteri vietati nei percorsi di cartella Drive / filesystem: / \ : * ? " < > |
    clean_text = re.sub(r'[/\\:*?"<>|]', ' ', clean_text)
    # Riduci spazi multipli
    clean_text = re.sub(r'\s+', ' ', clean_text).strip(" .-")

    if not clean_text:
        if thread_id:
            tid_clean = re.sub(r'[^a-zA-Z0-9_-]', '', thread_id).capitalize()
            return tid_clean or "Generale"
        return "Generale"

    return clean_text


def resolve_drive_folder_path(
    doc_type: str,
    due_date: Optional[date] = None,
    category_label: Optional[str] = None,
    subfolder: Optional[str] = None,
    chat_folder: Optional[str] = None,
) -> list[str]:
    """
    Risolve il percorso logico delle cartelle su Google Drive in base al canale/chat,
    alla categoria e alla data di scadenza (se presente) o alla sottocartella / anno.
    
    Struttura con chat_folder:
    - ["DoveLoAIMesso", "<Chat>", "<Categoria>", "<Anno o Sottocartella>"]
    
    Struttura standard (backward-compatible, senza chat_folder):
    - Con category_label:
      * Con sottocartella: ["DoveLoAIMesso", "<Categoria>", "<Sottocartella>"]
      * Con scadenza: ["DoveLoAIMesso", "<Categoria>", "<Anno>"]
      * Senza: ["DoveLoAIMesso", "<Categoria>"]
    - Standard con scadenza: ["DoveLoAIMesso", "<Anno>", "<Categoria>"]
    - Standard senza scadenza: ["DoveLoAIMesso", "<Categoria>"]
    """
    clean_type = (doc_type or "").strip().lower()

    if category_label and category_label.strip():
        category = category_label.strip()
    elif clean_type in ("canzone", "testo_personale", "musica", "poesia"):
        category = "Note & Testi Personali"
    elif clean_type in ("bolletta", "utenza"):
        category = "Bollette & Utenze"
    elif clean_type in ("f24", "tributo", "fiscale", "modello_unico"):
        category = "Fisco & Tasse"
    elif clean_type in ("fattura", "ricevuta", "scontrino"):
        category = "Fatture & Spese"
    elif clean_type in ("contratto", "certificato", "polizza"):
        category = "Contratti & Polizze"
    else:
        category = "Documenti & Foto"

    clean_chat = (chat_folder or "").strip() if chat_folder else None

    if clean_chat:
        # Struttura organizzata per chat: DoveLoAIMesso / <Chat> / <Categoria> / ...
        if subfolder and subfolder.strip():
            return ["DoveLoAIMesso", clean_chat, category, subfolder.strip()]
        if due_date is not None:
            return ["DoveLoAIMesso", clean_chat, category, str(due_date.year)]
        return ["DoveLoAIMesso", clean_chat, category]

    # Retrocompatibilità (senza chat_folder specificato)
    if category_label and category_label.strip():
        if subfolder and subfolder.strip():
            return ["DoveLoAIMesso", category, subfolder.strip()]
        if due_date is not None:
            return ["DoveLoAIMesso", category, str(due_date.year)]
        return ["DoveLoAIMesso", category]

    if subfolder and subfolder.strip():
        return ["DoveLoAIMesso", category, subfolder.strip()]

    if due_date is not None:
        return ["DoveLoAIMesso", str(due_date.year), category]
    return ["DoveLoAIMesso", category]


class GoogleDriveServiceInterface(Protocol):
    def get_auth_url(self, state: str = "") -> str:
        ...

    def exchange_code(self, code: str) -> dict:
        ...

    def upload_file(
        self,
        file_bytes: bytes,
        filename: str,
        mime_type: str,
        folder_path: list[str],
        access_token: str,
    ) -> dict:
        ...

    def delete_vault_root_folder(self, access_token: str) -> bool:
        ...


class MockGoogleDriveService:
    """Implementazione mock offline di GoogleDriveService per test e sviluppo locale."""

    def get_auth_url(self, state: str = "") -> str:
        params = {"mock": "true"}
        if state:
            params["state"] = state
        return f"https://accounts.google.com/o/oauth2/v2/auth?{urllib.parse.urlencode(params)}"

    def exchange_code(self, code: str) -> dict:
        return {
            "access_token": "mock-access-token",
            "refresh_token": "mock-refresh-token",
            "expires_in": 3600,
            "email": "mock.user@gmail.com",
        }

    def upload_file(
        self,
        file_bytes: bytes,
        filename: str,
        mime_type: str,
        folder_path: list[str],
        access_token: str,
    ) -> dict:
        mock_id = f"drive-mock-{uuid.uuid4().hex[:12]}"
        return {
            "file_id": mock_id,
            "web_view_link": f"https://drive.google.com/file/d/{mock_id}/view",
        }

    def delete_vault_root_folder(self, access_token: str) -> bool:
        return True


class RealGoogleDriveService:
    """Implementazione reale di GoogleDriveService con chiamate REST alle Google API v3."""

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        redirect_uri: Optional[str] = None,
        http_client: Optional[httpx.Client] = None,
    ):
        self.client_id = client_id or os.getenv("GOOGLE_CLIENT_ID", "")
        self.client_secret = client_secret or os.getenv("GOOGLE_CLIENT_SECRET", "")
        self.redirect_uri = (
            redirect_uri
            or os.getenv("GOOGLE_DRIVE_REDIRECT_URI")
            or "http://localhost:8000/api/drive/callback"
        )
        self.scope = (
            "https://www.googleapis.com/auth/drive.file "
            "https://www.googleapis.com/auth/userinfo.email"
        )
        self._http_client = http_client

    @contextmanager
    def _client_ctx(self):
        if self._http_client is not None:
            yield self._http_client
        else:
            with httpx.Client(timeout=30.0) as client:
                yield client

    def get_auth_url(self, state: str = "") -> str:
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": self.scope,
            "access_type": "offline",
            "prompt": "consent",
        }
        if state:
            params["state"] = state
        return f"https://accounts.google.com/o/oauth2/v2/auth?{urllib.parse.urlencode(params)}"

    def exchange_code(self, code: str) -> dict:
        token_url = "https://oauth2.googleapis.com/token"
        payload = {
            "code": code,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "redirect_uri": self.redirect_uri,
            "grant_type": "authorization_code",
        }

        with self._client_ctx() as client:
            resp = client.post(token_url, data=payload)
            resp.raise_for_status()
            token_data = resp.json()

            access_token = token_data.get("access_token", "")
            refresh_token = token_data.get("refresh_token", "")
            expires_in = token_data.get("expires_in", 3600)

            email = None
            try:
                userinfo_resp = client.get(
                    "https://www.googleapis.com/oauth2/v2/userinfo",
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                if userinfo_resp.status_code == 200:
                    email = userinfo_resp.json().get("email")
            except Exception as e:
                logger.warning(f"Impossibile recuperare email userinfo: {e}")

            return {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "expires_in": expires_in,
                "email": email,
            }

    def get_or_create_folder(
        self, folder_name: str, parent_id: Optional[str], access_token: str, client: httpx.Client
    ) -> str:
        safe_name = folder_name.replace("'", "\\'")
        query_parts = [
            "mimeType = 'application/vnd.google-apps.folder'",
            f"name = '{safe_name}'",
            "trashed = false",
        ]
        if parent_id:
            query_parts.append(f"'{parent_id}' in parents")
        else:
            query_parts.append("'root' in parents")

        q = " and ".join(query_parts)
        headers = {"Authorization": f"Bearer {access_token}"}

        res = client.get(
            "https://www.googleapis.com/drive/v3/files",
            headers=headers,
            params={"q": q, "fields": "files(id, name)"},
        )
        res.raise_for_status()
        files = res.json().get("files", [])
        if files:
            return files[0]["id"]

        # Cartella non trovata: creala
        body = {
            "name": folder_name,
            "mimeType": "application/vnd.google-apps.folder",
        }
        if parent_id:
            body["parents"] = [parent_id]

        create_res = client.post(
            "https://www.googleapis.com/drive/v3/files",
            headers=headers,
            json=body,
        )
        create_res.raise_for_status()
        return create_res.json()["id"]

    def upload_file(
        self,
        file_bytes: bytes,
        filename: str,
        mime_type: str,
        folder_path: list[str],
        access_token: str,
    ) -> dict:
        with self._client_ctx() as client:
            parent_id = None
            for folder_name in folder_path:
                cleaned = folder_name.strip()
                if cleaned:
                    parent_id = self.get_or_create_folder(
                        folder_name=cleaned,
                        parent_id=parent_id,
                        access_token=access_token,
                        client=client,
                    )

            boundary = f"=====boundary_{uuid.uuid4().hex}====="
            metadata = {"name": filename}
            if parent_id:
                metadata["parents"] = [parent_id]

            meta_bytes = json.dumps(metadata).encode("utf-8")
            body = (
                f"--{boundary}\r\n"
                f"Content-Type: application/json; charset=UTF-8\r\n\r\n"
            ).encode("utf-8") + meta_bytes + (
                f"\r\n--{boundary}\r\n"
                f"Content-Type: {mime_type}\r\n\r\n"
            ).encode("utf-8") + file_bytes + (
                f"\r\n--{boundary}--\r\n"
            ).encode("utf-8")

            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": f"multipart/related; boundary={boundary}",
            }

            upload_url = "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&fields=id,webViewLink"
            res = client.post(upload_url, headers=headers, content=body)
            res.raise_for_status()
            data = res.json()
            file_id = data.get("id", "")
            web_view_link = data.get("webViewLink") or f"https://drive.google.com/file/d/{file_id}/view"

            return {
                "file_id": file_id,
                "web_view_link": web_view_link,
            }

    def delete_vault_root_folder(self, access_token: str) -> bool:
        """Elimina la cartella radice DoveLoAIMesso e tutti i relativi file su Google Drive."""
        with self._client_ctx() as client:
            headers = {"Authorization": f"Bearer {access_token}"}
            q = "mimeType = 'application/vnd.google-apps.folder' and name = 'DoveLoAIMesso' and trashed = false and 'root' in parents"
            try:
                res = client.get(
                    "https://www.googleapis.com/drive/v3/files",
                    headers=headers,
                    params={"q": q, "fields": "files(id, name)"}
                )
                if res.status_code == 200:
                    files = res.json().get("files", [])
                    for f in files:
                        fid = f.get("id")
                        if fid:
                            client.delete(f"https://www.googleapis.com/drive/v3/files/{fid}", headers=headers)
                    return True
                else:
                    logger.warning(f"Google Drive search folder failed ({res.status_code}): {res.text}")
                    return False
            except Exception as e:
                logger.error(f"Errore durante eliminazione cartella radice DoveLoAIMesso da Drive: {e}")
                return False


def get_drive_service() -> GoogleDriveServiceInterface:
    client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
    if client_id and client_secret:
        return RealGoogleDriveService(client_id=client_id, client_secret=client_secret)
    return MockGoogleDriveService()
