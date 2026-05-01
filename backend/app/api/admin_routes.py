from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.auth import hash_password, require_admin
from app.db.session import get_db
from app.models.generation_job import GenerationJob, JobStatus
from app.models.model_config import ModelConfig
from app.models.upstream_provider import UpstreamProvider
from app.models.user import User
from app.schemas.auth import AdminCreateUserRequest, AdminUpdateUserRequest, UserResponse
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


@admin_router.put("/admin/users/{user_id}", response_model=UserResponse)
def admin_update_user(
    user_id: str,
    body: AdminUpdateUserRequest,
    db: Session = Depends(get_db),
    _: dict = Depends(require_admin),
) -> UserResponse:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在。")
    if body.password is not None:
        user.password_hash = hash_password(body.password)
    if body.display_name is not None:
        user.display_name = body.display_name
    if body.is_public is not None:
        user.is_public = body.is_public
    db.commit()
    db.refresh(user)
    return UserResponse(
        id=user.id, username=user.username, display_name=user.display_name,
        is_public=user.is_public, created_at=user.created_at,
    )


@admin_router.delete("/admin/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def admin_delete_user(
    user_id: str,
    db: Session = Depends(get_db),
    _: dict = Depends(require_admin),
) -> None:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在。")
    db.delete(user)
    db.commit()


# ---- Provider schemas ----

class ProviderResponse(BaseModel):
    id: str
    name: str
    base_url: str
    api_key: str
    timeout_seconds: int
    default_size: str
    default_quality: str
    default_output_format: str
    default_output_compression: int
    default_background: str
    default_moderation: str


class CreateProviderRequest(BaseModel):
    name: str
    base_url: str
    api_key: str
    timeout_seconds: int = 700
    default_size: str = "auto"
    default_quality: str = "high"
    default_output_format: str = "jpeg"
    default_output_compression: int = 85
    default_background: str = "auto"
    default_moderation: str = "auto"


class UpdateProviderRequest(BaseModel):
    name: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    timeout_seconds: int | None = None
    default_size: str | None = None
    default_quality: str | None = None
    default_output_format: str | None = None
    default_output_compression: int | None = None
    default_background: str | None = None
    default_moderation: str | None = None


def _provider_response(p: UpstreamProvider) -> ProviderResponse:
    return ProviderResponse(
        id=p.id, name=p.name, base_url=p.base_url, api_key=p.api_key,
        timeout_seconds=p.timeout_seconds, default_size=p.default_size,
        default_quality=p.default_quality, default_output_format=p.default_output_format,
        default_output_compression=p.default_output_compression,
        default_background=p.default_background, default_moderation=p.default_moderation,
    )


# ---- Model schemas ----

class ModelResponse(BaseModel):
    id: str
    provider_id: str
    label: str
    enabled: bool
    supports_reference_image: bool
    supported_sizes: list[str]
    sort_order: int


class CreateModelRequest(BaseModel):
    id: str
    provider_id: str
    label: str
    enabled: bool = True
    supports_reference_image: bool = True
    supported_sizes: list[str] = []
    sort_order: int = 0


class UpdateModelRequest(BaseModel):
    provider_id: str | None = None
    label: str | None = None
    enabled: bool | None = None
    supports_reference_image: bool | None = None
    supported_sizes: list[str] | None = None
    sort_order: int | None = None


def _model_response(m: ModelConfig) -> ModelResponse:
    return ModelResponse(
        id=m.id, provider_id=m.provider_id, label=m.label,
        enabled=m.enabled, supports_reference_image=m.supports_reference_image,
        supported_sizes=list(m.supported_sizes) if m.supported_sizes else [],
        sort_order=m.sort_order,
    )


# ---- Provider CRUD ----

@admin_router.get("/admin/providers", response_model=list[ProviderResponse])
def admin_list_providers(
    db: Session = Depends(get_db),
    _: dict = Depends(require_admin),
) -> list[ProviderResponse]:
    providers = db.scalars(select(UpstreamProvider).order_by(UpstreamProvider.created_at)).all()
    return [_provider_response(p) for p in providers]


