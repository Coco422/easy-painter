import pytest
from pydantic import ValidationError

from app.schemas.job import CreateJobRequest
from app.services.upstream import UpstreamImageClient


def test_create_job_request_accepts_official_size_parameter():
    payload = CreateJobRequest(prompt="画一朵花", model="gpt-image-2", size="3840x2160")

    assert payload.size == "3840x2160"


def test_create_job_request_rejects_size_outside_official_constraints():
    with pytest.raises(ValidationError):
        CreateJobRequest(prompt="画一朵花", model="gpt-image-2", size="4096x4096")


def test_create_job_request_maps_legacy_aspect_ratio_to_size():
    payload = CreateJobRequest(prompt="画一朵花", model="gpt-image-2", aspect_ratio="9:16")

    assert payload.size == "1024x1792"


TEST_PROVIDER_CONFIG = {"base_url": "https://test.example.com", "api_key": "test-key"}


def test_upstream_uses_size_parameter_directly():
    client = UpstreamImageClient(TEST_PROVIDER_CONFIG)

    assert client._resolve_size(size="3840x2160") == "3840x2160"


def test_upstream_falls_back_to_legacy_aspect_ratio_when_size_is_auto():
    client = UpstreamImageClient(TEST_PROVIDER_CONFIG)

    assert client._resolve_size(size="auto", aspect_ratio="9:16") == "1024x1792"


def test_upstream_size_matches_legacy_aspect_ratio():
    client = UpstreamImageClient(TEST_PROVIDER_CONFIG)

    assert client._size_for_aspect_ratio("auto") == "auto"
    assert client._size_for_aspect_ratio("1:1") == "1024x1024"
    assert client._size_for_aspect_ratio("3:4") == "1024x1536"
    assert client._size_for_aspect_ratio("9:16") == "1024x1792"
    assert client._size_for_aspect_ratio("4:3") == "1536x1024"
    assert client._size_for_aspect_ratio("16:9") == "1792x1024"


def test_upstream_content_type_uses_image_bytes():
    assert UpstreamImageClient._content_type_for_bytes(b"\x89PNG\r\n\x1a\n...") == "image/png"
    assert UpstreamImageClient._content_type_for_bytes(b"\xff\xd8\xff...") == "image/jpeg"
    assert UpstreamImageClient._content_type_for_bytes(b"RIFF....WEBP...") == "image/webp"
