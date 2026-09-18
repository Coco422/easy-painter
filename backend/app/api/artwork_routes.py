from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.auth import get_current_user_optional, require_admin, require_current_user
from app.db.session import get_db
from app.models.artwork import CommunitySubmission, Favorite
from app.models.generation_job import GenerationJob, JobStatus
from app.models.inspiration import Inspiration
from app.models.user import User
from app.schemas.artwork import ArtworkItem, ArtworkPage, GalleryMembershipRequest, ReviewRequest, SubmissionRequest
from app.services.artworks import (ArtworkContext, artwork_item, artwork_items, available_job_clause, canonical_target, curated_for_job,
    effective_submission, live_inspiration_clause, live_original_clause, original_available, resolve_asset, utcnow)
from app.services.community import review_submission

def private_metadata(response: Response):
    response.headers['Cache-Control'] = 'private, no-store'


artwork_router = APIRouter(dependencies=[Depends(private_metadata)])
Kind = Literal['job', 'inspiration']


def page_items(db, statement, page, page_size):
    total = db.scalar(select(func.count()).select_from(statement.order_by(None).subquery())) or 0
    return db.scalars(statement.offset((page - 1) * page_size).limit(page_size)).all(), total


def owned_job(db: Session, job_id: str, user: User) -> GenerationJob:
    job = db.scalar(select(GenerationJob).where(GenerationJob.id == job_id).with_for_update().execution_options(populate_existing=True))
    if not job or job.user_id != user.id or job.deleted_at is not None:
        raise HTTPException(404, '生成记录不存在。')
    return job


@artwork_router.get('/history', response_model=ArtworkPage)
def history(
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    state: Literal['all', 'queued', 'processing', 'succeeded', 'failed', 'expired'] = 'all',
    q: str = Query('', max_length=200), from_date: datetime | None = None, to_date: datetime | None = None,
    db: Session = Depends(get_db), user: User = Depends(require_current_user),
):
    stmt = select(GenerationJob).where(GenerationJob.user_id == user.id, GenerationJob.deleted_at.is_(None))
    if state == 'expired':
        stmt = stmt.where(GenerationJob.status == JobStatus.SUCCEEDED, ~available_job_clause())
    elif state != 'all':
        stmt = stmt.where(GenerationJob.status == JobStatus(state))
    if q.strip():
        stmt = stmt.where(GenerationJob.prompt.ilike(f'%{q.strip()}%'))
    if from_date:
        stmt = stmt.where(GenerationJob.created_at >= from_date)
    if to_date:
        stmt = stmt.where(GenerationJob.created_at < to_date + timedelta(days=1))
    jobs, total = page_items(db, stmt.order_by(desc(GenerationJob.created_at), desc(GenerationJob.id)), page, page_size)
    return ArtworkPage(items=artwork_items(db, [('job', j.id) for j in jobs], user.id), total=total, page=page, page_size=page_size)


@artwork_router.get('/portfolios/{username}', response_model=ArtworkPage)
def portfolio(username: str, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
              db: Session = Depends(get_db), user: User | None = Depends(get_current_user_optional)):
    owner = db.scalar(select(User).where(User.username == username))
    if not owner or (not owner.is_public and (not user or user.id != owner.id)):
        raise HTTPException(404, '画廊不存在或尚未公开。')
    stmt = select(GenerationJob).where(GenerationJob.user_id == owner.id,
        GenerationJob.is_public.is_(True), GenerationJob.deleted_at.is_(None), available_job_clause())
    jobs, total = page_items(db, stmt.order_by(desc(GenerationJob.finished_at), desc(GenerationJob.id)), page, page_size)
    return ArtworkPage(items=artwork_items(db, [('job', j.id) for j in jobs], user.id if user else None), total=total, page=page, page_size=page_size)


@artwork_router.put('/jobs/{job_id}/gallery', response_model=ArtworkItem)
def join_gallery(job_id: str, body: GalleryMembershipRequest, db: Session = Depends(get_db), user: User = Depends(require_current_user)):
    job = owned_job(db, job_id, user)
    if not original_available(job) and not curated_for_job(db, job_id):
        raise HTTPException(409, '只能将仍可查看的成功作品加入画廊。')
    job.is_public, job.tags, job.is_prompt_public = True, [tag.strip()[:20] for tag in body.tags if tag.strip()], body.is_prompt_public
    db.commit()
    return artwork_item(db, 'job', job.id, user.id)


