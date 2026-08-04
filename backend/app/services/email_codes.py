from __future__ import annotations

import hashlib
import hmac

from redis import Redis

from app.core.config import Settings
from app.schemas.auth import EmailCodePurpose
from app.services.rate_limit import GenerationRateLimiter


def normalize_email(email: str) -> str:
    return email.strip().lower()


def email_identity(email: str) -> str:
    return hashlib.sha256(normalize_email(email).encode("utf-8")).hexdigest()


def _subject_suffix(subject: str | None) -> str:
    if not subject:
        return ""
    digest = hashlib.sha256(subject.encode("utf-8")).hexdigest()[:32]
    return f":subject:{digest}"


def _code_key(email: str, purpose: EmailCodePurpose, subject: str | None = None) -> str:
    return f"auth:email-code:{purpose.value}:{email_identity(email)}{_subject_suffix(subject)}"


def _attempt_key(email: str, purpose: EmailCodePurpose, subject: str | None = None) -> str:
    return f"auth:email-code-attempts:{purpose.value}:{email_identity(email)}{_subject_suffix(subject)}"


def _cooldown_key(email: str) -> str:
    return f"auth:email-code-cooldown:{email_identity(email)}"


class EmailCodeRateLimitExceeded(RuntimeError):
    def __init__(self, retry_after: int) -> None:
        self.retry_after = max(1, retry_after)
        super().__init__(f"email code rate limit exceeded; retry after {self.retry_after}s")


def enforce_email_code_send_limits(
    redis_client: Redis,
    settings: Settings,
    *,
    email: str,
    ip_identity: str,
    user_id: str | None = None,
) -> None:
    cooldown_key = _cooldown_key(email)
    claimed = redis_client.set(
        cooldown_key,
        "1",
        ex=settings.email_code_cooldown_seconds,
        nx=True,
    )
    if not claimed:
        raise EmailCodeRateLimitExceeded(settings.email_code_cooldown_seconds)

    email_id = email_identity(email)
    checks = [
        (
            GenerationRateLimiter(
                redis_client,
                settings.email_code_rate_limit_count,
                settings.email_code_rate_limit_window_seconds,
                namespace="email-code-email-short",
            ),
            email_id,
            settings.email_code_rate_limit_window_seconds,
        ),
        (
            GenerationRateLimiter(
                redis_client,
                settings.email_code_daily_limit_count,
                settings.email_code_daily_limit_window_seconds,
                namespace="email-code-email-daily",
            ),
            email_id,
            settings.email_code_daily_limit_window_seconds,
        ),
        (
            GenerationRateLimiter(
                redis_client,
                settings.email_code_ip_rate_limit_count,
                settings.email_code_rate_limit_window_seconds,
                namespace="email-code-ip-short",
            ),
            ip_identity,
            settings.email_code_rate_limit_window_seconds,
        ),
        (
            GenerationRateLimiter(
                redis_client,
                settings.email_code_ip_daily_limit_count,
                settings.email_code_daily_limit_window_seconds,
                namespace="email-code-ip-daily",
            ),
            ip_identity,
            settings.email_code_daily_limit_window_seconds,
        ),
    ]
    if user_id:
        checks.extend([
            (
                GenerationRateLimiter(
                    redis_client,
                    settings.email_code_rate_limit_count,
                    settings.email_code_rate_limit_window_seconds,
                    namespace="email-code-user-short",
                ),
                user_id,
                settings.email_code_rate_limit_window_seconds,
            ),
            (
                GenerationRateLimiter(
                    redis_client,
                    settings.email_code_daily_limit_count,
                    settings.email_code_daily_limit_window_seconds,
                    namespace="email-code-user-daily",
                ),
                user_id,
                settings.email_code_daily_limit_window_seconds,
            ),
        ])

    for limiter, identity, retry_after in checks:
        if not limiter.check(identity).allowed:
            redis_client.delete(cooldown_key)
            raise EmailCodeRateLimitExceeded(retry_after)


def release_email_code_cooldown(redis_client: Redis, *, email: str) -> None:
    redis_client.delete(_cooldown_key(email))


def _hash_code(code: str, settings: Settings) -> str:
    return hmac.new(
        settings.jwt_secret_key.encode("utf-8"),
        code.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def store_email_code(
    redis_client: Redis,
    settings: Settings,
    *,
    email: str,
    purpose: EmailCodePurpose,
    code: str,
    subject: str | None = None,
) -> None:
    redis_client.setex(
        _code_key(email, purpose, subject),
        settings.email_code_expire_seconds,
        _hash_code(code, settings),
    )
    redis_client.delete(_attempt_key(email, purpose, subject))


def verify_email_code(
    redis_client: Redis,
    settings: Settings,
    *,
    email: str,
    purpose: EmailCodePurpose,
    code: str,
    subject: str | None = None,
) -> bool:
    stored = redis_client.get(_code_key(email, purpose, subject))
    if not stored:
        return False
    stored_hash = stored.decode("utf-8") if isinstance(stored, bytes) else str(stored)
    if hmac.compare_digest(stored_hash, _hash_code(code, settings)):
        return True

    attempt_key = _attempt_key(email, purpose, subject)
    attempts = redis_client.incr(attempt_key)
    if attempts == 1:
        redis_client.expire(attempt_key, settings.email_code_expire_seconds)
    if attempts >= 5:
        redis_client.delete(_code_key(email, purpose, subject))
    return False


def consume_email_code(
    redis_client: Redis,
    *,
    email: str,
    purpose: EmailCodePurpose,
    subject: str | None = None,
) -> None:
    redis_client.delete(_code_key(email, purpose, subject), _attempt_key(email, purpose, subject))
