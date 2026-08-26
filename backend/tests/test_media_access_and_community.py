from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.requests import Request

from app.api import community_admin_routes, inspiration_routes, media_routes, routes
from app.core.config import get_settings
from app.db.base import Base
from app.models.generation_job import GenerationJob, JobStatus
from app.models.inspiration import Inspiration
from app.models.media import MediaState
from app.models.user import User


def make_session_factory():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def request(method: str = "GET") -> Request:
    return Request({"type": "http", "method": method, "path": "/", "headers": []})


def test_media_capability_rechecks_resource_visibility_and_scope(monkeypatch):
    session_factory = make_session_factory()
    db = session_factory()
    job = GenerationJob(
        id="job-1",
        prompt="private",
        model="model",
        status=JobStatus.SUCCEEDED,
        user_id="owner",
        object_key="generated/job.jpg",
        media_state=MediaState.AVAILABLE,
        media_content_type="image/webp",
        media_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    other_job = GenerationJob(
        id="job-2",
        prompt="other",
        model="model",
        status=JobStatus.SUCCEEDED,
        user_id="owner",
        object_key="generated/other.jpg",
        media_state=MediaState.AVAILABLE,
    )
    owner = User(id="owner", username="owner", password_hash="hash", is_public=True)
    db.add_all([owner, job, other_job])
    db.commit()
    monkeypatch.setattr(media_routes, "SessionLocal", session_factory)

    class Storage:
        def iter_object(self, key: str):
            yield key.encode()

    monkeypatch.setattr(media_routes, "MinioStorageService", Storage)

    owner_token = media_routes.issue_job_media_token(job_id=job.id, user_id="owner")
    response = media_routes.stream_job_media(job.id, request(), owner_token)
    assert response.media_type == "image/webp"
    assert response.headers["cache-control"].startswith("private, max-age=")

    with pytest.raises(HTTPException) as exc_info:
        media_routes.stream_job_media(
            job.id,
            request(),
            media_routes.issue_job_media_token(job_id=job.id, user_id="intruder"),
        )
    assert exc_info.value.status_code == 403

    with pytest.raises(HTTPException) as exc_info:
        media_routes.stream_job_media(
            other_job.id,
            request(),
            media_routes.issue_job_media_token(job_id=job.id, user_id="owner"),
        )
    assert exc_info.value.status_code == 401
    assert exc_info.value.headers["Cache-Control"] == "no-store"

    token_parts = owner_token.split(".")
    token_parts[2] = ("a" if token_parts[2][0] != "a" else "b") + token_parts[2][1:]
    tampered = ".".join(token_parts)
    with pytest.raises(HTTPException) as exc_info:
        media_routes.stream_job_media(job.id, request(), tampered)
    assert exc_info.value.status_code == 401

    job.is_public = True
    db.commit()
    public_token = media_routes.issue_job_media_token(job_id=job.id, user_id=None)
    assert media_routes.stream_job_media(job.id, request("HEAD"), public_token).status_code == 200
    owner.is_public = False
    db.commit()
    with pytest.raises(HTTPException) as exc_info:
        media_routes.stream_job_media(job.id, request(), public_token)
    assert exc_info.value.status_code == 404
    owner.is_public = True
    job.is_public = False
    db.commit()
    with pytest.raises(HTTPException) as exc_info:
        media_routes.stream_job_media(job.id, request(), public_token)
    assert exc_info.value.status_code == 404

    job.media_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()
    with pytest.raises(HTTPException) as exc_info:
        media_routes.stream_job_media(job.id, request(), owner_token)
    assert exc_info.value.status_code == 404

    settings = get_settings()
    expired = jwt.encode(
        {
            "typ": "job_media",
            "aud": "media",
            "job_id": job.id,
            "sub": "owner",
            "exp": datetime.now(timezone.utc) - timedelta(seconds=1),
        },
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(HTTPException) as exc_info:
        media_routes.stream_job_media(job.id, request(), expired)
    assert exc_info.value.status_code == 401
    db.close()


def test_curated_copy_survives_source_deletion_and_hidden_prompts_are_ineligible(monkeypatch):
    session_factory = make_session_factory()
    db = session_factory()
    user = User(id="user-1", username="artist", display_name="Artist", password_hash="hash", is_public=True)
    eligible = GenerationJob(
        id="eligible",
        prompt="public prompt",
        model="model",
        status=JobStatus.SUCCEEDED,
        user_id=user.id,
        object_key="generated/source.jpg",
        media_state=MediaState.AVAILABLE,
        media_content_type="image/jpeg",
        media_size_bytes=123,
        media_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        finished_at=datetime.now(timezone.utc),
        is_public=True,
        is_prompt_public=True,
        tags=["landscape"],
    )
    hidden_prompt = GenerationJob(
        id="hidden-prompt",
        prompt="secret",
        model="model",
        status=JobStatus.SUCCEEDED,
        user_id=user.id,
        object_key="generated/secret.jpg",
        media_state=MediaState.AVAILABLE,
        finished_at=datetime.now(timezone.utc),
        is_public=True,
        is_prompt_public=False,
    )
    db.add_all([user, eligible, hidden_prompt])
    db.commit()

    class Storage:
        copied: list[tuple[str, str]] = []

        def copy_generated_image_to_inspiration(self, source: str, *, inspiration_id: str) -> str:
            self.copied.append((source, inspiration_id))
            return f"inspirations/curated/{inspiration_id}.jpg"

        def delete_object(self, _: str) -> None:
            return None

    storage = Storage()
    monkeypatch.setattr(community_admin_routes, "MinioStorageService", lambda: storage)

    candidates = community_admin_routes.list_community_candidates(page=1, page_size=50, db=db, _={})
    assert candidates.total == 1
    assert [item.job_id for item in candidates.items] == [eligible.id]
    curated = community_admin_routes.curate_job(
        eligible.id,
        community_admin_routes.CurateRequest(is_featured=True),
        db,
        {},
    )
    assert curated.source == "community-curated"
    assert curated.image_object_key.startswith("inspirations/curated/")
    assert storage.copied[0][0] == eligible.object_key

    with pytest.raises(HTTPException) as exc_info:
        community_admin_routes.curate_job(
            eligible.id,
            community_admin_routes.CurateRequest(),
            db,
            {},
        )
    assert exc_info.value.status_code == 409

    eligible.deleted_at = datetime.now(timezone.utc)
    eligible.media_state = MediaState.DELETED
    eligible.object_key = None
    db.commit()
    feed = inspiration_routes.list_inspirations(
        db=db,
        offset=0,
        limit=20,
        q=None,
        source=None,
        category=None,
        sort="recent",
        current_user=None,
    )
    assert [item.id for item in feed.items] == [curated.id]
    assert inspiration_routes.list_inspiration_categories(db=db, limit=20) == ["landscape"]
    curated_feed = inspiration_routes.list_inspirations(
        db=db,
        offset=0,
        limit=20,
        q=None,
        source="community-curated",
        category=None,
        sort="recent",
        current_user=None,
    )
    assert [item.id for item in curated_feed.items] == [curated.id]
    imported_feed = inspiration_routes.list_inspirations(
        db=db,
        offset=0,
        limit=20,
        q=None,
        source="imported",
        category=None,
        sort="recent",
        current_user=None,
    )
    assert imported_feed.items == []

    updated = community_admin_routes.edit_community_inspiration(
        curated.id,
        community_admin_routes.EditInspirationRequest(description=None, categories=[]),
        db,
        {},
    )
    assert updated.description is None
    assert updated.categories == []
    db.close()


def test_guest_inspiration_feed_is_capped_but_authenticated_feed_is_not():
    session_factory = make_session_factory()
    db = session_factory()
    db.add_all(
        [
            Inspiration(
                id=f"inspiration-{index}",
                title=f"Case {index}",
                prompt=f"Prompt {index}",
                image_url=f"https://example.com/{index}.jpg",
                source="test",
                media_state=MediaState.AVAILABLE,
            )
            for index in range(25)
        ]
    )
    db.commit()

    guest_feed = inspiration_routes.list_inspirations(
        db=db,
        offset=0,
        limit=100,
        q=None,
        source=None,
        category=None,
        sort="recent",
        current_user=None,
    )
    guest_next_page = inspiration_routes.list_inspirations(
        db=db,
        offset=20,
        limit=20,
        q=None,
        source=None,
        category=None,
        sort="recent",
        current_user=None,
    )
    signed_in_feed = inspiration_routes.list_inspirations(
        db=db,
        offset=0,
        limit=100,
        q=None,
        source=None,
        category=None,
        sort="recent",
        current_user=User(username="viewer", password_hash="hash"),
    )

    assert guest_feed.total == 25
    assert len(guest_feed.items) == inspiration_routes.GUEST_INSPIRATION_PREVIEW_LIMIT
    assert guest_next_page.items == []
    assert len(signed_in_feed.items) == 25
    db.close()


def test_public_gallery_hides_private_prompt_and_like_rechecks_visibility():
    session_factory = make_session_factory()
    db = session_factory()
    owner = User(id="owner", username="owner", password_hash="hash", is_public=True)
    viewer = User(id="viewer", username="viewer", password_hash="hash")
    job = GenerationJob(
        id="public-job",
        prompt="do not reveal",
        revised_prompt="also secret",
        model="model",
        status=JobStatus.SUCCEEDED,
        user_id=owner.id,
        object_key="generated/public.jpg",
        media_state=MediaState.AVAILABLE,
        finished_at=datetime.now(timezone.utc),
        is_public=True,
        is_prompt_public=False,
    )
    db.add_all([owner, viewer, job])
    db.commit()

    items = routes.get_public_gallery(db=db, current_user=viewer, sort="recent", page=1, page_size=20)
    assert items.items[0].prompt == ""
    assert items.items[0].revised_prompt is None
    routes.like_gallery_item(job.id, db=db, current_user=viewer)

    job.is_public = False
    db.commit()
    with pytest.raises(HTTPException) as exc_info:
        routes.like_gallery_item(job.id, db=db, current_user=viewer)
    assert exc_info.value.status_code == 404
    db.close()