@artwork_router.delete('/jobs/{job_id}/gallery', response_model=ArtworkItem)
def leave_gallery(job_id: str, db: Session = Depends(get_db), user: User = Depends(require_current_user)):
    job = owned_job(db, job_id, user)
    job.is_public = False
    db.commit()
    return artwork_item(db, 'job', job.id, user.id)


def favorite_available_clause(user_id: str):
    public_jobs = select(GenerationJob.id).outerjoin(User, User.id == GenerationJob.user_id).where(
        live_original_clause(), or_(GenerationJob.user_id == user_id,
            and_(GenerationJob.is_public.is_(True), or_(GenerationJob.user_id.is_(None), User.is_public.is_(True)))))
    curated_jobs = select(Inspiration.source_job_id).where(Inspiration.source == 'community-curated',
        Inspiration.source_job_id.is_not(None), live_inspiration_clause())
    inspirations = select(Inspiration.id).where(live_inspiration_clause())
    return or_(and_(Favorite.job_id.is_not(None), or_(Favorite.job_id.in_(public_jobs), Favorite.job_id.in_(curated_jobs))),
               and_(Favorite.inspiration_id.is_not(None), Favorite.inspiration_id.in_(inspirations)))


@artwork_router.get('/favorites', response_model=ArtworkPage)
def favorites(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
              state: Literal['all', 'available', 'unavailable'] = 'all',
              db: Session = Depends(get_db), user: User = Depends(require_current_user)):
    stmt = select(Favorite).where(Favorite.user_id == user.id)
    if state != 'all':
        available = favorite_available_clause(user.id)
        stmt = stmt.where(available if state == 'available' else ~available)
    rows, total = page_items(db, stmt.order_by(desc(Favorite.created_at), desc(Favorite.id)), page, page_size)
    return ArtworkPage(items=artwork_items(db, [('job' if f.job_id else 'inspiration', f.job_id or f.inspiration_id) for f in rows], user.id), total=total, page=page, page_size=page_size)


@artwork_router.delete('/favorites/unavailable')
def clear_unavailable_favorites(db: Session = Depends(get_db), user: User = Depends(require_current_user)):
    rows = db.scalars(select(Favorite).where(Favorite.user_id == user.id, ~favorite_available_clause(user.id))).all()
    for row in rows:
        db.delete(row)
    db.commit()
    return {'removed': len(rows)}


@artwork_router.put('/favorites/{kind}/{target_id}', response_model=ArtworkItem)
def add_favorite(kind: Kind, target_id: str, db: Session = Depends(get_db), user: User = Depends(require_current_user)):
    kind, target_id = canonical_target(db, kind, target_id)
    if resolve_asset(db, kind, target_id, user.id) is None:
        raise HTTPException(404, '作品不存在、未公开或已过期。')
    clause = Favorite.job_id == target_id if kind == 'job' else Favorite.inspiration_id == target_id
    if not db.scalar(select(Favorite).where(Favorite.user_id == user.id, clause)):
        db.add(Favorite(user_id=user.id, job_id=target_id if kind == 'job' else None,
                        inspiration_id=target_id if kind == 'inspiration' else None))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            if not db.scalar(select(Favorite).where(Favorite.user_id == user.id, clause)):
                raise
    return artwork_item(db, kind, target_id, user.id)


@artwork_router.delete('/favorites/{kind}/{target_id}', status_code=204)
def remove_favorite(kind: Kind, target_id: str, db: Session = Depends(get_db), user: User = Depends(require_current_user)):
    kind, target_id = canonical_target(db, kind, target_id)
    clause = Favorite.job_id == target_id if kind == 'job' else Favorite.inspiration_id == target_id
    item = db.scalar(select(Favorite).where(Favorite.user_id == user.id, clause))
    if item:
        db.delete(item)
        db.commit()


