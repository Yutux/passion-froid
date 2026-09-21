"""Persistent analysis queue: one lease per image, retries, and automatic discovery."""
import logging
import threading
from datetime import timedelta
from django.db import close_old_connections
from django.db.models import Q, F
from django.utils import timezone
from django.conf import settings
from .models import MediaAsset, AnalysisJob, WorkerHeartbeat

log = logging.getLogger(__name__)
_thread = None
_stop = threading.Event()


def enqueue_asset(asset, force=False):
    if asset.type_fichier != 'image' or asset.tags_validated or asset.media_status == 'ARCHIVED':
        return None
    job, created = AnalysisJob.objects.get_or_create(asset=asset)
    if force and not (job.status == 'RUNNING' and job.lease_until and job.lease_until > timezone.now()):
        AnalysisJob.objects.filter(pk=job.pk).update(status='PENDING', next_run=timezone.now(), error='', attempts=0)
    return job


def discover_missing():
    images = MediaAsset.objects.filter(type_fichier='image', tags_validated=False).exclude(media_status='ARCHIVED')
    # Reviewed drafts are protected; only unanalysed images and metadata fallbacks are queued.
    images = images.filter(Q(ai_tags=[]) | Q(ai_tag_source='') | Q(ai_tag_source__startswith='metadata-fallback'))
    for asset in images.iterator():
        if (asset.ai_analysis or {}).get('draftUpdatedAt'):
            continue
        enqueue_asset(asset)


def claim_job():
    now = timezone.now()
    eligible = Q(status__in=['PENDING','RETRY'], next_run__lte=now) | Q(status='RUNNING', lease_until__lt=now)
    for job_id in AnalysisJob.objects.filter(eligible).order_by('-asset__cree_le','next_run').values_list('pk',flat=True)[:10]:
        claimed = AnalysisJob.objects.filter(pk=job_id).filter(eligible).update(status='RUNNING', lease_until=now+timedelta(minutes=8), attempts=F('attempts')+1, updated_at=now)
        if claimed:
            return AnalysisJob.objects.select_related('asset').get(pk=job_id)
    return None


def process_one():
    job = claim_job()
    if not job:
        return False
    asset = job.asset
    if asset.tags_validated or asset.media_status == 'ARCHIVED' or (asset.ai_analysis or {}).get('draftUpdatedAt'):
        AnalysisJob.objects.filter(pk=job.pk).update(status='DONE', error='', lease_until=None)
        return True
    MediaAsset.objects.filter(pk=asset.pk).update(media_status='AI_ANALYZING')
    try:
        from .views import _store_ai_tags
        from .image_memory import ensure_fingerprint
        ensure_fingerprint(asset)
        _store_ai_tags(asset, allow_fallback=False)
        AnalysisJob.objects.filter(pk=job.pk).update(status='DONE', error='', lease_until=None, updated_at=timezone.now())
    except Exception as exc:
        from .ai_tags import TaggingError
        message = str(exc)[:500] if isinstance(exc, TaggingError) else 'Analyse distante indisponible. Nouvelle tentative automatique programmée.'
        delay = min(3600, 60 * 2**min(job.attempts,6))
        AnalysisJob.objects.filter(pk=job.pk).update(status='RETRY', error=message, next_run=timezone.now()+timedelta(seconds=delay), lease_until=None, updated_at=timezone.now())
        MediaAsset.objects.filter(pk=asset.pk, tags_validated=False, media_status='AI_ANALYZING').update(media_status='NEEDS_CORRECTION')
    return True


def run_worker(stop_event=None, poll=10):
    import time
    from .firebase_outbox import flush_outbox
    last_scan = 0
    stopper = stop_event or threading.Event()
    while not stopper.is_set():
        close_old_connections()
        try:
            WorkerHeartbeat.objects.update_or_create(name='analysis',defaults={'last_seen':timezone.now()})
            if time.monotonic()-last_scan > 30:
                discover_missing()
                last_scan = time.monotonic()
            flush_outbox(limit=3)
            if process_one():
                stopper.wait(2)
            else:
                stopper.wait(poll)
        except Exception:
            log.exception('Le worker IA reprendra après une erreur transitoire.')
            stopper.wait(poll)
        finally:
            close_old_connections()


def start_worker():
    global _thread
    if not getattr(settings, 'AI_WORKER_ENABLED', True) or (_thread and _thread.is_alive()):
        return
    _thread = threading.Thread(target=run_worker, args=(_stop,), name='passionfroid-ai-worker', daemon=True)
    _thread.start()
