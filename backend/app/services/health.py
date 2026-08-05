from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from redis import Redis
from sqlalchemy import case, func, select, text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.generation_job import GenerationJob, JobStatus
from app.models.outbox_event import OutboxEvent, OutboxEventStatus
from app.services.storage import MinioStorageService
from app.services.tasks import celery_app


DISPATCHER_HEARTBEAT_KEY = "easy-painter:dispatcher:heartbeat"
EXPECTED_FLYWAY_VERSION = "3"


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def collect_core_health(
    *,
    db: Session,
    redis_client: Redis,
    settings: Settings,
) -> dict[str, dict[str, Any]]:
    components: dict[str, dict[str, Any]] = {}

    try:
        db.execute(select(1))
        components["database"] = {"status": "ok"}
    except Exception as exc:
        components["database"] = {"status": "unavailable", "detail": type(exc).__name__}

    try:
        version = db.execute(
            text(
                "SELECT version FROM flyway_schema_history "
                "WHERE success = TRUE ORDER BY installed_rank DESC LIMIT 1"
            )
        ).scalar_one_or_none()
        components["schema"] = {
            "status": "ok" if version == EXPECTED_FLYWAY_VERSION else "degraded",
            "version": version,
            "expected": EXPECTED_FLYWAY_VERSION,
        }
    except Exception as exc:
        db.rollback()
        components["schema"] = {"status": "unavailable", "detail": type(exc).__name__}

    try:
        redis_client.ping()
        components["redis"] = {"status": "ok"}
    except Exception as exc:
        components["redis"] = {"status": "unavailable", "detail": type(exc).__name__}

    try:
        ready = MinioStorageService().check_ready()
        components["minio"] = {"status": "ok" if ready else "degraded"}
    except Exception as exc:
        components["minio"] = {"status": "unavailable", "detail": type(exc).__name__}

    try:
        heartbeat = redis_client.get(DISPATCHER_HEARTBEAT_KEY)
        components["dispatcher"] = {
            "status": "ok" if heartbeat else "unavailable",
            "heartbeat": heartbeat.decode() if isinstance(heartbeat, bytes) else heartbeat,
            "ttl": redis_client.ttl(DISPATCHER_HEARTBEAT_KEY),
        }
    except Exception as exc:
        components["dispatcher"] = {"status": "unavailable", "detail": type(exc).__name__}

    return components


def collect_admin_health(
    *,
    db: Session,
    redis_client: Redis,
    settings: Settings,
) -> dict[str, Any]:
    components = collect_core_health(db=db, redis_client=redis_client, settings=settings)
    try:
        active_queues = celery_app.control.inspect(timeout=0.7).active_queues() or {}
        generation_workers = [
            worker
            for worker, queues in active_queues.items()
            if any(queue.get("name") == "celery" for queue in queues)
        ]
        components["worker"] = {
            "status": "ok" if generation_workers else "unavailable",
            "count": len(generation_workers),
        }
    except Exception as exc:
        components["worker"] = {"status": "unavailable", "detail": type(exc).__name__}

    try:
        components["queue"] = {"status": "ok", "depth": int(redis_client.llen("celery"))}
    except Exception as exc:
        components["queue"] = {"status": "unavailable", "detail": type(exc).__name__}

    now = datetime.now(timezone.utc)
    try:
        pending_count, oldest_created_at, max_attempts = db.execute(
            select(
                func.count(),
                func.min(OutboxEvent.created_at),
                func.max(OutboxEvent.attempts),
            ).where(OutboxEvent.status == OutboxEventStatus.PENDING)
        ).one()
        components["outbox"] = {
            "status": "degraded" if (max_attempts or 0) > 0 or (
                oldest_created_at and _as_utc(oldest_created_at) < now - timedelta(minutes=1)
            ) else "ok",
            "pending": int(pending_count or 0),
            "oldest_created_at": oldest_created_at.isoformat() if oldest_created_at else None,
            "oldest_wait_seconds": round((now - _as_utc(oldest_created_at)).total_seconds(), 1) if oldest_created_at else 0,
            "max_attempts": int(max_attempts or 0),
        }
    except Exception as exc:
        db.rollback()
        components["outbox"] = {"status": "unavailable", "detail": type(exc).__name__}
    components["smtp"] = {
        "status": "configured" if settings.smtp_configured else "not_configured",
    }

    try:
        since = now - timedelta(hours=24)
        provider_rows = db.execute(
            select(
                GenerationJob.provider_name_snapshot,
                func.count(GenerationJob.id),
                func.sum(case((GenerationJob.status == JobStatus.SUCCEEDED, 1), else_=0)),
                func.sum(case((GenerationJob.status == JobStatus.FAILED, 1), else_=0)),
                func.max(GenerationJob.finished_at),
            )
            .where(GenerationJob.created_at >= since)
            .group_by(GenerationJob.provider_name_snapshot)
            .order_by(func.count(GenerationJob.id).desc())
        ).all()
        provider_items = []
        for provider_name, total, succeeded, failed, last_finished_at in provider_rows:
            terminal = int(succeeded or 0) + int(failed or 0)
            provider_items.append(
                {
                    "name": provider_name or "未记录渠道",
                    "total": int(total or 0),
                    "succeeded": int(succeeded or 0),
                    "failed": int(failed or 0),
                    "success_rate": round(int(succeeded or 0) / terminal * 100, 2) if terminal else 0.0,
                    "last_finished_at": last_finished_at.isoformat() if last_finished_at else None,
                }
            )
        components["providers"] = {"status": "ok", "window": "24h", "items": provider_items}
    except Exception as exc:
        db.rollback()
        components["providers"] = {"status": "unavailable", "detail": type(exc).__name__, "items": []}
    overall = "ok" if all(
        item.get("status") in {"ok", "configured", "not_configured"}
        for item in components.values()
    ) else "degraded"
    return {"status": overall, "components": components}