@artwork_router.post('/jobs/{job_id}/community-submission', response_model=ArtworkItem)
def submit_community(job_id: str, body: SubmissionRequest, db: Session = Depends(get_db), user: User = Depends(require_current_user)):
    owner = db.scalar(select(User).where(User.id == user.id).with_for_update().execution_options(populate_existing=True))
    if not owner.is_public:
        raise HTTPException(409, '请先在个人中心开启公开作品总开关。')
    job = owned_job(db, job_id, user)
    if not original_available(job):
        raise HTTPException(409, '图片已过期或尚未生成完成。')
    sub = db.get(CommunitySubmission, job_id)
    if sub and sub.status in ('pending', 'approved'):
        return artwork_item(db, 'job', job_id, user.id)
    if sub is None:
        sub = CommunitySubmission(job_id=job_id, user_id=user.id)
        db.add(sub)
    sub.status, sub.submitted_at, sub.reviewed_at, sub.review_reason = 'pending', utcnow(), None, None
    db.commit()
    return artwork_item(db, 'job', job_id, user.id)


@artwork_router.delete('/jobs/{job_id}/community-submission', response_model=ArtworkItem)
def withdraw_community(job_id: str, db: Session = Depends(get_db), user: User = Depends(require_current_user)):
    db.scalar(select(User).where(User.id == user.id).with_for_update().execution_options(populate_existing=True))
    job = owned_job(db, job_id, user)
    sub = db.get(CommunitySubmission, job_id)
    if sub and sub.status == 'pending':
        sub.status, sub.reviewed_at = 'withdrawn', utcnow()
        db.commit()
    return artwork_item(db, 'job', job.id, user.id)


@artwork_router.get('/admin/community-submissions')
def submissions(state: Literal['pending', 'approved', 'rejected', 'withdrawn', 'expired', 'all'] = 'pending',
                page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100),
                db: Session = Depends(get_db), _: dict = Depends(require_admin)):
    stmt = select(CommunitySubmission)
    owner_open = select(User.id).where(User.id == CommunitySubmission.user_id, User.is_public.is_(True)).exists()
    job_exists = select(GenerationJob.id).where(GenerationJob.id == CommunitySubmission.job_id, GenerationJob.deleted_at.is_(None)).exists()
    job_live = select(GenerationJob.id).where(GenerationJob.id == CommunitySubmission.job_id, live_original_clause()).exists()
    pending = CommunitySubmission.status == 'pending'
    if state == 'pending':
        stmt = stmt.where(pending, owner_open, job_live)
    elif state == 'expired':
        stmt = stmt.where(or_(CommunitySubmission.status == state, and_(pending, owner_open, job_exists, ~job_live)))
    elif state == 'withdrawn':
        stmt = stmt.where(or_(CommunitySubmission.status == state, and_(pending, or_(~owner_open, ~job_exists))))
    elif state != 'all':
        stmt = stmt.where(CommunitySubmission.status == state)
    rows, total = page_items(db, stmt.order_by(CommunitySubmission.submitted_at, CommunitySubmission.job_id), page, page_size)
    context = ArtworkContext(db, [('job', sub.job_id) for sub in rows], None)
    items = []
    for sub in rows:
        item = artwork_item(db, 'job', sub.job_id, sub.user_id, context=context)
        item['submission_status'] = effective_submission(sub, context.jobs.get(sub.job_id), context.owners.get(sub.user_id))
        if item['submission_status'] == 'pending':
            item['image_url'] = f'/api/v1/admin/community-submissions/{sub.job_id}/file'
            if item['thumbnail_url']:
                item['thumbnail_url'] = item['image_url'] + '?variant=thumbnail'
        elif item['submission_status'] != 'approved':
            # Withdrawal/rejection closes the review grant. Do not hand the
            # admin UI an owner-only URL that will fail and trigger refreshes.
            item['image_url'] = item['thumbnail_url'] = None
            item['media_state'] = 'expired' if item['submission_status'] == 'expired' else 'unavailable'
        items.append({**item, 'submitted_at': sub.submitted_at, 'reviewed_at': sub.reviewed_at})
    return {'items': items, 'total': total, 'page': page, 'page_size': page_size, 'server_time': utcnow()}


@artwork_router.put('/admin/community-submissions/{job_id}')
def review(job_id: str, body: ReviewRequest, db: Session = Depends(get_db), _: dict = Depends(require_admin)):
    sub = review_submission(db, job_id, body.decision, body.reason)
    return {'job_id': job_id, 'status': sub.status, 'inspiration_id': sub.inspiration_id}


@artwork_router.get('/artworks/{kind}/{target_id}', response_model=ArtworkItem)
def get_artwork(kind: Kind, target_id: str, db: Session = Depends(get_db), user: User | None = Depends(get_current_user_optional)):
    return artwork_item(db, kind, target_id, user.id if user else None)
