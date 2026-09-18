from typing import Literal
from hashlib import sha256

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.auth import get_current_user_optional, require_admin, require_current_user
from app.db.session import get_db
from app.models.artwork import CommunitySubmission
from app.models.generation_job import GenerationJob
from app.models.inspiration import Inspiration
from app.models.reference_image import ReferenceImage
from app.models.media import MediaState
from app.models.user import User
from app.services.artworks import expired, original_available, resolve_asset, utcnow
from app.services.storage import MinioStorageService, StorageError

artwork_media_router = APIRouter()


def stream_asset(asset, request: Request, variant: str, *, reference: bool = False):
    """Call only after authorization, including for conditional requests and HEAD."""
    key = asset.thumbnail_key if variant == 'thumbnail' else (asset.image_object_key if isinstance(asset, Inspiration) else asset.object_key)
    if not key:
        raise HTTPException(404, '预览尚未准备完成。', headers={'Cache-Control': 'no-store'})
    digest = asset.thumbnail_hash if variant == 'thumbnail' else asset.media_hash
    # Keys are immutable after publication, including pre-upgrade originals.
    etag = '"' + (digest or sha256(key.encode()).hexdigest()) + '"'
    headers = {'Cache-Control': 'private, no-cache, must-revalidate', 'ETag': etag,
               'Vary': 'Authorization', 'X-Content-Type-Options': 'nosniff'}
    # Auth and resource expiry are checked by the caller before returning 304.
    tags = [value.strip().removeprefix('W/') for value in request.headers.get('if-none-match', '').split(',')]
    if etag in tags or '*' in tags:
        return Response(status_code=304, headers=headers)
    content_type = 'image/webp' if variant == 'thumbnail' else (getattr(asset, 'media_content_type', None) or getattr(asset, 'content_type', None) or 'image/jpeg')
    size = asset.thumbnail_size_bytes if variant == 'thumbnail' else asset.media_size_bytes
    if size is not None:
        headers['Content-Length'] = str(size)
    if request.method == 'HEAD':
        return Response(headers=headers, media_type=content_type)
    storage = MinioStorageService()
    try:
        opened = storage.open_object(key, reference=reference)
    except StorageError:
        raise HTTPException(503, '图片暂时无法读取。', headers={'Cache-Control': 'no-store'}) from None
    return StreamingResponse(storage.iter_response(opened), media_type=content_type, headers=headers)


@artwork_media_router.api_route('/artworks/{kind}/{target_id}/file', methods=['GET', 'HEAD'])
def artwork_file(kind: Literal['job', 'inspiration'], target_id: str, request: Request,
                 variant: Literal['original', 'thumbnail'] = 'original', db: Session = Depends(get_db),
                 user: User | None = Depends(get_current_user_optional)):
    asset = resolve_asset(db, kind, target_id, user.id if user else None)
    if asset is None:
        raise HTTPException(404, '作品不存在、未公开或已过期。', headers={'Cache-Control': 'no-store'})
    return stream_asset(asset, request, variant)


@artwork_media_router.api_route('/admin/community-submissions/{job_id}/file', methods=['GET', 'HEAD'])
def submission_file(job_id: str, request: Request, variant: Literal['original', 'thumbnail'] = 'original',
                    db: Session = Depends(get_db), _: dict = Depends(require_admin)):
    sub = db.get(CommunitySubmission, job_id)
    job = db.get(GenerationJob, job_id)
    owner = db.get(User, sub.user_id) if sub else None
    if not sub or sub.status != 'pending' or not owner or not owner.is_public or not job or not original_available(job):
        raise HTTPException(404, '投稿已失效。', headers={'Cache-Control': 'no-store'})
    return stream_asset(job, request, variant)


@artwork_media_router.api_route('/reference-images/{image_id}/preview', methods=['GET', 'HEAD'])
def reference_preview(image_id: str, request: Request, db: Session = Depends(get_db), user: User = Depends(require_current_user)):
    asset = db.get(ReferenceImage, image_id)
    if not asset or asset.user_id != user.id or asset.media_state != MediaState.AVAILABLE or expired(asset.media_expires_at):
        raise HTTPException(404, '参考图已失效。', headers={'Cache-Control': 'no-store'})
    return stream_asset(asset, request, 'thumbnail', reference=True)
