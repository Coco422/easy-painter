"""MCP tool business adapter; no independent charge or dispatch path."""
import hashlib
import json
from datetime import timedelta

import jwt
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api import routes
from app.core.config import get_settings
from app.models.agent import AgentUsage
from app.models.generation_job import GenerationJob
from app.models.user import User
from app.schemas.job import CreateJobRequest
from app.services import agent_auth as auth
from app.services.auth_sessions import utcnow
from app.services.reference_images import MAX_REFERENCE_IMAGE_BYTES, validate_reference_image
from app.services.storage import MinioStorageService, StorageError
from app.services.model_pricing import base_credit_cost_for_size


def owned_job(db: Session, user_id: str, job_id: str) -> GenerationJob:
    row = db.get(GenerationJob, job_id)
    if not row or row.user_id != user_id or row.deleted_at:
        raise HTTPException(404, '任务不存在。')
    return row


def estimate(db: Session, user: User, model: str, size: str = 'auto', *, editing: bool = False) -> dict:
    request = CreateJobRequest(prompt='estimate', model=model, size=size)
    meta = routes.get_public_meta(db=db, settings=get_settings(), current_user=user)
    item = next((m for m in meta.models if m.id == model and m.enabled), None)
    if not item: raise HTTPException(422, '当前模型不可用。')
    if editing and not item.supports_reference_image: raise HTTPException(422, '当前模型不支持改图。')
    if item.supported_sizes and request.size not in item.supported_sizes: raise HTTPException(422, '模型不支持此尺寸。')
    return {
        'model': item.id,
        'size': request.size,
        'credit_cost': base_credit_cost_for_size(item.model_dump(), request.size),
        'images': 1,
    }


def submit(db: Session, redis_client, grant_id: str, *, prompt: str, model: str, size: str,
           request_id: str, max_cost: int, source_job_id: str | None = None) -> dict:
    if not routes.IDEMPOTENCY_KEY_PATTERN.fullmatch(request_id): raise HTTPException(422, 'request_id 必须是 1–128 位安全请求标识。')
    grant, user = auth.grant_for_update(db, grant_id)
    if 'jobs:create' not in grant.scopes or (source_job_id and 'jobs:read' not in grant.scopes):
        raise HTTPException(403, '此连接没有执行该操作的权限。')
    payload = CreateJobRequest(prompt=prompt, model=model, size=size)
    request_digest = auth.digest(json.dumps(dict(prompt=prompt, model=model, size=size, source_job_id=source_job_id, max_cost=max_cost), sort_keys=True, ensure_ascii=False))
    previous = db.scalar(select(AgentUsage).where(AgentUsage.grant_id == grant.id, AgentUsage.request_key == request_id))
    if previous:
        if previous.request_digest != request_digest: raise HTTPException(409, '此 request_id 已用于不同参数。')
        return {'job_id': previous.job_id, 'replayed': True, 'next_action': 'get_job'}
    reference = None
    if source_job_id:
        job = owned_job(db, user.id, source_job_id)
        if not routes._job_has_available_media(job): raise HTTPException(410, '原图已过期或不可用。')
        stream = MinioStorageService().iter_object(job.object_key)
        data = bytearray()
        try:
            for chunk in stream:
                data.extend(chunk)
                if len(data) > MAX_REFERENCE_IMAGE_BYTES: raise HTTPException(422, '原图超过 10MB，请在网站处理。')
        except StorageError:
            raise HTTPException(503, '原图暂时无法读取。') from None
        finally:
            if hasattr(stream, 'close'): stream.close()
        reference = validate_reference_image(filename=f'{job.id}.png', content_type=job.media_content_type, image_bytes=bytes(data))
        if not routes._job_has_available_media(job): raise HTTPException(410, '原图已过期。')
    # Namespace the key so two clients cannot collide with each other or web UI.
    key = f'agent:{grant.id}:{auth.digest(request_id)}'
    result = routes.create_generation_job(routes.ParsedCreateJobPayload(payload, reference), key, db, redis_client,
                                          get_settings(), user, agent_context=(grant.id, request_id, request_digest, max_cost))
    return {**result.model_dump(mode='json'), 'next_action': 'get_job', 'poll_after_seconds': 3}


def job_result(db: Session, grant_id: str, job_id: str) -> dict:
    from app.models.agent import AgentGrant
    grant = db.get(AgentGrant, grant_id)
    job = owned_job(db, grant.user_id, job_id)
    detail = routes._build_job_detail_response(db, job, viewer_user_id=grant.user_id)
    result = {key: getattr(detail, key) for key in ['job_id', 'status', 'prompt', 'model', 'size', 'credit_cost', 'billing_status', 'error_message', 'media_state']}
    result['media_expires_at'] = detail.media_expires_at.isoformat() if detail.media_expires_at else None
    result['website_url'] = auth.origin_url() + '/history'
    result['poll_after_seconds'] = 3 if detail.status in ['queued', 'processing'] else None
    if routes._job_has_available_media(job):
        expires = min(utcnow() + timedelta(minutes=5), auth.as_utc(grant.expires_at))
        if job.media_expires_at: expires = min(expires, auth.as_utc(job.media_expires_at))
        settings = get_settings()
        token = jwt.encode({'typ': 'agent_media', 'aud': 'agent_media', 'grant': grant.id, 'job': job.id,
                            'exp': expires, 'resource': auth.resource_url()}, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
        result['image_url'] = auth.origin_url() + f'/api/v1/agent/media/{job.id}?token={token}'
        result['download_expires_at'] = expires.isoformat()
    return result
