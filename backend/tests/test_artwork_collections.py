from datetime import datetime, timedelta, timezone
from io import BytesIO

import pytest
from fastapi import HTTPException
from PIL import Image
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.requests import Request

from app.api import artwork_routes as routes, artwork_media_routes as media
from app.api.user_routes import update_me
from app.db.base import Base
from app.models.artwork import CommunitySubmission, Favorite
from app.models.generation_job import GenerationJob, JobStatus
from app.models.inspiration import Inspiration
from app.models.media import MediaState, MediaDeletionTask
from app.models.user import User
from app.schemas.artwork import GalleryMembershipRequest, SubmissionRequest
from app.schemas.auth import UpdateUserRequest
from app.services.artworks import artwork_item, artwork_items
from app.services.community import review_submission
from app.services.media_lifecycle import refresh_submission_states, process_media_deletions, enqueue_deletion
from app.services.thumbnails import make_thumbnail, prepare_thumbnail


@pytest.fixture
def data():
    engine = create_engine('sqlite+pysqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    owner = User(id='owner', username='owner', password_hash='x', is_public=True)
    viewer = User(id='viewer', username='viewer', password_hash='x')
    job = GenerationJob(id='job', user_id=owner.id, prompt='original prompt', model='test',
        status=JobStatus.SUCCEEDED, media_state=MediaState.AVAILABLE, object_key='original.png',
        media_hash='a' * 64, thumbnail_key='thumb.webp', thumbnail_hash='b' * 64,
        finished_at=datetime.now(timezone.utc), media_expires_at=datetime.now(timezone.utc) + timedelta(hours=48))
    db.add_all([owner, viewer, job]); db.commit()
    yield db, owner, viewer, job
    db.close(); engine.dispose()


def req(headers=None, method='GET'):
    return Request({'type': 'http', 'method': method, 'path': '/',
                    'headers': [(k.encode(), v.encode()) for k,v in (headers or {}).items()]})


def favorite_page(db, user, state='all'):
    return routes.favorites(page=1, page_size=20, state=state, db=db, user=user)


def test_favorite_permissions_idempotency_and_tombstones(data):
    db, owner, viewer, job = data
    with pytest.raises(HTTPException): routes.add_favorite('job', job.id, db, viewer)
    routes.add_favorite('job', job.id, db, owner)
    routes.join_gallery(job.id, GalleryMembershipRequest(is_prompt_public=False), db, owner)
    routes.add_favorite('job', job.id, db, viewer)
    routes.add_favorite('job', job.id, db, viewer)
    page = favorite_page(db, viewer)
    assert page.total == 1 and page.items[0].prompt == ''
    expires = job.media_expires_at
    assert routes.add_favorite('job', job.id, db, owner)['media_expires_at'].replace(tzinfo=None) == expires.replace(tzinfo=None)
    routes.leave_gallery(job.id, db, owner)
    hidden = favorite_page(db, viewer, 'unavailable')
    assert hidden.total == 1
    assert hidden.items[0].image_url is None and hidden.items[0].thumbnail_url is None
    assert hidden.items[0].prompt == '' and hidden.items[0].username is None
    assert favorite_page(db, viewer, 'available').total == 0
    assert routes.clear_unavailable_favorites(db, viewer) == {'removed': 1}
    assert favorite_page(db, owner).total == 1


def test_collection_expiry_and_imported_favorite_filter(data):
    db, owner, viewer, job = data
    routes.add_favorite('job', job.id, db, owner)
    item = Inspiration(id='import', title='Imported', prompt='example', source='imported',
        image_url='/old', image_object_key='import.png', media_state=MediaState.AVAILABLE)
    db.add(item); db.commit()
    routes.add_favorite('inspiration', item.id, db, owner)
    job.media_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1); db.commit()
    assert favorite_page(db, owner, 'unavailable').total == 1
    assert favorite_page(db, owner, 'available').total == 1
    assert routes.clear_unavailable_favorites(db, owner)['removed'] == 1
    assert favorite_page(db, owner).items[0].id == 'import'


def test_history_retains_all_states_but_no_expired_image_urls(data):
    db, owner, viewer, job = data
    job.media_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.add(GenerationJob(id='failed', user_id=owner.id, model='test', prompt='failed prompt', status=JobStatus.FAILED))
    db.add(GenerationJob(id='private-other', user_id=viewer.id, model='test', prompt='other secret'))
    db.commit()
    page = routes.history(page=1, page_size=20, state='all', q='', from_date=None, to_date=None, db=db, user=owner)
    assert page.total == 2
    assert {i.status for i in page.items} == {'failed','succeeded'}
    assert all(i.image_url is None and i.thumbnail_url is None for i in page.items)
    assert next(i for i in page.items if i.id == job.id).prompt == 'original prompt'


