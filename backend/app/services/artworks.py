"""One access policy for history, portfolios, favorites and media responses."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.models.artwork import CommunitySubmission, Favorite
from app.models.generation_job import GenerationJob, JobStatus
from app.models.inspiration import Inspiration
from app.models.job_charge import JobCharge
from app.models.media import MediaState
from app.models.user import User


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def timestamp(value: datetime | None) -> datetime | None:
    return value.replace(tzinfo=timezone.utc) if value is not None and value.tzinfo is None else value


def expired(value: datetime | None, now: datetime | None = None) -> bool:
    if value is None:
        return False
    value = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    return value <= (now or utcnow())


def original_available(job: GenerationJob, now: datetime | None = None) -> bool:
    return bool(job.status == JobStatus.SUCCEEDED and job.deleted_at is None
                and job.media_state == MediaState.AVAILABLE and job.object_key
                and not expired(job.media_expires_at, now))


def live_original_clause(now: datetime | None = None):
    return and_(GenerationJob.status == JobStatus.SUCCEEDED, GenerationJob.deleted_at.is_(None),
                GenerationJob.media_state == MediaState.AVAILABLE, GenerationJob.object_key.is_not(None),
                or_(GenerationJob.media_expires_at.is_(None), GenerationJob.media_expires_at > (now or utcnow())))


def live_inspiration_clause():
    return and_(Inspiration.deleted_at.is_(None), Inspiration.media_state == MediaState.AVAILABLE,
                Inspiration.image_object_key.is_not(None))


def curated_exists_clause():
    return select(Inspiration.id).where(
        Inspiration.source_job_id == GenerationJob.id, Inspiration.source == 'community-curated',
        live_inspiration_clause(),
    ).exists()


def available_job_clause(now: datetime | None = None):
    return or_(live_original_clause(now), curated_exists_clause())


def curated_for_job(db: Session, job_id: str) -> Inspiration | None:
    return db.scalar(select(Inspiration).where(
        Inspiration.source_job_id == job_id, Inspiration.source == 'community-curated',
        live_inspiration_clause(),
    ).order_by(Inspiration.created_at, Inspiration.id).limit(1))


def canonical_target(db: Session, kind: str, target_id: str) -> tuple[str, str]:
    if kind == 'inspiration':
        item = db.get(Inspiration, target_id)
        if item and item.source == 'community-curated' and item.source_job_id:
            return 'job', item.source_job_id
    return kind, target_id


def effective_submission(sub: CommunitySubmission | None, job: GenerationJob | None, owner: User | None) -> str:
    if not sub:
        return 'none'
    if sub.status == 'pending':
        if not owner or not owner.is_public or not job or job.deleted_at is not None:
            return 'withdrawn'
        if not original_available(job):
            return 'expired'
    return sub.status


def resolve_asset(db: Session, kind: str, target_id: str, viewer_id: str | None, *, context=None):
    """Return an authorized live source. A favorite never confers access."""
    if kind == 'inspiration':
        item = context.inspirations.get(target_id) if context else db.get(Inspiration, target_id)
        if item and item.deleted_at is None and item.media_state == MediaState.AVAILABLE and item.image_object_key:
            return item
        return None
    job = context.jobs.get(target_id) if context else db.get(GenerationJob, target_id)
    curated = context.curated.get(target_id) if context else curated_for_job(db, target_id)
    if curated:
        return curated
    if not job or not original_available(job):
        return None
    owner = context.owners.get(job.user_id) if context else (db.get(User, job.user_id) if job.user_id else None)
    if viewer_id == job.user_id and viewer_id is not None:
        return job
    if job.is_public and (job.user_id is None or (owner and owner.is_public)):
        return job
    return None


def media_url(kind: str, target_id: str, asset, variant: str = 'original') -> str:
    version = asset.thumbnail_hash if variant == 'thumbnail' else asset.media_hash
    return f'/api/v1/artworks/{kind}/{target_id}/file?variant={variant}' + (f'&v={version}' if version else '')


def artwork_item(db: Session, kind: str, target_id: str, viewer_id: str | None, *, favorite: Favorite | None = None, context=None) -> dict[str, Any]:
    if context:
        target = context.inspirations.get(target_id) if kind == 'inspiration' else None
        if target and target.source == 'community-curated' and target.source_job_id:
            kind, target_id = 'job', target.source_job_id
    else:
        kind, target_id = canonical_target(db, kind, target_id)
    job = (context.jobs.get(target_id) if context else db.get(GenerationJob, target_id)) if kind == 'job' else None
    item = (context.inspirations.get(target_id) if context else db.get(Inspiration, target_id)) if kind == 'inspiration' else None
    owner = (context.owners.get(job.user_id) if context else db.get(User, job.user_id)) if job and job.user_id else None
    is_owner = bool(job and viewer_id and viewer_id == job.user_id)
    charge = (context.charges.get(target_id) if context else db.scalar(select(JobCharge).where(JobCharge.job_id == target_id))) if is_owner else None
    asset = resolve_asset(db, kind, target_id, viewer_id, context=context)
    curated = asset if isinstance(asset, Inspiration) else None
    sub = (context.submissions.get(target_id) if context else db.get(CommunitySubmission, target_id)) if job else None
    if favorite is None and viewer_id:
        target_clause = Favorite.job_id == target_id if kind == 'job' else Favorite.inspiration_id == target_id
        favorite = context.favorites.get((kind, target_id)) if context else db.scalar(select(Favorite).where(Favorite.user_id == viewer_id, target_clause))
    prompt_visible = bool(asset and (curated or item or (job and job.is_prompt_public))) or is_owner
    source_prompt = (curated or item).prompt if (curated or item) and not is_owner else (job.prompt if job else '')
    state = 'available' if asset else ('expired' if job and expired(job.media_expires_at) else 'unavailable')
    if job and job.status in (JobStatus.QUEUED, JobStatus.PROCESSING, JobStatus.FAILED) and not asset:
        state = 'none'
    # Tombstones deliberately contain no metadata belonging to an inaccessible author.
    metadata_visible = bool(asset or is_owner)
    return {
        'kind': kind, 'id': target_id, 'job_id': job.id if job else None,
        'favorite_id': favorite.id if favorite else None,
        'inspiration_id': curated.id if curated else (item.id if item else None),
        'title': ((curated or item).title if (curated or item) else '') if metadata_visible else '',
        'prompt': source_prompt if prompt_visible else '',
        'revised_prompt': job.revised_prompt if job and prompt_visible and not curated else None,
        'is_prompt_public': bool(job.is_prompt_public if job and metadata_visible else (asset if not job else False)),
        'can_view_prompt': bool(prompt_visible),
        'username': owner.username if owner and metadata_visible else None,
        'is_owner': is_owner,
        'is_in_gallery': bool(job and job.is_public) if metadata_visible else False,
        'gallery_visible': bool(job and job.is_public and owner and owner.is_public and asset),
        'is_favorite': favorite is not None,
        'tags': (job.tags or []) if job and metadata_visible else [],
        'status': job.status.value if job and metadata_visible else ('succeeded' if asset else None),
        'model': job.model if job and metadata_visible else '',
        'size': job.size if job and metadata_visible else 'auto',
        'aspect_ratio': job.aspect_ratio if job and metadata_visible else 'auto',
        'created_at': timestamp(job.created_at) if job and metadata_visible else (timestamp(item.created_at) if item and asset else None),
        'finished_at': timestamp(job.finished_at) if job and metadata_visible else None,
        'favorited_at': timestamp(favorite.created_at) if favorite else None,
        'credit_cost': (charge.amount if charge else job.credit_cost_snapshot) if job and is_owner else None,
        'billing_status': (charge.status.value if charge else 'not_charged') if is_owner else None,
        'error_message': job.error_message if job and is_owner else None,
        'media_state': state,
        'media_expires_at': timestamp(job.media_expires_at) if job and not curated and metadata_visible else None,
        'original_expires_at': timestamp(job.media_expires_at) if job and is_owner else None,
        'retention_kind': 'permanent' if isinstance(asset, Inspiration) else 'temporary',
        'image_url': media_url(kind, target_id, asset) if asset else None,
        'thumbnail_url': media_url(kind, target_id, asset, 'thumbnail') if asset and asset.thumbnail_key else None,
        'submission_status': effective_submission(sub, job, owner) if is_owner else ('approved' if curated else 'none'),
        'review_reason': sub.review_reason if sub and is_owner else None,
    }


class ArtworkContext:
    """Bounded list queries rather than fetching authorization per card."""
    def __init__(self, db: Session, targets: list[tuple[str, str]], viewer_id: str | None):
        inspiration_ids = [target for kind, target in targets if kind == 'inspiration']
        self.inspirations = {i.id: i for i in db.scalars(select(Inspiration).where(Inspiration.id.in_(inspiration_ids))).all()} if inspiration_ids else {}
        job_ids = {target for kind, target in targets if kind == 'job'}
        job_ids.update(i.source_job_id for i in self.inspirations.values() if i.source == 'community-curated' and i.source_job_id)
        self.jobs = {j.id: j for j in db.scalars(select(GenerationJob).where(GenerationJob.id.in_(job_ids))).all()} if job_ids else {}
        self.curated = {i.source_job_id: i for i in db.scalars(select(Inspiration).where(
            Inspiration.source_job_id.in_(job_ids), Inspiration.source == 'community-curated', live_inspiration_clause(),
        )).all()} if job_ids else {}
        owner_ids = {j.user_id for j in self.jobs.values() if j.user_id}
        self.owners = {u.id: u for u in db.scalars(select(User).where(User.id.in_(owner_ids))).all()} if owner_ids else {}
        self.submissions = {s.job_id: s for s in db.scalars(select(CommunitySubmission).where(CommunitySubmission.job_id.in_(job_ids))).all()} if job_ids else {}
        owned_ids = [j.id for j in self.jobs.values() if viewer_id and j.user_id == viewer_id]
        self.charges = {c.job_id: c for c in db.scalars(select(JobCharge).where(JobCharge.job_id.in_(owned_ids))).all()} if owned_ids else {}
        self.favorites = {}
        if viewer_id and targets:
            rows = db.scalars(select(Favorite).where(Favorite.user_id == viewer_id,
                or_(Favorite.job_id.in_(job_ids), Favorite.inspiration_id.in_(inspiration_ids)))).all()
            self.favorites = {('job' if f.job_id else 'inspiration', f.job_id or f.inspiration_id): f for f in rows}


def artwork_items(db: Session, targets: list[tuple[str, str]], viewer_id: str | None) -> list[dict[str, Any]]:
    context = ArtworkContext(db, targets, viewer_id)
    return [artwork_item(db, kind, target, viewer_id, context=context) for kind, target in targets]
