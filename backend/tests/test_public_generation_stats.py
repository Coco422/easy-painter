from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI, Response
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api import routes
from app.db.session import get_db
from app.models.generation_job import GenerationJob, JobStatus
from app.models.media import MediaState


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    GenerationJob.__table__.create(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def add_job(db, *, finished_at=None, **values):
    job = GenerationJob(
        prompt="统计测试",
        model="test-model",
        status=values.pop("status", JobStatus.SUCCEEDED),
        finished_at=finished_at,
        **values,
    )
    db.add(job)
    return job


def test_counts_all_successful_images_even_if_private_deleted_or_expired(db, monkeypatch):
    now = datetime(2026, 9, 15, 4, tzinfo=timezone.utc)
    monkeypatch.setattr(routes, "utcnow", lambda: now)
    for values in (
        {"user_id": "user-a", "is_public": False},
        {"user_id": "user-b", "is_public": True},
        {"user_id": None},
        {"deleted_at": now, "media_state": MediaState.DELETED},
        {"media_expires_at": now - timedelta(hours=1), "media_state": MediaState.AVAILABLE},
    ):
        add_job(db, finished_at=now - timedelta(hours=2), **values)
    for status in (JobStatus.QUEUED, JobStatus.PROCESSING, JobStatus.FAILED):
        add_job(db, finished_at=now, status=status)
    add_job(db, finished_at=now - timedelta(days=1))
    # Legacy successes without a timestamp still contribute to the all-time count.
    add_job(db)
    db.commit()

    result = routes.get_public_generation_stats(Response(), db)

    assert result.today_images == 5
    assert result.total_images == 7


@pytest.mark.parametrize("utc_hour, expected_today", [(15, 1), (16, 2)])
def test_beijing_midnight_uses_completion_time_and_half_open_day(db, monkeypatch, utc_hour, expected_today):
    midnight = datetime(2026, 9, 14, 16, tzinfo=timezone.utc)
    monkeypatch.setattr(
        routes, "utcnow", lambda: datetime(2026, 9, 14, utc_hour, tzinfo=timezone.utc),
    )
    for finished_at in (
        midnight - timedelta(microseconds=1),
        midnight,
        midnight + timedelta(days=1, microseconds=-1),
        midnight + timedelta(days=1),
    ):
        add_job(db, finished_at=finished_at, created_at=midnight - timedelta(days=3))
    db.commit()

    result = routes.get_public_generation_stats(Response(), db)

    assert result.today_images == expected_today
    assert result.total_images == 4


@pytest.mark.parametrize("authorization", [None, "Bearer expired-token"])
def test_public_endpoint_returns_only_counts_without_requiring_auth(db, authorization):
    app = FastAPI()
    app.include_router(routes.router, prefix="/api/v1")
    app.dependency_overrides[get_db] = lambda: db

    with TestClient(app) as client:
        response = client.get(
            "/api/v1/stats/public",
            headers={"Authorization": authorization} if authorization else {},
        )

    assert response.status_code == 200
    assert response.json() == {"today_images": 0, "total_images": 0}
    assert response.headers["Cache-Control"] == "public, max-age=30"


def test_database_failure_does_not_return_fake_zero_counts():
    class UnavailableDB:
        def execute(self, _):
            raise RuntimeError("database unavailable")

    with pytest.raises(RuntimeError, match="database unavailable"):
        routes.get_public_generation_stats(Response(), UnavailableDB())