class CopyStorage:
    def __init__(self): self.copies = 0
    def copy_generated_image_to_inspiration(self, key, *, inspiration_id):
        self.copies += 1
        return 'curated/' + inspiration_id


def test_submission_is_explicit_and_independent_of_gallery(data):
    db, owner, viewer, job = data
    storage = CopyStorage()
    with pytest.raises(HTTPException): review_submission(db, job.id, 'approve', storage=storage)
    owner.is_public = False; db.commit()
    with pytest.raises(HTTPException): routes.submit_community(job.id, SubmissionRequest(consent_public_prompt=True), db, owner)
    owner.is_public = True; db.commit()
    routes.submit_community(job.id, SubmissionRequest(consent_public_prompt=True), db, owner)
    assert not job.is_public
    sub = review_submission(db, job.id, 'approve', storage=storage)
    assert sub.status == 'approved' and storage.copies == 1
    review_submission(db, job.id, 'approve', storage=storage)
    assert storage.copies == 1


def test_approved_copy_survives_expiry_and_favorites_share_identity(data):
    db, owner, viewer, job = data
    routes.join_gallery(job.id, GalleryMembershipRequest(), db, owner)
    routes.add_favorite('job', job.id, db, viewer)
    routes.submit_community(job.id, SubmissionRequest(consent_public_prompt=True), db, owner)
    sub = review_submission(db, job.id, 'approve', storage=CopyStorage())
    routes.add_favorite('inspiration', sub.inspiration_id, db, viewer)
    job.media_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    job.object_key, job.media_state = None, MediaState.DELETED
    db.commit()
    assert favorite_page(db, viewer).total == 1
    item = favorite_page(db, viewer).items[0]
    assert item.retention_kind == 'permanent' and item.media_expires_at is None
    page = routes.portfolio(owner.username, 1, 20, db, viewer)
    assert page.total == 1 and page.items[0].retention_kind == 'permanent'
    owner.is_public = False; job.deleted_at = datetime.now(timezone.utc); db.commit()
    assert favorite_page(db, viewer, 'available').total == 1
    with pytest.raises(HTTPException): routes.portfolio(owner.username, 1, 20, db, viewer)


def test_pending_expiration_rejection_resubmission_and_master_switch(data):
    db, owner, viewer, job = data
    routes.submit_community(job.id, SubmissionRequest(consent_public_prompt=True), db, owner)
    with pytest.raises(HTTPException): review_submission(db, job.id, 'reject', '')
    review_submission(db, job.id, 'reject', '请改善构图')
    assert artwork_item(db, 'job', job.id, owner.id)['review_reason'] == '请改善构图'
    routes.submit_community(job.id, SubmissionRequest(consent_public_prompt=True), db, owner)
    update_me(UpdateUserRequest(is_public=False), owner, db)
    assert db.get(CommunitySubmission, job.id).status == 'withdrawn'
    owner.is_public = True; db.commit()
    routes.submit_community(job.id, SubmissionRequest(consent_public_prompt=True), db, owner)
    job.media_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1); db.commit()
    assert refresh_submission_states(db) == 1
    with pytest.raises(HTTPException): review_submission(db, job.id, 'approve', storage=CopyStorage())
    assert db.get(CommunitySubmission, job.id).status == 'expired'


def test_expiry_during_copy_never_publishes(data):
    db, owner, viewer, job = data
    routes.submit_community(job.id, SubmissionRequest(consent_public_prompt=True), db, owner)
    class SlowCopy(CopyStorage):
        def copy_generated_image_to_inspiration(self, key, *, inspiration_id):
            job.media_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            return super().copy_generated_image_to_inspiration(key, inspiration_id=inspiration_id)
    with pytest.raises(HTTPException): review_submission(db, job.id, 'approve', storage=SlowCopy())
    assert not db.scalars(select(Inspiration)).all()
    assert db.scalars(select(MediaDeletionTask)).one().object_key.startswith('curated/')


