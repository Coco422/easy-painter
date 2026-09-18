from sqlalchemy import BigInteger, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from datetime import datetime


class MediaDerivativeMixin:
    """Stored derivatives share their source's authorization and lifecycle."""

    thumbnail_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    thumbnail_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    thumbnail_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    media_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    thumbnail_attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    thumbnail_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
