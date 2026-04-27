from __future__ import annotations

from dataclasses import dataclass


ALLOWED_REFERENCE_IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp"}
MAX_REFERENCE_IMAGE_BYTES = 10 * 1024 * 1024


class ReferenceImageValidationError(ValueError):
    pass


@dataclass(slots=True)
class ReferenceImagePayload:
    filename: str
    content_type: str
    image_bytes: bytes


def validate_reference_image(*, filename: str | None, content_type: str | None, image_bytes: bytes) -> ReferenceImagePayload:
    normalized_content_type = (content_type or "").split(";")[0].strip().lower()
    if normalized_content_type not in ALLOWED_REFERENCE_IMAGE_TYPES:
        raise ReferenceImageValidationError("参考图仅支持 PNG、JPEG 或 WebP。")
    if not image_bytes:
        raise ReferenceImageValidationError("参考图不能为空。")
    if len(image_bytes) > MAX_REFERENCE_IMAGE_BYTES:
        raise ReferenceImageValidationError("参考图不能超过 10MB。")

    safe_filename = (filename or "reference").replace("/", "_").replace("\\", "_")
    return ReferenceImagePayload(
        filename=safe_filename,
        content_type=normalized_content_type,
        image_bytes=image_bytes,
    )