def test_media_conditional_get_authorizes_before_304_and_never_opens_storage(data, monkeypatch):
    db, owner, viewer, job = data
    monkeypatch.setattr(media, 'MinioStorageService', lambda: pytest.fail('304 must not read object storage'))
    headers = {'if-none-match': '"' + 'b' * 64 + '"'}
    assert media.artwork_file('job', job.id, req(headers), 'thumbnail', db, owner).status_code == 304
    with pytest.raises(HTTPException): media.artwork_file('job', job.id, req(headers), 'thumbnail', db, viewer)
    job.is_public = True; db.commit()
    assert media.artwork_file('job', job.id, req(headers), 'thumbnail', db, None).status_code == 304
    owner.is_public = False; db.commit()
    with pytest.raises(HTTPException): media.artwork_file('job', job.id, req(headers), 'thumbnail', db, None)
    job.media_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1); db.commit()
    with pytest.raises(HTTPException): media.artwork_file('job', job.id, req(headers), 'thumbnail', db, owner)


def test_list_query_count_is_bounded(data):
    db, owner, viewer, job = data
    jobs = [GenerationJob(id=f'j{i}', user_id=owner.id, prompt='x', model='x') for i in range(20)]
    db.add_all(jobs); db.commit()
    calls=[]
    def record(*args): calls.append(args)
    event.listen(db.bind, 'before_cursor_execute', record)
    result=artwork_items(db, [('job', j.id) for j in jobs], owner.id)
    event.remove(db.bind, 'before_cursor_execute', record)
    assert len(result)==20 and len(calls)<=6


def test_thumbnail_dimensions_format_and_no_upscale():
    for size, expected in [((2000,1000),(640,320)),((20,10),(20,10))]:
        buf=BytesIO(); Image.new('RGB',size,'orange').save(buf,'PNG')
        image=Image.open(BytesIO(make_thumbnail(buf.getvalue())))
        assert image.format == 'WEBP' and image.size==expected


def test_thumbnail_failure_does_not_change_generation_status(data):
    db, owner, viewer, job = data
    job.thumbnail_key=None; db.commit()
    assert not prepare_thumbnail(db,job,data=b'bad image',storage=object())
    assert job.status == JobStatus.SUCCEEDED and job.media_state == MediaState.AVAILABLE
    assert job.thumbnail_attempts == 1 and job.thumbnail_retry_at is not None


def test_original_cleanup_also_queues_preview_but_not_curated_copy(data, monkeypatch):
    from app.services import media_lifecycle
    db, owner, viewer, job = data
    enqueue_deletion(db,bucket_type='media',object_key=job.object_key,resource_type='generation_job',resource_id=job.id)
    db.commit()
    class Storage:
        def delete_object(self,key): pass
    monkeypatch.setattr(media_lifecycle,'MinioStorageService',Storage)
    process_media_deletions(db)
    assert job.thumbnail_key is None
    tasks=db.scalars(select(MediaDeletionTask)).all()
    assert {t.object_key for t in tasks}=={'original.png','thumb.webp'}


def test_reference_preview_head_and_304_still_require_owner_and_live_media(data, monkeypatch):
    from app.models.reference_image import ReferenceImage
    db, owner, viewer, _ = data
    ref = ReferenceImage(id='reference', user_id=owner.id, filename='ref.png', object_key='ref.png', content_type='image/png',
        media_state=MediaState.AVAILABLE, media_expires_at=datetime.now(timezone.utc) + timedelta(hours=48),
        thumbnail_key='ref.webp', thumbnail_hash='c'*64, thumbnail_size_bytes=99)
    db.add(ref); db.commit()
    monkeypatch.setattr(media, 'MinioStorageService', lambda: pytest.fail('HEAD/304 must not read storage'))
    response = media.reference_preview(ref.id, req(method='HEAD'), db, owner)
    assert response.headers['content-length'] == '99'
    assert response.headers['cache-control'] == 'private, no-cache, must-revalidate'
    conditional = req({'if-none-match':'W/"'+'c'*64+'"'})
    assert media.reference_preview(ref.id, conditional, db, owner).status_code == 304
    with pytest.raises(HTTPException): media.reference_preview(ref.id, conditional, db, viewer)
    ref.media_expires_at = datetime.now(timezone.utc)-timedelta(seconds=1); db.commit()
    with pytest.raises(HTTPException): media.reference_preview(ref.id, conditional, db, owner)


