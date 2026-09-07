import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.api.routes import _parse_create_job_payload, create_job
from app.core.config import Settings
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


@pytest.mark.anyio
async def test_create_job_rejects_prompt_over_configured_limit():
    request = make_request(
        content_type="application/json",
        body=b'{"prompt":"hello world","model":"gpt-image-2-c","size":"1024x1024"}',
    )

    with pytest.raises(HTTPException) as exc_info:
        await create_job(
            request,
            db=object(),
            redis_client=object(),
            settings=Settings(prompt_max_length=5),
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "提示词不能超过 5 个字符。"


@pytest.mark.anyio
async def test_create_job_rejects_reference_image_for_unsupported_model():
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
        "1024x1024\r\n"
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="reference_image"; filename="sample.png"\r\n'
        "Content-Type: image/png\r\n\r\n"
    ).encode() + b"\x89PNG\r\n\x1a\nsample\r\n" + f"--{boundary}--\r\n".encode()
    request = make_request(content_type=f"multipart/form-data; boundary={boundary}", body=body)

    with pytest.raises(HTTPException) as exc_info:
        await create_job(
            request,
            db=object(),
            redis_client=object(),
            settings=Settings(
                public_models_json=(
                    '[{"id":"gpt-image-2-c","label":"GPT-Image-2 C","enabled":true,'
                    '"supports_reference_image":false}]'
                ),
            ),
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "当前模型不支持参考图，请切换到支持参考图的模型。"


@pytest.mark.anyio
async def test_create_job_rejects_unsupported_model_size():
    request = make_request(
        content_type="application/json",
        body=b'{"prompt":"hello","model":"grok-4.1-image","size":"3840x2160"}',
    )

    with pytest.raises(HTTPException) as exc_info:
        await create_job(
            request,
            db=object(),
            redis_client=object(),
            settings=Settings(
                public_models_json=(
                    '[{"id":"grok-4.1-image","label":"Grok 4.1 Image","enabled":true,'
                    '"supports_reference_image":true,'
                    '"supported_sizes":["1024x1024","1280x720","1792x1024","720x1280","1024x1792"]}]'
                ),
            ),
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "当前模型不支持该尺寸，请切换尺寸或模型。"


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

    result = UpstreamImageClient({"base_url": "https://test.example.com", "api_key": "test-key"}).generate_image(
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


def test_upstream_uses_compact_edit_payload_for_doubao_reference_image(monkeypatch):
    captured = {}

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "created": 1,
                "data": [{"url": "https://example.com/sample.png"}],
            }

    class FakeDownloadResponse:
        content = b"\x89PNG\r\n\x1a\nsample"
        headers = {"content-type": "image/png"}

        def raise_for_status(self):
            return None

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

        def get(self, image_url):
            captured["download_url"] = image_url
            return FakeDownloadResponse()

    monkeypatch.setattr("app.services.upstream.httpx.Client", FakeClient)

    UpstreamImageClient({"base_url": "https://test.example.com", "api_key": "test-key"}).generate_image(
        prompt="画一朵花",
        model="doubao-seedream-5-0-260128",
        size="1024x1024",
        reference_image=ReferenceImageForUpstream(
            filename="sample.png",
            content_type="image/png",
            image_bytes=b"\x89PNG\r\n\x1a\nsample",
        ),
    )

    assert captured["endpoint"].endswith("/images/edits")
    assert captured["kwargs"]["data"] == {
        "model": "doubao-seedream-5-0-260128",
        "prompt": "画一朵花",
        "size": "1024x1024",
        "watermark": "false",
    }


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

    UpstreamImageClient({"base_url": "https://test.example.com", "api_key": "test-key"}).generate_image(prompt="画一朵花", model="gpt-image-2-c")

    assert captured["endpoint"].endswith("/images/generations")
    assert "json" in captured["kwargs"]
    assert "files" not in captured["kwargs"]
    assert captured["kwargs"]["json"]["size"] == "auto"


@pytest.mark.parametrize('model,field', [('gpt-image-2-b', 'image'), ('gpt-image-2-c', 'image'), ('doubao-seedream-5-0-260128', 'image[]')])
def test_multiple_reference_files_are_encoded_as_repeated_multipart_fields(monkeypatch, model, field):
    import httpx

    captured = []
    class FakeClient:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def post(self, endpoint, **kwargs):
            request = httpx.Request('POST', endpoint, **kwargs)
            captured.append(request.read())
            assert request.headers['content-type'].startswith('multipart/form-data; boundary=')
            assert endpoint.endswith('/images/edits')
            return httpx.Response(200, json={'data': [{'b64_json': 'iVBORw0KGgpzYW1wbGU='}]})
    monkeypatch.setattr('app.services.upstream.httpx.Client', FakeClient)
    UpstreamImageClient({'base_url': 'https://test.example.com/v1', 'api_key': 'test-key'}).generate_image(
        prompt='combine images in order', model=model,
        reference_images=[ReferenceImageForUpstream('same.png', 'image/png', data) for data in (b'FIRST_IMAGE', b'SECOND_IMAGE')],
    )
    [body] = captured
    assert body.count(f'name="{field}"; filename="same.png"'.encode()) == 2
    assert body.index(b'FIRST_IMAGE') < body.index(b'SECOND_IMAGE')


def test_reference_ids_reject_duplicates_and_mixed_legacy_fields():
    from pydantic import ValidationError
    from app.schemas.job import CreateJobRequest
    for fields in ({'reference_image_ids': ['a', 'a']}, {'reference_image_ids': [' ']}, {'reference_image_id': 'a', 'reference_image_ids': ['b']}):
        with pytest.raises(ValidationError):
            CreateJobRequest(prompt='test', model='test', **fields)


def test_reference_fingerprint_preserves_legacy_and_multi_image_order():
    from app.api.routes import ParsedCreateJobPayload, _job_request_fingerprint
    from app.schemas.job import CreateJobRequest
    def fingerprint(**kwargs):
        return _job_request_fingerprint(ParsedCreateJobPayload(request=CreateJobRequest(prompt='test', model='test', **kwargs)), 'test')
    assert fingerprint(reference_image_id='a') == fingerprint(reference_image_ids=['a'])
    assert fingerprint() == fingerprint(reference_image_ids=[])
    assert fingerprint(reference_image_ids=['a', 'b']) != fingerprint(reference_image_ids=['b', 'a'])


@pytest.mark.anyio
async def test_invalid_reference_ids_return_json_serializable_validation_error():
    import json
    request = make_request(content_type='application/json', body=b'{"prompt":"test","model":"test","reference_image_ids":["a","a"]}')
    with pytest.raises(HTTPException) as error:
        await _parse_create_job_payload(request)
    assert error.value.status_code == 422
    assert json.dumps(error.value.detail)
