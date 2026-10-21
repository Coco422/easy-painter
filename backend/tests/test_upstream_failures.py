import httpx
import pytest

from app.services.upstream import UpstreamImageClient, UpstreamServiceError


def _install_fake_client(monkeypatch, status_code: int, body: str = "") -> dict:
    captured = {}

    class FakeResponse:
        def __init__(self) -> None:
            self.status_code = status_code
            self.text = body
            self.headers = {"content-type": "application/json"}

        def json(self):
            raise AssertionError("error responses must not be parsed")

    class FakeClient:
        def __init__(self, timeout):
            captured["timeout"] = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, endpoint, **kwargs):
            captured["endpoint"] = endpoint
            captured["kwargs"] = kwargs
            return FakeResponse()

    monkeypatch.setattr("app.services.upstream.httpx.Client", FakeClient)
    return captured


def _generate(monkeypatch, status_code: int, body: str = ""):
    captured = _install_fake_client(monkeypatch, status_code, body)
    client = UpstreamImageClient({"base_url": "https://upstream.example.com/v1", "api_key": "test-key"})
    with pytest.raises(UpstreamServiceError) as exc_info:
        client.generate_image(prompt="画一朵花", model="gpt-image-2", size="1024x1024")
    return captured, exc_info.value


def test_upstream_quota_429_is_reported_as_quota_and_not_retried(monkeypatch):
    captured, error = _generate(monkeypatch, 429, '{"error":{"message":"no available image quota"}}')

    assert error.retryable is False
    assert error.failover_safe is True
    assert "额度" in error.user_message
    assert captured["endpoint"] == "https://upstream.example.com/v1/images/generations"


def test_upstream_auth_failure_is_reported_as_configuration_error(monkeypatch):
    for status_code in (401, 403):
        _, error = _generate(monkeypatch, status_code, '{"error":{"message":"invalid api key"}}')

        assert error.retryable is False
        assert error.failover_safe is True
        assert "配置" in error.user_message


def test_upstream_server_error_stays_retryable(monkeypatch):
    for status_code in (500, 502, 503, 525):
        _, error = _generate(monkeypatch, status_code, "error code: 525")

        assert error.retryable is True
        assert error.failover_safe is True


def test_upstream_client_error_keeps_request_message(monkeypatch):
    _, error = _generate(monkeypatch, 400, '{"error":{"message":"prompt is required"}}')

    assert error.retryable is False
    assert error.failover_safe is True
    assert "提示词" in error.user_message


def test_upstream_timeout_only_allows_failover_when_connection_never_started(monkeypatch):
    class TimeoutClient:
        def __init__(self, timeout):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, endpoint, **kwargs):
            raise httpx.ReadTimeout("response timed out")

    monkeypatch.setattr("app.services.upstream.httpx.Client", TimeoutClient)
    with pytest.raises(UpstreamServiceError) as exc_info:
        UpstreamImageClient({"base_url": "https://test.example.com/v1", "api_key": "test-key"}).generate_image(
            prompt="hello", model="gpt-image-2", size="1024x1024",
        )

    assert exc_info.value.retryable is True
    assert exc_info.value.failover_safe is False


def test_error_snippet_collapses_whitespace_and_bounds_length():
    class FakeResponse:
        text = "  detail: \n\tModel not found  " + "x" * 500

    snippet = UpstreamImageClient._error_snippet(FakeResponse())

    assert snippet.startswith("detail: Model not found")
    assert "\n" not in snippet and "\t" not in snippet
    assert len(snippet) == 300
