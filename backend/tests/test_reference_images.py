import pytest
from starlette.requests import Request

from app.api.routes import _parse_create_job_payload
from app.services.reference_images import ReferenceImageValidationError, validate_reference_image
from app.services.upstream import ReferenceImageForUpstream, UpstreamImageClient


def make_request(*, content_type: str, body: bytes) -> Request:
    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/jobs",
            "headers": [(b"content-type", content_type.encode())],
        },
        receive,
    )


@pytest.mark.anyio
async def test_parse_json_create_job_payload():
    request = make_request(
        content_type="application/json",
        body=b'{"prompt":"hello","model":"gpt-image-2-c","size":"3840x2160"}',
    )

    payload = await _parse_create_job_payload(request)

    assert payload.request.prompt == "hello"
    assert payload.request.model == "gpt-image-2-c"
    assert payload.request.size == "3840x2160"
    assert payload.reference_image is None


@pytest.mark.anyio
async def test_parse_multipart_create_job_payload_with_reference_image():
    boundary = "----easy-painter-test"
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="prompt"\r\n\r\n'
        "hello\r\n"
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="model"\r\n\r\n'
        "gpt-image-2-c\r\n"
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="size"\r\n\r\n'
        "2160x3840\r\n"
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="reference_image"; filename="sample.png"\r\n'
        "Content-Type: image/png\r\n\r\n"
    ).encode() + b"\x89PNG\r\n\x1a\nsample\r\n" + f"--{boundary}--\r\n".encode()
    request = make_request(content_type=f"multipart/form-data; boundary={boundary}", body=body)

    payload = await _parse_create_job_payload(request)

    assert payload.request.prompt == "hello"
    assert payload.request.model == "gpt-image-2-c"
    assert payload.request.size == "2160x3840"
    assert payload.reference_image is not None
    assert payload.reference_image.filename == "sample.png"
    assert payload.reference_image.content_type == "image/png"


def test_validate_reference_image_accepts_supported_png():
    payload = validate_reference_image(
        filename="sample.png",
        content_type="image/png",
        image_bytes=b"\x89PNG\r\n\x1a\nsample",
    )

    assert payload.filename == "sample.png"
    assert payload.content_type == "image/png"
    assert payload.image_bytes == b"\x89PNG\r\n\x1a\nsample"


def test_validate_reference_image_rejects_unsupported_content_type():
    with pytest.raises(ReferenceImageValidationError):
        validate_reference_image(
            filename="sample.gif",
            content_type="image/gif",
            image_bytes=b"GIF89a",
        )


def test_validate_reference_image_rejects_large_file():
    with pytest.raises(ReferenceImageValidationError):
        validate_reference_image(
            filename="sample.png",
            content_type="image/png",
            image_bytes=b"x" * (10 * 1024 * 1024 + 1),
        )


def test_upstream_uses_edits_endpoint_for_reference_image(monkeypatch):
    captured = {}

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "created": 1,
                "data": [{"b64_json": "iVBORw0KGgpzYW1wbGU="}],
            }

    class FakeClient:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, endpoint, **kwargs):
            captured["endpoint"] = endpoint
            captured["kwargs"] = kwargs
            return FakeResponse()

    monkeypatch.setattr("app.services.upstream.httpx.Client", FakeClient)

    result = UpstreamImageClient().generate_image(
        prompt="画一朵花",
        model="gpt-image-2-c",
        reference_image=ReferenceImageForUpstream(
            filename="sample.png",
            content_type="image/png",
            image_bytes=b"\x89PNG\r\n\x1a\nsample",
        ),
    )

    assert captured["endpoint"].endswith("/images/edits")
    assert "files" in captured["kwargs"]
    assert captured["kwargs"]["files"]["image"][0] == "sample.png"
    assert captured["kwargs"]["data"]["prompt"] == "画一朵花"
    assert captured["kwargs"]["data"]["size"] == "auto"
    assert captured["kwargs"]["data"]["stream"] == "false"
    assert result.content_type == "image/png"


def test_upstream_uses_generations_endpoint_without_reference_image(monkeypatch):
    captured = {}

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "created": 1,
                "data": [{"b64_json": "iVBORw0KGgpzYW1wbGU="}],
            }

    class FakeClient:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, endpoint, **kwargs):
            captured["endpoint"] = endpoint
            captured["kwargs"] = kwargs
            return FakeResponse()

    monkeypatch.setattr("app.services.upstream.httpx.Client", FakeClient)

    UpstreamImageClient().generate_image(prompt="画一朵花", model="gpt-image-2-c")

    assert captured["endpoint"].endswith("/images/generations")
    assert "json" in captured["kwargs"]
    assert "files" not in captured["kwargs"]
    assert captured["kwargs"]["json"]["size"] == "auto"
