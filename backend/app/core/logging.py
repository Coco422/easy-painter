from __future__ import annotations

import logging

from app.core.config import get_settings


class RedactSecretsFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        settings = get_settings()
        message = record.getMessage()
        for secret in (settings.upstream_base_url, settings.upstream_api_key):
            if secret:
                message = message.replace(secret, "[REDACTED]")
        record.msg = message
        record.args = ()
        return True


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    secret_filter = RedactSecretsFilter()
    for handler in logging.getLogger().handlers:
        handler.addFilter(secret_filter)
