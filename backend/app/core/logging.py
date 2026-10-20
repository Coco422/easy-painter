from __future__ import annotations

import logging
import re

from app.core.config import get_settings


class RedactSecretsFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        settings = get_settings()
        message = record.getMessage()
        for secret in (settings.upstream_base_url, settings.upstream_api_key, settings.zpay_key.get_secret_value(), settings.payment_config_encryption_key.get_secret_value()):
            if secret:
                message = message.replace(secret, "[REDACTED]")
        # Dashboard-managed credentials are decrypted on demand, not in Settings.
        message = re.sub(r'([?&](?:key|sign)=)[^&\s\"\']+', r'\1[REDACTED]', message)
        record.msg = message
        record.args = ()
        return True


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    secret_filter = RedactSecretsFilter()
    # Celery may replace root handlers after task imports. Filter httpx at its
    # source too: the ZPAY v1 query protocol carries a merchant key in the URL.
    for name in ("httpx", "uvicorn.access"):
        logger = logging.getLogger(name)
        if not any(isinstance(item, RedactSecretsFilter) for item in logger.filters):
            logger.addFilter(secret_filter)
    for handler in logging.getLogger().handlers:
        handler.addFilter(secret_filter)
