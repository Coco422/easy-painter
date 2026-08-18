from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import admin_routes
from app.db.base import Base
from app.models.generation_job import GenerationJob, JobStatus
from app.models.user import User


def make_session():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def test_admin_jobs_are_server_paginated_and_status_filtered():
    db = make_session()
    created_at = datetime.now(timezone.utc)
    db.add(User(id="user-1", username="owner", password_hash="hash"))
    db.add_all([
        GenerationJob(
            id=f"job-{index}",
            prompt=f"prompt {index}",
            model="model",
            user_id="user-1",
            status=JobStatus.FAILED if index == 4 else JobStatus.SUCCEEDED,
            created_at=created_at + timedelta(minutes=index),
        )
        for index in range(5)
    ])
    db.commit()

    second_page = admin_routes.admin_list_jobs(
        db=db,
        _={},
        status_filter=None,
        page=2,
        page_size=2,
    )

    assert second_page.total == 5
    assert second_page.page == 2
    assert second_page.page_size == 2
    assert [item.job_id for item in second_page.items] == ["job-2", "job-1"]
    assert all(item.username == "owner" for item in second_page.items)

    failed_page = admin_routes.admin_list_jobs(
        db=db,
        _={},
        status_filter=JobStatus.FAILED,
        page=1,
        page_size=25,
    )

    assert failed_page.total == 1
    assert [item.job_id for item in failed_page.items] == ["job-4"]
