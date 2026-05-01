from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.auth import hash_password, require_admin
from app.db.session import get_db
from app.models.generation_job import GenerationJob, JobStatus
from app.models.user import User
from app.schemas.auth import AdminCreateUserRequest, UserResponse
from app.services.storage import MinioStorageService

logger = logging.getLogger(__name__)
admin_router = APIRouter()


class AdminJobItem(BaseModel):
    job_id: str
    status: str
    prompt: str
    model: str
    username: str | None = None
    created_at: str
    finished_at: str | None = None


@admin_router.get("/admin/jobs", response_model=list[AdminJobItem])
def admin_list_jobs(
    db: Session = Depends(get_db),
    _: dict = Depends(require_admin),
) -> list[AdminJobItem]:
    stmt = select(GenerationJob).order_by(desc(GenerationJob.created_at)).limit(100)
    jobs = db.scalars(stmt).all()
    result = []
    for job in jobs:
        username = None
        if job.user_id:
            user = db.get(User, job.user_id)
            if user:
                username = user.username
        result.append(AdminJobItem(
            job_id=job.id,
            status=job.status.value,
            prompt=job.prompt[:80],
            model=job.model,
            username=username,
            created_at=job.created_at.isoformat() if job.created_at else "",
            finished_at=job.finished_at.isoformat() if job.finished_at else None,
        ))
    return result


@admin_router.delete("/admin/jobs/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
def admin_delete_job(
    job_id: str,
    db: Session = Depends(get_db),
    _: dict = Depends(require_admin),
) -> None:
    job = db.get(GenerationJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在。")
    storage: MinioStorageService | None = None
    if job.object_key:
        try:
            storage = storage or MinioStorageService()
            storage.delete_object(job.object_key)
        except Exception:
            logger.warning("Failed to delete MinIO object %s", job.object_key)
    if job.reference_image_key:
        try:
            storage = storage or MinioStorageService()
            storage.delete_reference_image(job.reference_image_key)
        except Exception:
            logger.warning("Failed to delete MinIO reference %s", job.reference_image_key)
    db.delete(job)
    db.commit()


@admin_router.get("/admin/users", response_model=list[UserResponse])
def admin_list_users(
    db: Session = Depends(get_db),
    _: dict = Depends(require_admin),
) -> list[UserResponse]:
    users = db.scalars(select(User).order_by(User.created_at)).all()
    return [
        UserResponse(
            id=u.id, username=u.username, display_name=u.display_name,
            is_public=u.is_public, created_at=u.created_at,
        )
        for u in users
    ]


@admin_router.post("/admin/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def admin_create_user(
    body: AdminCreateUserRequest,
    db: Session = Depends(get_db),
    _: dict = Depends(require_admin),
) -> UserResponse:
    existing = db.scalar(select(User).where(User.username == body.username))
    if existing:
        raise HTTPException(status_code=409, detail="用户名已存在。")
    user = User(
        username=body.username,
        password_hash=hash_password(body.password),
        display_name=body.display_name or body.username,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return UserResponse(
        id=user.id, username=user.username, display_name=user.display_name,
        is_public=user.is_public, created_at=user.created_at,
    )
