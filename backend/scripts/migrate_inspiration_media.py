"""Copy legacy externally hosted inspiration images into managed MinIO.

The command is dry-run by default. Use ``--apply`` after reviewing the JSON
report; failures remain unchanged and are included in the report.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import socket
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.inspiration import Inspiration
from app.models.media import MediaState
from app.services.reference_images import (
    MAX_REFERENCE_IMAGE_BYTES,
    ReferenceImageValidationError,
    validate_reference_image,
)
from app.services.storage import MinioStorageService, StorageError


MAX_REDIRECTS = 5


def _validate_public_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("only absolute HTTP(S) URLs are supported")
    for answer in socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)):
        address = ipaddress.ip_address(answer[4][0])
        if not address.is_global:
            raise ValueError("URL resolves to a non-public address")


def _download(client: httpx.Client, url: str) -> tuple[bytes, str, str]:
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        _validate_public_url(current)
        with client.stream("GET", current) as response:
            if response.is_redirect:
                location = response.headers.get("location")
                if not location:
                    raise ValueError("redirect has no location")
                current = urljoin(current, location)
                continue
            response.raise_for_status()
            declared_size = int(response.headers.get("content-length", "0") or 0)
            if declared_size > MAX_REFERENCE_IMAGE_BYTES:
                raise ValueError("image exceeds 10MB")
            chunks: list[bytes] = []
            received = 0
            for chunk in response.iter_bytes():
                received += len(chunk)
                if received > MAX_REFERENCE_IMAGE_BYTES:
                    raise ValueError("image exceeds 10MB")
                chunks.append(chunk)
            content_type = response.headers.get("content-type", "image/jpeg").split(";", 1)[0].strip()
            filename = Path(urlparse(current).path).name or "inspiration.jpg"
            validated = validate_reference_image(
                filename=filename,
                content_type=content_type,
                image_bytes=b"".join(chunks),
            )
            return validated.image_bytes, validated.content_type, validated.filename
    raise ValueError("too many redirects")


def run(*, apply: bool) -> dict[str, object]:
    db = SessionLocal()
    storage = MinioStorageService() if apply else None
    report: dict[str, object] = {"mode": "apply" if apply else "dry-run", "migrated": [], "failed": []}
    try:
        items = db.scalars(
            select(Inspiration).where(
                Inspiration.deleted_at.is_(None),
                Inspiration.image_object_key.is_(None),
            )
        ).all()
        with httpx.Client(timeout=30, follow_redirects=False) as client:
            for item in items:
                try:
                    image_bytes, content_type, _ = _download(client, item.image_url)
                    if not apply:
                        report["migrated"].append({"id": item.id, "bytes": len(image_bytes), "dry_run": True})
                        continue
                    assert storage is not None
                    stored = storage.upload_inspiration_image(item.id, image_bytes, content_type)
                    item.image_object_key = stored.object_key
                    item.image_url = f"/api/v1/inspirations/{item.id}/file"
                    item.media_state = MediaState.AVAILABLE
                    item.media_size_bytes = len(image_bytes)
                    item.media_content_type = content_type
                    try:
                        db.commit()
                    except Exception:
                        db.rollback()
                        storage.delete_object(stored.object_key)
                        raise
                    report["migrated"].append({"id": item.id, "bytes": len(image_bytes)})
                except (httpx.HTTPError, OSError, ValueError, ReferenceImageValidationError, StorageError) as exc:
                    db.rollback()
                    report["failed"].append({"id": item.id, "url": item.image_url, "error": str(exc)})
        report["total"] = len(items)
        return report
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="upload and update rows; default is dry-run")
    parser.add_argument("--report", type=Path, help="write the JSON report to this path")
    args = parser.parse_args()
    report = run(apply=args.apply)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        args.report.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
