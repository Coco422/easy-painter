import pytest
from pydantic import ValidationError

from app.schemas.job import CreateJobRequest
from app.services.upstream import UpstreamImageClient


def test_create_job_request_accepts_supported_aspect_ratios():
    payload = CreateJobRequest(prompt="画一朵花", model="gpt-image-2", aspect_ratio="9:16")

    assert payload.aspect_ratio == "9:16"


def test_create_job_request_rejects_unsupported_aspect_ratio():
    with pytest.raises(ValidationError):
        CreateJobRequest(prompt="画一朵花", model="gpt-image-2", aspect_ratio="2:1")


def test_upstream_size_matches_selected_aspect_ratio():
    client = UpstreamImageClient()

    assert client._size_for_aspect_ratio("auto") == "auto"
    assert client._size_for_aspect_ratio("1:1") == "1024x1024"
    assert client._size_for_aspect_ratio("3:4") == "1024x1536"
    assert client._size_for_aspect_ratio("9:16") == "1024x1792"
    assert client._size_for_aspect_ratio("4:3") == "1536x1024"
    assert client._size_for_aspect_ratio("16:9") == "1792x1024"
