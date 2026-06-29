from __future__ import annotations

import logging
import secrets
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.core.auth import hash_password, require_admin
from app.db.session import get_db
from app.models.credit_transaction import CreditTransaction
from app.models.gallery_like import GalleryLike
from app.models.generation_job import GenerationJob, JobStatus
from app.models.inspiration import Inspiration
from app.models.model_config import ModelConfig
from app.models.redemption_code import RedemptionCode
from app.models.upstream_provider import UpstreamProvider
from app.models.user import User
from app.schemas.auth import AdminCreateUserRequest, AdminUpdateUserRequest, UserResponse
from app.schemas.inspiration import (
    AdminInspirationItem,
    BatchCreateInspirationsRequest,
    BatchCreateInspirationsResponse,
    CreateInspirationRequest,
    CreateInspirationResponse,
)
from app.services.storage import MinioStorageService

logger = logging.getLogger(__name__)
admin_router = APIRouter()


class AdminJobItem(BaseModel):
    job_id: str
    status: str
    prompt: str
    revised_prompt: str | None = None
    model: str
    size: str = "auto"
    aspect_ratio: str = "auto"
    username: str | None = None
    error_message: str | None = None
    provider_job_meta: dict[str, Any] | None = None
    image_url: str | None = None
    reference_image_filename: str | None = None
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None


@admin_router.get("/admin/jobs", response_model=list[AdminJobItem])
def admin_list_jobs(
    db: Session = Depends(get_db),
    _: dict = Depends(require_admin),
    status_filter: str | None = Query(None, alias="status"),
) -> list[AdminJobItem]:
    stmt = select(GenerationJob).order_by(desc(GenerationJob.created_at))
    if status_filter:
        stmt = stmt.where(GenerationJob.status == status_filter)
    stmt = stmt.limit(500)
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
            prompt=job.prompt,
            revised_prompt=job.revised_prompt,
            model=job.model,
            size=job.size or "auto",
            aspect_ratio=job.aspect_ratio or "auto",
            username=username,
            error_message=job.error_message,
            provider_job_meta=job.provider_job_meta,
            image_url=job.public_url,
            reference_image_filename=job.reference_image_filename,
            created_at=job.created_at.isoformat() if job.created_at else "",
            started_at=job.started_at.isoformat() if job.started_at else None,
            finished_at=job.finished_at.isoformat() if job.finished_at else None,
        ))
    return result


def _delete_job_artifacts(job: GenerationJob, storage: MinioStorageService | None) -> MinioStorageService:
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
    return storage


