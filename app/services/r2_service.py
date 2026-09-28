"""
Modulo di integrazione con Cloudflare R2 (Object Storage S3-compatible).
Gestisce il salvataggio sicuro e la generazione di presigned URL a scadenza temporanea (15 min)
per i documenti condivisi nei gruppi, garantendo zero costi di banda (egress free).
"""
import uuid
import re
import time
from typing import Protocol, Dict, Optional
from pathlib import Path

from app.config import get_settings


class R2StorageServiceInterface(Protocol):
    def upload_group_file(
        self,
        file_bytes: bytes,
        filename: str,
        group_id: str,
        category: str = "generico",
        content_type: str = "application/octet-stream"
    ) -> str:
        ...

    def generate_presigned_download_url(self, file_key: str, expires_in: int = 900) -> str:
        ...

    def delete_group_file(self, file_key: str) -> bool:
        ...

    def file_exists(self, file_key: str) -> bool:
        ...


def _sanitize_filename(name: str) -> str:
    cleaned = re.sub(r"[^\w\.-]", "_", name).strip("_")
    return cleaned or "document.bin"


class MockR2StorageService:
    """Implementazione deterministica in memoria per test e ambienti di sviluppo locale."""

    def __init__(self):
        self._storage: Dict[str, bytes] = {}

    def upload_group_file(
        self,
        file_bytes: bytes,
        filename: str,
        group_id: str,
        category: str = "generico",
        content_type: str = "application/octet-stream"
    ) -> str:
        safe_name = _sanitize_filename(filename)
        unique_prefix = uuid.uuid4().hex[:8]
        clean_cat = _sanitize_filename(category).lower()
        file_key = f"groups/{group_id}/{clean_cat}/{unique_prefix}_{safe_name}"
        self._storage[file_key] = file_bytes
        return file_key

    def generate_presigned_download_url(self, file_key: str, expires_in: int = 900) -> str:
        exp_ts = int(time.time()) + expires_in
        return f"https://mock-r2.doveloaimesso.internal/{file_key}?expires={exp_ts}&signature=mock_r2_sig"

    def delete_group_file(self, file_key: str) -> bool:
        if file_key in self._storage:
            del self._storage[file_key]
            return True
        return False

    def file_exists(self, file_key: str) -> bool:
        return file_key in self._storage


class RealR2StorageService:
    """Client Cloudflare R2 tramite API S3-compatible (boto3)."""

    def __init__(self):
        settings = get_settings()
        import boto3
        from botocore.config import Config

        endpoint = f"https://{settings.R2_ACCOUNT_ID}.r2.cloudflarestorage.com"
        self.bucket = settings.R2_BUCKET_NAME
        self.s3_client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=settings.R2_ACCESS_KEY_ID,
            aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
            config=Config(signature_version="s3v4")
        )

    def upload_group_file(
        self,
        file_bytes: bytes,
        filename: str,
        group_id: str,
        category: str = "generico",
        content_type: str = "application/octet-stream"
    ) -> str:
        safe_name = _sanitize_filename(filename)
        unique_prefix = uuid.uuid4().hex[:8]
        clean_cat = _sanitize_filename(category).lower()
        file_key = f"groups/{group_id}/{clean_cat}/{unique_prefix}_{safe_name}"

        self.s3_client.put_object(
            Bucket=self.bucket,
            Key=file_key,
            Body=file_bytes,
            ContentType=content_type
        )
        return file_key

    def generate_presigned_download_url(self, file_key: str, expires_in: int = 900) -> str:
        return self.s3_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": file_key},
            ExpiresIn=expires_in
        )

    def delete_group_file(self, file_key: str) -> bool:
        try:
            self.s3_client.delete_object(Bucket=self.bucket, Key=file_key)
            return True
        except Exception:
            return False

    def file_exists(self, file_key: str) -> bool:
        try:
            self.s3_client.head_object(Bucket=self.bucket, Key=file_key)
            return True
        except Exception:
            return False


_r2_instance: Optional[R2StorageServiceInterface] = None


def get_r2_service() -> R2StorageServiceInterface:
    """Restituisce l'istanza singleton del servizio Cloudflare R2 (reale se configurato, altrimenti mock)."""
    global _r2_instance
    if _r2_instance is None:
        settings = get_settings()
        has_keys = bool(
            settings.R2_ACCOUNT_ID and
            settings.R2_ACCESS_KEY_ID and
            settings.R2_SECRET_ACCESS_KEY
        )
        if has_keys:
            try:
                _r2_instance = RealR2StorageService()
            except Exception:
                _r2_instance = MockR2StorageService()
        else:
            _r2_instance = MockR2StorageService()
    return _r2_instance
