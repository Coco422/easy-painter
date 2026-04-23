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


class StorageError(RuntimeError):
    pass


class MinioStorageService:
    def __init__(self) -> None:
        settings = get_settings()
        self.bucket = settings.minio_bucket
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

    @staticmethod
    def _guess_extension(content_type: str) -> str:
        if "png" in content_type:
            return "png"
        if "webp" in content_type:
            return "webp"
        return "jpg"
