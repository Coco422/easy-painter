from __future__ import annotations

import logging
import re

from app.core.config import get_settings


class RedactSecretsFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        settings = get_settings()

        def redact(message: str) -> str:
            for secret in (settings.upstream_base_url, settings.upstream_api_key, settings.zpay_key.get_secret_value(), settings.payment_config_encryption_key.get_secret_value()):
                if secret:
                    message = message.replace(secret, "[REDACTED]")
            # Dashboard credentials are decrypted on demand, not in Settings.
            return re.sub(r'([?&](?:key|sign)=)[^&\s\"\']+', r'\1[REDACTED]', message)

        if record.name == "uvicorn.access" and isinstance(record.args, tuple) and len(record.args) == 5:
            # AccessFormatter unpacks this structured tuple even after filtering.
            # Keep its shape and redact only the request target.
            client, method, target, version, code = record.args
            record.args = (client, method, redact(str(target)), version, code)
        else:
            record.msg = redact(record.getMessage())
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