def test_original_and_thumbnail_choose_same_permanent_asset(data, monkeypatch):
    db, owner, viewer, job = data
    routes.submit_community(job.id, SubmissionRequest(consent_public_prompt=True), db, owner)
    class Storage:
        def copy_generated_image_to_inspiration(self, key, *, inspiration_id): return 'community.png'
    sub = review_submission(db, job.id, 'approve', storage=Storage())
    copy = db.get(Inspiration, sub.inspiration_id)
    copy.thumbnail_key='permanent.webp'; copy.thumbnail_hash='p'*64
    copy.media_hash='o'*64; job.media_state=MediaState.DELETED; job.object_key=None; owner.is_public=False
    db.commit()
    monkeypatch.setattr(media, 'MinioStorageService', lambda: pytest.fail('304 must not read storage'))
    assert media.artwork_file('job', job.id, req({'if-none-match':'"'+'p'*64+'"'}), 'thumbnail', db, None).status_code==304
    assert media.artwork_file('job', job.id, req({'if-none-match':'"'+'o'*64+'"'}), 'original', db, None).status_code==304
    copy.media_state=MediaState.DELETE_PENDING;db.commit()
    with pytest.raises(HTTPException): media.artwork_file('job', job.id, req({'if-none-match':'"'+'o'*64+'"'}), 'original', db, None)


def test_gallery_prompt_setting_is_distinct_from_owner_read_permission(data):
    db, owner, viewer, job = data
    job.is_prompt_public=False;job.is_public=True;db.commit()
    own=artwork_item(db,'job',job.id,owner.id)
    assert own['prompt']==job.prompt and own['can_view_prompt'] and not own['is_prompt_public']
    other=artwork_item(db,'job',job.id,viewer.id)
    assert other['prompt']=='' and not other['can_view_prompt']
    assert own['media_expires_at'].tzinfo is not None


def test_backfill_skips_expired_and_deleted_and_caps_attempts(data, monkeypatch):
    from app.services import thumbnails
    db, owner, viewer, job = data
    job.thumbnail_key=None;job.thumbnail_attempts=5;db.commit()
    monkeypatch.setattr(thumbnails,'MinioStorageService',lambda:pytest.fail('ineligible backfill must not access storage'))
    assert thumbnails.backfill_thumbnails(db)==0
    job.thumbnail_attempts=0;job.media_expires_at=datetime.now(timezone.utc)-timedelta(hours=1);db.commit()
    assert thumbnails.backfill_thumbnails(db)==0
    job.media_expires_at=datetime.now(timezone.utc)+timedelta(hours=1);job.media_state=MediaState.DELETE_PENDING;db.commit()
    assert thumbnails.backfill_thumbnails(db)==0


def test_admin_queue_filters_effective_state_before_dispatcher_runs(data):
    db, owner, viewer, job = data
    routes.submit_community(job.id, SubmissionRequest(consent_public_prompt=True), db, owner)
    page=lambda state: routes.submissions(state,1,25,db,{})
    assert page('pending')['total']==1
    job.media_expires_at=datetime.now(timezone.utc)-timedelta(seconds=1);db.commit()
    assert page('pending')['total']==0 and page('expired')['total']==1
    assert page('expired')['items'][0]['thumbnail_url'] is None
    owner.is_public=False;db.commit()
    assert page('expired')['total']==0 and page('withdrawn')['total']==1


def test_legacy_gallery_and_favorite_resolve_canonical_collections(data):
    from app.api import routes as legacy
    db, owner, viewer, job = data
    routes.join_gallery(job.id, GalleryMembershipRequest(), db, owner)
    routes.add_favorite('job',job.id,db,owner)
    assert legacy.get_gallery(db,owner,1,20,None,None,None).items[0].is_favorite
    assert not legacy.get_public_gallery(db,viewer,'recent',1,20).items[0].is_favorite
    assert legacy.toggle_job_favorite(job.id,db,owner)=={'is_favorite':False}
    assert not favorite_page(db,owner).items
    routes.submit_community(job.id, SubmissionRequest(consent_public_prompt=True),db,owner)
    class Storage:
        def copy_generated_image_to_inspiration(self,key,*,inspiration_id): return 'permanent.png'
    review_submission(db,job.id,'approve',storage=Storage())
    job.object_key=None;job.media_state=MediaState.DELETED;db.commit()
    result=legacy.get_user_gallery(owner.username,db,1,20)
    assert result.total==1 and '/inspirations/' in result.items[0].image_url
    assert result.items[0].media_expires_at is None


def test_invalid_favorite_filter_handles_curated_import_without_source_job(data):
    db, owner, viewer, job = data
    routes.add_favorite('job',job.id,db,owner)
    job.media_expires_at=datetime.now(timezone.utc)-timedelta(seconds=1)
    db.add(Inspiration(id='import',title='external',prompt='public',image_url='/x',image_object_key='x.png',source='community-curated',media_state=MediaState.AVAILABLE))
    db.commit()
    assert favorite_page(db,owner,'unavailable').total==1
    assert routes.clear_unavailable_favorites(db,owner)['removed']==1
