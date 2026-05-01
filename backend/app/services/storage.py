from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO

from minio import Minio
from minio.error import S3Error

from app.core.config import get_settings


@dataclass(slots=True)
class StoredImage:
    object_key: str
    public_url: str


@dataclass(slots=True)
class StoredReferenceImage:
    object_key: str
    image_bytes: bytes
    content_type: str


class StorageError(RuntimeError):
    pass


class MinioStorageService:
    def __init__(self) -> None:
        settings = get_settings()
        self.bucket = settings.minio_bucket
        self.reference_bucket = settings.minio_reference_bucket
        self.client = Minio(
            endpoint=settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
        )

    def upload_generated_image(self, job_id: str, image_bytes: bytes, content_type: str) -> StoredImage:
        timestamp = datetime.now(timezone.utc)
        extension = self._guess_extension(content_type)
        object_key = f"generated/{timestamp:%Y/%m/%d}/{job_id}.{extension}"
        stream = BytesIO(image_bytes)
        try:
            self.client.put_object(
                self.bucket,
                object_key,
                data=stream,
                length=len(image_bytes),
                content_type=content_type,
            )
        except S3Error as exc:
            raise StorageError("Failed to store generated image.") from exc
        return StoredImage(object_key=object_key, public_url=f"/media/{object_key}")

    def upload_reference_image(
        self,
        *,
        job_id: str,
        image_bytes: bytes,
        content_type: str,
        filename: str,
    ) -> str:
        timestamp = datetime.now(timezone.utc)
        extension = self._guess_extension(content_type)
        object_key = f"references/{timestamp:%Y/%m/%d}/{job_id}/{self._safe_stem(filename)}.{extension}"
        stream = BytesIO(image_bytes)
        try:
            self.client.put_object(
                self.reference_bucket,
                object_key,
                data=stream,
                length=len(image_bytes),
                content_type=content_type,
            )
        except S3Error as exc:
            raise StorageError("Failed to store reference image.") from exc
        return object_key

    def download_reference_image(self, object_key: str, content_type: str) -> StoredReferenceImage:
        try:
            response = self.client.get_object(self.reference_bucket, object_key)
            try:
                image_bytes = response.read()
            finally:
                response.close()
                response.release_conn()
        except S3Error as exc:
            raise StorageError("Failed to read reference image.") from exc
        return StoredReferenceImage(object_key=object_key, image_bytes=image_bytes, content_type=content_type)

    def delete_object(self, object_key: str) -> None:
        try:
            self.client.remove_object(self.bucket, object_key)
        except S3Error:
            pass

    def delete_reference_image(self, object_key: str) -> None:
        try:
            self.client.remove_object(self.reference_bucket, object_key)
        except S3Error:
            pass

    @staticmethod
    def _guess_extension(content_type: str) -> str:
        if "png" in content_type:
            return "png"
        if "webp" in content_type:
            return "webp"
        return "jpg"

    @staticmethod
    def _safe_stem(filename: str) -> str:
        stem = filename.rsplit(".", 1)[0] or "reference"
        safe = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in stem)
        return safe[:80] or "reference"
