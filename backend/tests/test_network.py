from types import SimpleNamespace

from app.core.network import extract_client_ip, rate_limit_identity
from app.services.rate_limit import GenerationRateLimiter


class DummyRequest:
    def __init__(self, headers, client_host="127.0.0.1"):
        self.headers = headers
        self.client = SimpleNamespace(host=client_host)


class FakeRedis:
    def __init__(self):
        self.data = {}
        self.expiry = {}

    def incr(self, key):
        self.data[key] = self.data.get(key, 0) + 1
        return self.data[key]

    def expire(self, key, ttl):
        self.expiry[key] = ttl


def test_extract_client_ip_uses_cloudflare_header_first():
    request = DummyRequest(
        headers={
            "cf-connecting-ip": "8.8.8.8",
            "x-forwarded-for": "1.1.1.1, 2.2.2.2",
        }
    )

    assert extract_client_ip(request) == "8.8.8.8"


def test_extract_client_ip_uses_first_forwarded_address():
    request = DummyRequest(headers={"x-forwarded-for": "1.1.1.1, 2.2.2.2"})

    assert extract_client_ip(request) == "1.1.1.1"


def test_rate_limit_identity_is_stable_and_not_raw_ip():
    identity = rate_limit_identity("1.2.3.4")

    assert identity == rate_limit_identity("1.2.3.4")
    assert identity != "1.2.3.4"
    assert len(identity) == 32


def test_generation_rate_limiter_blocks_after_limit():
    limiter = GenerationRateLimiter(redis_client=FakeRedis(), limit=2, window_seconds=60)

    first = limiter.check("abc")
    second = limiter.check("abc")
    third = limiter.check("abc")

    assert first.allowed is True
    assert second.allowed is True
    assert third.allowed is False
    assert third.remaining == 0
