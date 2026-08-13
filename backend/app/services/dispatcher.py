from __future__ import annotations

import logging
import signal
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import asc, func, select

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import SessionLocal
from app.models.generation_job import GenerationJob, JobStatus
from app.models.outbox_event import OutboxEvent, OutboxEventStatus
from app.services.billing import reconcile_job_billing, reconcile_user_balances
from app.services.health import DISPATCHER_HEARTBEAT_KEY
from app.services.job_lifecycle import mark_generation_failed
from app.services.media_lifecycle import process_media_deletions, scan_expired_media
from app.services.redis_client import redis_client
from app.services.tasks import generate_image_task


configure_logging()
settings = get_settings()
logger = logging.getLogger(__name__)
_stopping = False


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def dispatch_pending_events(*, now: datetime | None = None) -> dict[str, int]:
    dispatched_at = now or utcnow()
    counts = {"published": 0, "failed": 0, "discarded": 0}
    db = SessionLocal()
    try:
        events = db.scalars(
            select(OutboxEvent)
            .where(
                OutboxEvent.status == OutboxEventStatus.PENDING,
                OutboxEvent.available_at <= dispatched_at,
            )
            .order_by(asc(OutboxEvent.created_at))
            .limit(settings.outbox_batch_size)
            .with_for_update(skip_locked=True)
        ).all()
        for event in events:
            job = db.get(GenerationJob, event.aggregate_id)
            if not job or job.status != JobStatus.QUEUED:
                event.status = OutboxEventStatus.DISCARDED
                event.last_error = "job is no longer queued"
                counts["discarded"] += 1
                continue
            try:
                generate_image_task.apply_async(args=[job.id])
            except Exception as exc:
                event.attempts += 1
                event.last_error = str(exc)[:1000]
                event.available_at = dispatched_at + timedelta(seconds=min(60, 2 ** min(event.attempts, 6)))
                counts["failed"] += 1
            else:
                event.status = OutboxEventStatus.PUBLISHED
                event.published_at = dispatched_at
                event.last_error = None
                counts["published"] += 1
        db.commit()
        return counts
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def run_watchdog(*, now: datetime | None = None) -> int:
    checked_at = now or utcnow()
    queue_cutoff = checked_at - timedelta(seconds=settings.generation_queue_stale_seconds)
    processing_cutoff = checked_at - timedelta(seconds=settings.generation_job_stale_seconds)
    db = SessionLocal()
    try:
        jobs = db.scalars(
            select(GenerationJob).where(
                (
                    (GenerationJob.status == JobStatus.QUEUED)
                    & (GenerationJob.created_at <= queue_cutoff)
                )
                | (
                    (GenerationJob.status == JobStatus.PROCESSING)
                    & (
                        (GenerationJob.lease_expires_at <= checked_at)
                        | (
                            (GenerationJob.lease_expires_at.is_(None))
                            & (
                                func.coalesce(
                                    GenerationJob.started_at,
                                    GenerationJob.created_at,
                                )
                                <= processing_cutoff
                            )
                        )
                    )
                )
            )
        ).all()
        job_ids = [job.id for job in jobs]
    finally:
        db.close()

    failed = 0
    for job_id in job_ids:
        db = SessionLocal()
        try:
            if mark_generation_failed(
                db,
                job_id=job_id,
                message="生成任务长时间没有响应，灵感丝线已自动退回。",
                now=checked_at,
            ):
                failed += 1
        finally:
            db.close()
    return failed


def run_reconciliation() -> dict[str, int]:
    db = SessionLocal()
    try:
        counts = reconcile_job_billing(db)
        counts["balances_repaired"] = reconcile_user_balances(db)
        db.commit()
        return counts
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def write_heartbeat() -> None:
    redis_client.setex(
        DISPATCHER_HEARTBEAT_KEY,
        settings.dispatcher_heartbeat_ttl_seconds,
        utcnow().isoformat(),
    )


def _stop(*_: object) -> None:
    global _stopping
    _stopping = True


def main() -> None:
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    last_watchdog = 0.0
    last_reconciliation = 0.0
    last_media_cleanup = 0.0
    logger.info("Dispatcher started.")
    while not _stopping:
        loop_started = time.monotonic()
        try:
            write_heartbeat()
            counts = dispatch_pending_events()
            if any(counts.values()):
                logger.info("Outbox dispatch result=%s", counts)
            if loop_started - last_watchdog >= settings.watchdog_interval_seconds:
                failed = run_watchdog()
                if failed:
                    logger.warning("Watchdog failed and refunded %s stale jobs.", failed)
                last_watchdog = loop_started
            if loop_started - last_reconciliation >= settings.reconciliation_interval_seconds:
                reconciled = run_reconciliation()
                if any(reconciled.values()):
                    logger.warning("Billing reconciliation result=%s", reconciled)
                last_reconciliation = loop_started
            if settings.media_cleanup_enabled and loop_started - last_media_cleanup >= settings.media_cleanup_interval_seconds:
                db = SessionLocal()
                try:
                    marked = scan_expired_media(db)
                    deleted = process_media_deletions(db, limit=settings.media_cleanup_batch_size)
                    if marked or any(deleted.values()):
                        logger.info("Media cleanup marked=%s result=%s", marked, deleted)
                finally:
                    db.close()
                last_media_cleanup = loop_started
        except Exception:
            logger.exception("Dispatcher loop failed.")
        elapsed = time.monotonic() - loop_started
        time.sleep(max(0.1, settings.outbox_poll_seconds - elapsed))
    logger.info("Dispatcher stopped.")


if __name__ == "__main__":
    main()
