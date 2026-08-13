from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator
from datetime import datetime, timezone
from io import BytesIO

from minio import Minio
from minio.commonconfig import CopySource
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
        except Exception as exc:
            raise StorageError("Failed to store generated image.") from exc
        return StoredImage(object_key=object_key, public_url="")

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
        except Exception as exc:
            raise StorageError("Failed to store reference image.") from exc
        return object_key

    def upload_staging_reference_image(
        self,
        *,
        image_id: str,
        image_bytes: bytes,
        content_type: str,
    ) -> str:
        timestamp = datetime.now(timezone.utc)
        extension = self._guess_extension(content_type)
        object_key = f"references/{timestamp:%Y/%m/%d}/staging/{image_id}.{extension}"
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
        except Exception as exc:
            raise StorageError("Failed to store reference image.") from exc
        return object_key

    def copy_reference_image_to_job(
        self,
        src_key: str,
        *,
        job_id: str,
        filename: str,
        content_type: str,
    ) -> str:
        timestamp = datetime.now(timezone.utc)
        extension = self._guess_extension(content_type)
        object_key = f"references/{timestamp:%Y/%m/%d}/{job_id}/{self._safe_stem(filename)}.{extension}"
        try:
            self.client.copy_object(
                self.reference_bucket,
                object_key,
                CopySource(self.reference_bucket, src_key),
            )
        except S3Error as exc:
            raise StorageError("Failed to copy reference image.") from exc
        except Exception as exc:
            raise StorageError("Failed to copy reference image.") from exc
        return object_key

    def upload_inspiration_image(self, image_id: str, image_bytes: bytes, content_type: str) -> StoredImage:
        timestamp = datetime.now(timezone.utc)
        extension = self._guess_extension(content_type)
        object_key = f"inspirations/{timestamp:%Y/%m/%d}/{image_id}.{extension}"
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
            raise StorageError("Failed to store inspiration image.") from exc
        except Exception as exc:
            raise StorageError("Failed to store inspiration image.") from exc
        # Never publish an object-store key as a browser URL.  The API performs
        # the visibility check before it streams this object.
        return StoredImage(object_key=object_key, public_url=f"/api/v1/inspirations/{image_id}/file")

    def copy_generated_image_to_inspiration(self, src_key: str, *, inspiration_id: str) -> str:
        """Create a permanent, independently owned community copy."""
        timestamp = datetime.now(timezone.utc)
        object_key = f"inspirations/curated/{timestamp:%Y/%m/%d}/{inspiration_id}"
        try:
            self.client.copy_object(self.bucket, object_key, CopySource(self.bucket, src_key))
        except S3Error as exc:
            raise StorageError("Failed to copy generated image to inspiration.") from exc
        except Exception as exc:
            raise StorageError("Failed to copy generated image to inspiration.") from exc
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
        except Exception as exc:
            raise StorageError("Failed to read reference image.") from exc
        return StoredReferenceImage(object_key=object_key, image_bytes=image_bytes, content_type=content_type)

    def open_object(self, object_key: str, *, reference: bool = False):
        """Return MinIO's streaming response; caller is responsible for closing it."""
        try:
            return self.client.get_object(self.reference_bucket if reference else self.bucket, object_key)
        except S3Error as exc:
            raise StorageError("Failed to read stored image.") from exc
        except Exception as exc:
            raise StorageError("Failed to read stored image.") from exc

    def iter_object(self, object_key: str, *, reference: bool = False, chunk_size: int = 64 * 1024) -> Iterator[bytes]:
        response = self.open_object(object_key, reference=reference)
        yield from self.iter_response(response, chunk_size=chunk_size)

    @staticmethod
    def iter_response(response, *, chunk_size: int = 64 * 1024) -> Iterator[bytes]:
        """Drain and close an already-open MinIO response."""
        try:
            while chunk := response.read(chunk_size):
                yield chunk
        finally:
            response.close()
            response.release_conn()

    def delete_object(self, object_key: str) -> None:
        try:
            self.client.remove_object(self.bucket, object_key)
        except S3Error as exc:
            # The cleanup queue treats a missing object as successful, but
            # callers must be able to distinguish a transient storage failure.
            if exc.code not in {"NoSuchKey", "NoSuchObject", "NotFound"}:
                raise StorageError("Failed to delete generated image.") from exc
        except Exception as exc:
            raise StorageError("Failed to delete generated image.") from exc

    def delete_reference_image(self, object_key: str) -> None:
        try:
            self.client.remove_object(self.reference_bucket, object_key)
        except S3Error as exc:
            if exc.code not in {"NoSuchKey", "NoSuchObject", "NotFound"}:
                raise StorageError("Failed to delete reference image.") from exc
        except Exception as exc:
            raise StorageError("Failed to delete reference image.") from exc

    def check_ready(self) -> bool:
        try:
            return self.client.bucket_exists(self.bucket) and self.client.bucket_exists(self.reference_bucket)
        except S3Error as exc:
            raise StorageError("Object storage is unavailable.") from exc
        except Exception as exc:
            raise StorageError("Object storage is unavailable.") from exc

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
