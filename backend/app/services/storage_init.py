"""Create private S3 buckets before API, worker and dispatcher start."""
from __future__ import annotations

from minio.error import S3Error

from app.services.storage import MinioStorageService


def initialize_storage() -> None:
    storage = MinioStorageService()
    for bucket in dict.fromkeys((storage.bucket, storage.reference_bucket)):
        if not storage.client.bucket_exists(bucket):
            try:
                storage.client.make_bucket(bucket)
            except S3Error as exc:
                # Another initializer may have created this bucket concurrently.
                if exc.code != "BucketAlreadyOwnedByYou":
                    raise
        try:
            # No anonymous policy: reads continue through the authorized API.
            storage.client.delete_bucket_policy(bucket)
        except S3Error as exc:
            if exc.code != "NoSuchBucketPolicy":
                raise


if __name__ == "__main__":
    initialize_storage()
