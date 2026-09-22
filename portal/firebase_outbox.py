"""Durable Firebase delivery: failed writes remain pending for the worker."""
from datetime import timedelta
from django.utils import timezone
from django.db.models import Case, When, Value, IntegerField
from .models import FirebaseOutbox
from .firebase_sync import _json_ready, write_firebase_document


def enqueue_document(collection, document_id, payload):
    return FirebaseOutbox.objects.update_or_create(collection=collection, document_id=document_id,
        defaults={'payload':_json_ready(payload), 'sent_at':None, 'next_run':timezone.now(), 'error':''})[0]


def flush_outbox(limit=10):
    sent = 0
    for item in FirebaseOutbox.objects.filter(sent_at__isnull=True, next_run__lte=timezone.now()).order_by(Case(When(collection='tag_feedback',then=Value(0)),When(collection='training_validations',then=Value(1)),default=Value(2),output_field=IntegerField()),'pk')[:limit]:
        try:
            write_firebase_document(item.collection, item.document_id, item.payload)
            item.sent_at = timezone.now()
            item.error = ''
            sent += 1
        except Exception:
            item.attempts += 1
            item.error = 'Synchronisation Firebase indisponible ; nouvelle tentative programmée.'
            item.next_run = timezone.now() + timedelta(seconds=min(3600, 30 * 2**min(item.attempts,7)))
        FirebaseOutbox.objects.filter(pk=item.pk,payload=item.payload).update(sent_at=item.sent_at,error=item.error,attempts=item.attempts,next_run=item.next_run)
    return sent