@admin_router.post("/admin/providers", response_model=ProviderResponse, status_code=status.HTTP_201_CREATED)
def admin_create_provider(
    body: CreateProviderRequest,
    db: Session = Depends(get_db),
    _: dict = Depends(require_admin),
) -> ProviderResponse:
    provider = UpstreamProvider(
        name=body.name, base_url=body.base_url, api_key=body.api_key,
        timeout_seconds=body.timeout_seconds, default_size=body.default_size,
        default_quality=body.default_quality, default_output_format=body.default_output_format,
        default_output_compression=body.default_output_compression,
        default_background=body.default_background, default_moderation=body.default_moderation,
    )
    db.add(provider)
    db.commit()
    db.refresh(provider)
    return _provider_response(provider)


@admin_router.put("/admin/providers/{provider_id}", response_model=ProviderResponse)
def admin_update_provider(
    provider_id: str,
    body: UpdateProviderRequest,
    db: Session = Depends(get_db),
    _: dict = Depends(require_admin),
) -> ProviderResponse:
    provider = db.get(UpstreamProvider, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="上游不存在。")
    for field in body.model_fields:
        value = getattr(body, field)
        if value is not None:
            setattr(provider, field, value)
    db.commit()
    db.refresh(provider)
    return _provider_response(provider)


@admin_router.delete("/admin/providers/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
def admin_delete_provider(
    provider_id: str,
    db: Session = Depends(get_db),
    _: dict = Depends(require_admin),
) -> None:
    provider = db.get(UpstreamProvider, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="上游不存在。")
    linked = db.scalar(select(ModelConfig).where(ModelConfig.provider_id == provider_id).limit(1))
    if linked:
        raise HTTPException(status_code=409, detail="该上游下还有关联的模型，请先删除或迁移模型。")
    db.delete(provider)
    db.commit()


# ---- Model CRUD ----

@admin_router.get("/admin/models", response_model=list[ModelResponse])
def admin_list_models(
    db: Session = Depends(get_db),
    _: dict = Depends(require_admin),
) -> list[ModelResponse]:
    models = db.scalars(select(ModelConfig).order_by(ModelConfig.sort_order, ModelConfig.id)).all()
    return [_model_response(m) for m in models]


@admin_router.post("/admin/models", response_model=ModelResponse, status_code=status.HTTP_201_CREATED)
def admin_create_model(
    body: CreateModelRequest,
    db: Session = Depends(get_db),
    _: dict = Depends(require_admin),
) -> ModelResponse:
    existing = db.get(ModelConfig, body.id)
    if existing:
        raise HTTPException(status_code=409, detail="模型 ID 已存在。")
    provider = db.get(UpstreamProvider, body.provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="关联的上游不存在。")
    model = ModelConfig(
        id=body.id, provider_id=body.provider_id, label=body.label,
        enabled=body.enabled, supports_reference_image=body.supports_reference_image,
        supported_sizes=body.supported_sizes, sort_order=body.sort_order,
    )
    db.add(model)
    db.commit()
    db.refresh(model)
    return _model_response(model)


@admin_router.put("/admin/models/{model_id:path}", response_model=ModelResponse)
def admin_update_model(
    model_id: str,
    body: UpdateModelRequest,
    db: Session = Depends(get_db),
    _: dict = Depends(require_admin),
) -> ModelResponse:
    model = db.get(ModelConfig, model_id)
    if not model:
        raise HTTPException(status_code=404, detail="模型不存在。")
    if body.provider_id is not None:
        provider = db.get(UpstreamProvider, body.provider_id)
        if not provider:
            raise HTTPException(status_code=404, detail="关联的上游不存在。")
    for field in body.model_fields:
        value = getattr(body, field)
        if value is not None:
            setattr(model, field, value)
    db.commit()
    db.refresh(model)
    return _model_response(model)


@admin_router.delete("/admin/models/{model_id:path}", status_code=status.HTTP_204_NO_CONTENT)
def admin_delete_model(
    model_id: str,
    db: Session = Depends(get_db),
    _: dict = Depends(require_admin),
) -> None:
    model = db.get(ModelConfig, model_id)
    if not model:
        raise HTTPException(status_code=404, detail="模型不存在。")
    db.delete(model)
    db.commit()
