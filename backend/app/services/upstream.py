from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from io import BytesIO

import httpx

from app.core.config import get_settings


logger = logging.getLogger(__name__)


class UpstreamServiceError(RuntimeError):
    def __init__(self, user_message: str, *, retryable: bool) -> None:
        super().__init__(user_message)
        self.user_message = user_message
        self.retryable = retryable


@dataclass(slots=True)
class GeneratedImageResult:
    image_bytes: bytes
    content_type: str
    revised_prompt: str | None
    provider_meta: dict[str, int | str | None]


@dataclass(slots=True)
class ReferenceImageForUpstream:
    filename: str
    content_type: str
    image_bytes: bytes


class UpstreamImageClient:
    def __init__(self) -> None:
        self.settings = get_settings()

    def generate_image(
        self,
        prompt: str,
        model: str,
        size: str | None = None,
        aspect_ratio: str | None = None,
        reference_image: ReferenceImageForUpstream | None = None,
    ) -> GeneratedImageResult:
        if not self.settings.upstream_base_url or not self.settings.upstream_api_key:
            raise UpstreamServiceError("生成服务尚未配置完成。", retryable=False)

        request_payload = self._generation_payload(prompt=prompt, model=model, size=size, aspect_ratio=aspect_ratio)
        headers = {
            "Authorization": f"Bearer {self.settings.upstream_api_key}",
            "Content-Type": "application/json",
        }
        endpoint = f"{self.settings.upstream_base_url.rstrip('/')}/images/generations"
        request_kwargs = {"json": request_payload, "headers": headers}
        if reference_image:
            endpoint = f"{self.settings.upstream_base_url.rstrip('/')}/images/edits"
            request_kwargs = {
                "data": {
                    key: self._form_value(value)
                    for key, value in self._edit_payload(request_payload, model=model).items()
                },
                "headers": {"Authorization": headers["Authorization"]},
                "files": {
                    "image": (
                        reference_image.filename,
                        BytesIO(reference_image.image_bytes),
                        reference_image.content_type,
                    )
                },
            }

        try:
            with httpx.Client(timeout=self.settings.upstream_timeout_seconds) as client:
                response = client.post(endpoint, **request_kwargs)
        except httpx.TimeoutException as exc:
            raise UpstreamServiceError("生成服务响应超时，请稍后再试。", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise UpstreamServiceError("生成服务暂时不可用，请稍后再试。", retryable=True) from exc

        if response.status_code >= 500:
            logger.warning(
                "Upstream image generation failed with %s for model=%s size=%s.",
                response.status_code,
                model,
                request_payload["size"],
            )
            raise UpstreamServiceError("生成服务暂时不可用，请稍后再试。", retryable=True)
        if response.status_code >= 400:
            logger.warning(
                "Upstream image generation rejected request with %s for model=%s size=%s.",
                response.status_code,
                model,
                request_payload["size"],
            )
            raise UpstreamServiceError("生成请求未能完成，请稍后调整提示词再试。", retryable=False)

        try:
            response_payload = response.json()
            image_data = response_payload["data"][0]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise UpstreamServiceError("生成服务返回了无法识别的数据。", retryable=True) from exc

        revised_prompt = image_data.get("revised_prompt")
        created = response_payload.get("created")

        if image_data.get("b64_json"):
            image_bytes = base64.b64decode(image_data["b64_json"])
            content_type = self._content_type_for_bytes(image_bytes)
            source_type = "b64_json"
        elif image_data.get("url"):
            image_bytes, content_type = self._download_image(image_data["url"])
            source_type = "url"
        else:
            raise UpstreamServiceError("生成服务未返回图像数据。", retryable=True)

        logger.info(
            "Upstream image generation succeeded model=%s size=%s source=%s bytes=%s.",
            model,
            request_payload["size"],
            source_type,
            len(image_bytes),
        )

        return GeneratedImageResult(
            image_bytes=image_bytes,
            content_type=content_type,
            revised_prompt=revised_prompt,
            provider_meta={
                "created": created,
                "model": model,
                "size": request_payload["size"],
            },
        )

    def _generation_payload(
        self,
        *,
        prompt: str,
        model: str,
        size: str | None,
        aspect_ratio: str | None,
    ) -> dict[str, int | str | bool]:
        payload: dict[str, int | str | bool] = {
            "model": model,
            "prompt": prompt,
            "n": 1,
            "size": self._resolve_size(size=size, aspect_ratio=aspect_ratio),
            "quality": self.settings.upstream_default_quality,
            "output_format": self.settings.upstream_default_output_format,
            "output_compression": self.settings.upstream_default_output_compression,
            "background": self.settings.upstream_default_background,
            "moderation": self.settings.upstream_default_moderation,
            "stream": False,
            "partial_images": 0,
        }
        if self._is_doubao_seedream(model):
            payload["watermark"] = False
        return payload

    def _edit_payload(self, request_payload: dict[str, int | str | bool], *, model: str) -> dict[str, int | str | bool]:
        if not self._is_doubao_seedream(model):
            return request_payload

        return {
            "model": request_payload["model"],
            "prompt": request_payload["prompt"],
            "size": request_payload["size"],
            "watermark": False,
        }

    @staticmethod
    def _is_doubao_seedream(model: str) -> bool:
        return model.startswith("doubao-seedream-")

    def _resolve_size(self, *, size: str | None, aspect_ratio: str | None = None) -> str:
        if size and size != "auto":
            return size
        if aspect_ratio and aspect_ratio != "auto":
            return self._size_for_aspect_ratio(aspect_ratio)
        if size:
            return size
        return self._size_for_aspect_ratio(aspect_ratio or "auto")

    def _size_for_aspect_ratio(self, aspect_ratio: str) -> str:
        if aspect_ratio == "auto":
            return "auto"

        sizes = {
            "1:1": "1024x1024",
            "3:4": "1024x1536",
            "9:16": "1024x1792",
            "4:3": "1536x1024",
            "16:9": "1792x1024",
        }
        return sizes.get(aspect_ratio, self.settings.upstream_default_size)

    @staticmethod
    def _form_value(value: object) -> str:
        if isinstance(value, bool):
            return str(value).lower()
        return str(value)

    def _download_image(self, image_url: str) -> tuple[bytes, str]:
        try:
            with httpx.Client(timeout=self.settings.upstream_timeout_seconds) as client:
                response = client.get(image_url)
                response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise UpstreamServiceError("生成服务响应超时，请稍后再试。", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise UpstreamServiceError("生成图像下载失败，请稍后再试。", retryable=True) from exc

        return response.content, response.headers.get("content-type", "image/jpeg")

    @staticmethod
    def _content_type_for_bytes(image_bytes: bytes) -> str:
        if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if image_bytes.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"
        if image_bytes.startswith(b"RIFF") and image_bytes[8:12] == b"WEBP":
            return "image/webp"
        return "application/octet-stream"

    @staticmethod
    def _content_type_for_format(output_format: str) -> str:
        normalized = output_format.lower()
        if normalized == "png":
            return "image/png"
        if normalized == "webp":
            return "image/webp"
        return "image/jpeg"
