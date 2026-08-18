import json

import httpx
import pytest

from app.core.config import Settings
from app.services.release_updates import (
    RELEASE_CACHE_KEY,
    RELEASE_FRESH_KEY,
    ReleaseLookupError,
    fetch_latest_release,
)


class FakeRedis:
    def __init__(self):
        self.data: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    def get(self, key):
        return self.data.get(key)

    def setex(self, key, ttl, value):
        self.data[key] = value
        self.ttls[key] = ttl


class FakeResponse:
    def __init__(self, status_code, payload=None, headers=None):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}
        self.is_success = 200 <= status_code < 300

    def json(self):
        return self._payload


class FakeClient:
    def __init__(self, response, requests):
        self.response = response
        self.requests = requests

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def get(self, url, headers):
        self.requests.append((url, headers))
        return self.response


def _release_payload():
    return {
        "tag_name": "v0.13.0",
        "body": "+ [修复] 修复版本检查",
        "html_url": "https://github.com/Coco422/easy-painter/releases/tag/v0.13.0",
        "published_at": "2026-08-18T00:00:00Z",
    }


def _install_client(monkeypatch, response, requests):
    monkeypatch.setattr(
        "app.services.release_updates.httpx.Client",
        lambda **_kwargs: FakeClient(response, requests),
    )


def test_release_lookup_fetches_and_caches_response(monkeypatch):
    redis = FakeRedis()
    requests = []
    _install_client(monkeypatch, FakeResponse(200, _release_payload(), {"etag": '"release-1"'}), requests)

    first = fetch_latest_release(redis, Settings())
    second = fetch_latest_release(redis, Settings())

    assert first.cache_state == "refresh"
    assert second.cache_state == "hit"
    assert first.payload["status"] == "found"
    assert len(requests) == 1
    assert redis.ttls[RELEASE_FRESH_KEY] == 3600
    assert json.loads(redis.data[RELEASE_CACHE_KEY])["etag"] == '"release-1"'


def test_release_lookup_revalidates_with_etag(monkeypatch):
    redis = FakeRedis()
    requests = []
    _install_client(monkeypatch, FakeResponse(200, _release_payload(), {"etag": '"release-1"'}), requests)
    expected = fetch_latest_release(redis, Settings()).payload
    redis.data.pop(RELEASE_FRESH_KEY)
    _install_client(monkeypatch, FakeResponse(304), requests)

    result = fetch_latest_release(redis, Settings())

    assert result.cache_state == "revalidated"
    assert result.payload == expected
    assert requests[-1][1]["If-None-Match"] == '"release-1"'


def test_release_lookup_serves_stale_cache_when_github_is_limited(monkeypatch):
    redis = FakeRedis()
    requests = []
    _install_client(monkeypatch, FakeResponse(200, _release_payload()), requests)
    expected = fetch_latest_release(redis, Settings()).payload
    redis.data.pop(RELEASE_FRESH_KEY)
    _install_client(monkeypatch, FakeResponse(403), requests)

    result = fetch_latest_release(redis, Settings())

    assert result.cache_state == "stale"
    assert result.payload == expected
    assert redis.ttls[RELEASE_FRESH_KEY] == 300


def test_release_lookup_raises_without_cache(monkeypatch):
    redis = FakeRedis()
    _install_client(monkeypatch, FakeResponse(403), [])

    with pytest.raises(ReleaseLookupError):
        fetch_latest_release(redis, Settings())


def test_release_lookup_converts_network_errors_to_service_error(monkeypatch):
    class FailingClient:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def get(self, *_args, **_kwargs):
            raise httpx.ConnectError("offline")

    monkeypatch.setattr("app.services.release_updates.httpx.Client", lambda **_kwargs: FailingClient())

    with pytest.raises(ReleaseLookupError):
        fetch_latest_release(FakeRedis(), Settings())
