from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Literal

import httpx
from redis import Redis
from redis.exceptions import RedisError

from app.core.config import Settings


logger = logging.getLogger(__name__)

GITHUB_LATEST_RELEASE_URL = "https://api.github.com/repos/Coco422/easy-painter/releases/latest"
REPOSITORY_RELEASE_URL_PREFIX = "https://github.com/Coco422/easy-painter/releases/tag/"
RELEASE_CACHE_KEY = "release:github:latest:v1"
RELEASE_FRESH_KEY = "release:github:latest:fresh:v1"
RELEASE_CACHE_SECONDS = 3600
RELEASE_STALE_SECONDS = 7 * 24 * 3600
RELEASE_ERROR_BACKOFF_SECONDS = 300
STABLE_SEMVER_PATTERN = re.compile(r"^v(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)$")


class ReleaseLookupError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ReleaseLookupResult:
    payload: dict[str, object]
    cache_state: Literal["hit", "refresh", "revalidated", "stale"]


def _read_cache(redis_client: Redis) -> dict[str, object] | None:
    try:
        value = redis_client.get(RELEASE_CACHE_KEY)
    except RedisError:
        logger.warning("Unable to read the GitHub release cache", exc_info=True)
        return None
    if not value:
        return None
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        logger.warning("Ignoring an invalid GitHub release cache entry")
        return None
    return parsed if isinstance(parsed, dict) else None


def _is_fresh(redis_client: Redis) -> bool:
    try:
        return bool(redis_client.get(RELEASE_FRESH_KEY))
    except RedisError:
        logger.warning("Unable to read GitHub release cache freshness", exc_info=True)
        return False


def _mark_fresh(redis_client: Redis, ttl: int = RELEASE_CACHE_SECONDS) -> None:
    try:
        redis_client.setex(RELEASE_FRESH_KEY, ttl, "1")
    except RedisError:
        logger.warning("Unable to mark the GitHub release cache as fresh", exc_info=True)


def _write_cache(redis_client: Redis, envelope: dict[str, object]) -> None:
    try:
        redis_client.setex(RELEASE_CACHE_KEY, RELEASE_STALE_SECONDS, json.dumps(envelope))
        _mark_fresh(redis_client)
    except RedisError:
        logger.warning("Unable to write the GitHub release cache", exc_info=True)


def _cached_payload(envelope: dict[str, object] | None) -> dict[str, object] | None:
    if not envelope:
        return None
    payload = envelope.get("payload")
    return payload if isinstance(payload, dict) else None


def _normalize_release(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise ReleaseLookupError("GitHub returned an invalid release response")

    version = payload.get("tag_name")
    url = payload.get("html_url")
    if not isinstance(version, str) or not STABLE_SEMVER_PATTERN.fullmatch(version.strip()):
        raise ReleaseLookupError("GitHub returned an invalid release version")
    if not isinstance(url, str) or not url.startswith(REPOSITORY_RELEASE_URL_PREFIX):
        raise ReleaseLookupError("GitHub returned an invalid release URL")

    return {
        "status": "found",
        "release": {
            "tag_name": version.strip(),
            "body": payload.get("body") if isinstance(payload.get("body"), str) else "",
            "html_url": url,
            "published_at": payload.get("published_at") if isinstance(payload.get("published_at"), str) else "",
        },
    }


def fetch_latest_release(redis_client: Redis, settings: Settings) -> ReleaseLookupResult:
    cached = _read_cache(redis_client)
    cached_payload = _cached_payload(cached)
    if cached_payload is not None and _is_fresh(redis_client):
        return ReleaseLookupResult(payload=cached_payload, cache_state="hit")

    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "easy-painter-release-checker",
    }
    etag = cached.get("etag") if cached else None
    if isinstance(etag, str) and etag:
        headers["If-None-Match"] = etag
    if settings.github_api_token:
        headers["Authorization"] = f"Bearer {settings.github_api_token}"

    try:
        with httpx.Client(timeout=8.0) as client:
            response = client.get(GITHUB_LATEST_RELEASE_URL, headers=headers)

        if response.status_code == 304 and cached_payload is not None:
            _mark_fresh(redis_client)
            return ReleaseLookupResult(payload=cached_payload, cache_state="revalidated")

        if response.status_code == 404:
            payload: dict[str, object] = {"status": "none"}
        elif response.is_success:
            payload = _normalize_release(response.json())
        else:
            raise ReleaseLookupError(f"GitHub release request failed with {response.status_code}")

        _write_cache(
            redis_client,
            {"payload": payload, "etag": response.headers.get("etag", "")},
        )
        return ReleaseLookupResult(payload=payload, cache_state="refresh")
    except (httpx.HTTPError, ValueError, ReleaseLookupError) as exc:
        if cached_payload is not None:
            logger.warning("GitHub release refresh failed; serving stale cache: %s", exc)
            _mark_fresh(redis_client, RELEASE_ERROR_BACKOFF_SECONDS)
            return ReleaseLookupResult(payload=cached_payload, cache_state="stale")
        raise ReleaseLookupError("Unable to retrieve GitHub release information") from exc