@admin_router.delete("/admin/jobs/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
def admin_delete_job(
    job_id: str,
    db: Session = Depends(get_db),
    _: dict = Depends(require_admin),
) -> None:
    job = db.get(GenerationJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在。")
    storage = _delete_job_artifacts(job, None)
    for like in db.scalars(select(GalleryLike).where(GalleryLike.job_id == job.id)).all():
        db.delete(like)
    db.delete(job)
    db.commit()


class BatchDeleteRequest(BaseModel):
    job_ids: list[str] = Field(max_length=200)


class BatchDeleteResponse(BaseModel):
    deleted: int
    failed: list[str]


@admin_router.post("/admin/jobs/batch-delete", response_model=BatchDeleteResponse)
def admin_batch_delete_jobs(
    body: BatchDeleteRequest,
    db: Session = Depends(get_db),
    _: dict = Depends(require_admin),
) -> BatchDeleteResponse:
    deleted = 0
    failed: list[str] = []
    storage: MinioStorageService | None = None
    for job_id in body.job_ids:
        job = db.get(GenerationJob, job_id)
        if not job:
            failed.append(job_id)
            continue
        storage = _delete_job_artifacts(job, storage)
        for like in db.scalars(select(GalleryLike).where(GalleryLike.job_id == job.id)).all():
            db.delete(like)
        db.delete(job)
        deleted += 1
    if deleted > 0:
        db.commit()
    return BatchDeleteResponse(deleted=deleted, failed=failed)


@admin_router.get("/admin/users", response_model=list[UserResponse])
def admin_list_users(
    db: Session = Depends(get_db),
    _: dict = Depends(require_admin),
) -> list[UserResponse]:
    users = db.scalars(select(User).order_by(User.created_at)).all()
    return [
        UserResponse(
            id=u.id, username=u.username, display_name=u.display_name,
            is_public=u.is_public, credits=u.credits, created_at=u.created_at,
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
        is_public=user.is_public, credits=user.credits, created_at=user.created_at,
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
        is_public=user.is_public, credits=user.credits, created_at=user.created_at,
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
    for like in db.scalars(select(GalleryLike).where(GalleryLike.user_id == user.id)).all():
        db.delete(like)
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
    credit_cost: int = 1


class CreateModelRequest(BaseModel):
    id: str
    provider_id: str
    label: str
    enabled: bool = True
    supports_reference_image: bool = True
    supported_sizes: list[str] = []
    sort_order: int = 0
    credit_cost: int = 1


class UpdateModelRequest(BaseModel):
    provider_id: str | None = None
    label: str | None = None
    enabled: bool | None = None
    supports_reference_image: bool | None = None
    supported_sizes: list[str] | None = None
    sort_order: int | None = None
    credit_cost: int | None = None


def _model_response(m: ModelConfig) -> ModelResponse:
    return ModelResponse(
        id=m.id, provider_id=m.provider_id, label=m.label,
        enabled=m.enabled, supports_reference_image=m.supports_reference_image,
        supported_sizes=list(m.supported_sizes) if m.supported_sizes else [],
        sort_order=m.sort_order, credit_cost=m.credit_cost or 1,
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
        credit_cost=body.credit_cost,
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


# ---- Billing admin endpoints ----


class GenerateCodesRequest(BaseModel):
    count: int = Field(ge=1, le=1000, default=10)
    credits: int = Field(ge=1, default=100)
    prefix: str = Field(default="EP", max_length=8)


class CodeItem(BaseModel):
    id: str
    code: str
    credits: int
    used_by: str | None = None
    used_at: str | None = None
    created_at: str


class GenerateCodesResponse(BaseModel):
    codes: list[str]


class AdjustCreditsRequest(BaseModel):
    amount: int
    reason: str = Field(default="", max_length=256)


class AdminCreditTransactionItem(BaseModel):
    id: str
    user_id: str
    username: str | None = None
    amount: int
    balance_after: int
    reason: str
    created_at: str


@admin_router.post("/admin/codes/generate", response_model=GenerateCodesResponse)
def admin_generate_codes(
    body: GenerateCodesRequest,
    db: Session = Depends(get_db),
    admin: dict = Depends(require_admin),
) -> GenerateCodesResponse:
    admin_user = db.scalar(select(User).limit(1))
    if not admin_user:
        raise HTTPException(status_code=500, detail="无可用管理员用户。")
    codes = []
    for _ in range(body.count):
        code_str = f"{body.prefix}-{secrets.token_urlsafe(8).upper()[:8]}"
        code = RedemptionCode(
            code=code_str,
            credits=body.credits,
            created_by=admin_user.id,
        )
        db.add(code)
        codes.append(code_str)
    db.commit()
    return GenerateCodesResponse(codes=codes)


@admin_router.get("/admin/codes", response_model=list[CodeItem])
def admin_list_codes(
    status_filter: str = Query("all", pattern="^(all|unused|used)$"),
    db: Session = Depends(get_db),
    _: dict = Depends(require_admin),
) -> list[CodeItem]:
    stmt = select(RedemptionCode).order_by(desc(RedemptionCode.created_at)).limit(500)
    if status_filter == "unused":
        stmt = stmt.where(RedemptionCode.used_by.is_(None))
    elif status_filter == "used":
        stmt = stmt.where(RedemptionCode.used_by.is_not(None))
    codes = db.scalars(stmt).all()
    return [
        CodeItem(
            id=c.id,
            code=c.code,
            credits=c.credits,
            used_by=c.used_by,
            used_at=c.used_at.isoformat() if c.used_at else None,
            created_at=c.created_at.isoformat() if c.created_at else "",
        )
        for c in codes
    ]


@admin_router.post("/admin/users/{user_id}/credits")
def admin_adjust_credits(
    user_id: str,
    body: AdjustCreditsRequest,
    db: Session = Depends(get_db),
    _: dict = Depends(require_admin),
) -> dict:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在。")
    user.credits = (user.credits or 0) + body.amount
    if user.credits < 0:
        user.credits = 0
    txn = CreditTransaction(
        user_id=user.id,
        amount=body.amount,
        balance_after=user.credits,
        reason=body.reason or "admin:adjust",
    )
    db.add(txn)
    db.commit()
    db.refresh(user)
    return {"credits": user.credits}


@admin_router.get("/admin/transactions", response_model=list[AdminCreditTransactionItem])
def admin_list_transactions(
    user_id: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    _: dict = Depends(require_admin),
) -> list[AdminCreditTransactionItem]:
    stmt = select(CreditTransaction).order_by(desc(CreditTransaction.created_at))
    if user_id:
        stmt = stmt.where(CreditTransaction.user_id == user_id)
    offset = (page - 1) * page_size
    stmt = stmt.offset(offset).limit(page_size)
    txns = db.scalars(stmt).all()

    user_ids = list({t.user_id for t in txns})
    users = db.scalars(select(User).where(User.id.in_(user_ids))).all() if user_ids else []
    username_map = {u.id: u.username for u in users}

    return [
        AdminCreditTransactionItem(
            id=t.id,
            user_id=t.user_id,
            username=username_map.get(t.user_id),
            amount=t.amount,
            balance_after=t.balance_after,
            reason=t.reason,
            created_at=t.created_at.isoformat() if t.created_at else "",
        )
        for t in txns
    ]


# ---- Inspiration admin endpoints ----

@admin_router.get("/admin/inspirations", response_model=list[AdminInspirationItem])
def admin_list_inspirations(
    db: Session = Depends(get_db),
    _: dict = Depends(require_admin),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    source: str | None = Query(None),
) -> list[AdminInspirationItem]:
    stmt = select(Inspiration).order_by(desc(Inspiration.created_at))
    if source:
        stmt = stmt.where(Inspiration.source == source)
    stmt = stmt.offset(offset).limit(limit)
    items = db.scalars(stmt).all()
    return [
        AdminInspirationItem(
            id=item.id,
            title=item.title,
            description=item.description,
            prompt=item.prompt,
            image_url=item.image_url,
            image_object_key=item.image_object_key,
            external_id=item.external_id,
            source=item.source,
            source_url=item.source_url,
            author_name=item.author_name,
            author_url=item.author_url,
            language=item.language or "zh",
            categories=item.categories if isinstance(item.categories, list) else None,
            is_featured=item.is_featured or False,
            like_count=item.like_count or 0,
            created_at=item.created_at,
            updated_at=item.updated_at,
        )
        for item in items
    ]


@admin_router.post("/admin/inspirations", response_model=CreateInspirationResponse, status_code=status.HTTP_201_CREATED)
async def admin_create_inspiration(
    request: Request,
    db: Session = Depends(get_db),
    _: dict = Depends(require_admin),
) -> CreateInspirationResponse:
    form = await request.form()

    title = form.get("title", "")
    description = form.get("description") or None
    prompt = form.get("prompt", "")
    external_id = form.get("external_id") or None
    source = form.get("source", "")
    source_url = form.get("source_url") or None
    author_name = form.get("author_name") or None
    author_url = form.get("author_url") or None
    language = form.get("language") or "zh"
    is_featured = form.get("is_featured", "").lower() in ("true", "1", "yes") if form.get("is_featured") else False

    # Parse categories from JSON string if present
    categories_raw = form.get("categories")
    categories = None
    if categories_raw:
        import json
        try:
            categories = json.loads(str(categories_raw))
        except (json.JSONDecodeError, TypeError):
            pass

    if not title or not prompt or not source:
        raise HTTPException(status_code=422, detail="title, prompt, source 为必填项。")

    # Dedup check
    if external_id:
        existing = db.scalar(
            select(Inspiration).where(
                Inspiration.source == source,
                Inspiration.external_id == external_id,
            )
        )
        if existing:
            raise HTTPException(status_code=409, detail="该灵感条目已存在（source + external_id 重复）。")

    import uuid
    inspiration_id = str(uuid.uuid4())
    image_url = ""
    image_object_key = None

    # Handle image upload
    upload = form.get("image")
    if hasattr(upload, "read"):
        image_bytes = await upload.read()
        if image_bytes:
            content_type = getattr(upload, "content_type", "image/jpeg") or "image/jpeg"
            try:
                stored = MinioStorageService().upload_inspiration_image(
                    image_id=inspiration_id,
                    image_bytes=image_bytes,
                    content_type=content_type,
                )
                image_url = stored.public_url
                image_object_key = stored.object_key
            except Exception as exc:
                logger.warning("Failed to upload inspiration image: %s", exc)
                raise HTTPException(status_code=503, detail="图片上传失败。") from exc

    # Also accept image_url directly (for pre-uploaded images)
    if not image_url:
        image_url = str(form.get("image_url", ""))
    if not image_url:
        raise HTTPException(status_code=422, detail="需要提供图片（image 文件或 image_url）。")

    inspiration = Inspiration(
        id=inspiration_id,
        title=title,
        description=description,
        prompt=prompt,
        image_url=image_url,
        image_object_key=image_object_key,
        external_id=external_id,
        source=source,
        source_url=source_url,
        author_name=author_name,
        author_url=author_url,
        language=language,
        categories=categories,
        is_featured=is_featured,
    )
    db.add(inspiration)
    db.commit()
    db.refresh(inspiration)

    return CreateInspirationResponse(id=inspiration.id, image_url=inspiration.image_url)


@admin_router.post("/admin/inspirations/batch", response_model=BatchCreateInspirationsResponse)
def admin_batch_create_inspirations(
    body: BatchCreateInspirationsRequest,
    db: Session = Depends(get_db),
    _: dict = Depends(require_admin),
) -> BatchCreateInspirationsResponse:
    created = 0
    skipped = 0
    errors: list[str] = []

    for i, item in enumerate(body.items):
        try:
            # Dedup check
            if item.external_id:
                existing = db.scalar(
                    select(Inspiration).where(
                        Inspiration.source == item.source,
                        Inspiration.external_id == item.external_id,
                    )
                )
                if existing:
                    skipped += 1
                    continue

            inspiration = Inspiration(
                title=item.title,
                description=item.description,
                prompt=item.prompt,
                image_url=item.image_url,
                external_id=item.external_id,
                source=item.source,
                source_url=item.source_url,
                author_name=item.author_name,
                author_url=item.author_url,
                language=item.language or "zh",
                categories=item.categories,
                is_featured=item.is_featured or False,
            )
            db.add(inspiration)
            created += 1
        except Exception as exc:
            errors.append(f"Item {i}: {exc}")

    if created > 0:
        db.commit()

    return BatchCreateInspirationsResponse(created=created, skipped=skipped, errors=errors)


@admin_router.delete("/admin/inspirations/{inspiration_id}", status_code=status.HTTP_204_NO_CONTENT)
def admin_delete_inspiration(
    inspiration_id: str,
    db: Session = Depends(get_db),
    _: dict = Depends(require_admin),
) -> None:
    inspiration = db.get(Inspiration, inspiration_id)
    if not inspiration:
        raise HTTPException(status_code=404, detail="灵感不存在。")
    if inspiration.image_object_key:
        try:
            MinioStorageService().delete_object(inspiration.image_object_key)
        except Exception:
            logger.warning("Failed to delete MinIO object %s", inspiration.image_object_key)
    db.delete(inspiration)
    db.commit()
