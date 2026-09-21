from __future__ import annotations

from django.conf import settings
from django.utils import timezone


class FirebaseSyncSkipped(Exception):
    """Raised when Firebase is not configured for this environment."""


def firebase_is_configured() -> bool:
    return bool(settings.FIREBASE_CREDENTIALS_PATH and settings.FIREBASE_PROJECT_ID)


def sync_asset_to_firestore(asset) -> bool:
    """
    Store the searchable asset index in Firestore.
    Firebase is optional so local demos keep working without credentials.
    """
    if not firebase_is_configured():
        raise FirebaseSyncSkipped("Firebase credentials are not configured.")

    try:
        import firebase_admin
        from firebase_admin import credentials, firestore

        if not firebase_admin._apps:
            cred = credentials.Certificate(settings.FIREBASE_CREDENTIALS_PATH)
            options = {'projectId': settings.FIREBASE_PROJECT_ID}
            if settings.FIREBASE_DATABASE_URL:
                options['databaseURL'] = settings.FIREBASE_DATABASE_URL
            firebase_admin.initialize_app(cred, options)

        db = firestore.client()
        doc_id = asset.firebase_document_id or asset.public_id.replace('/', '_')
        payload = _asset_payload(asset)
        db.collection(settings.FIREBASE_MEDIA_COLLECTION).document(doc_id).set(payload, merge=True, timeout=10, retry=None)
        db.collection('media').document(doc_id).set(payload, merge=True, timeout=10, retry=None)

        asset.firebase_document_id = doc_id
        asset.firebase_synced_at = timezone.now()
        asset.firebase_sync_error = ''
        asset.save(update_fields=[
            'firebase_document_id',
            'firebase_synced_at',
            'firebase_sync_error',
            'modifie_le',
        ])
        return True
    except Exception as exc:
        try:
            _sync_asset_to_realtime_database(asset)
            return True
        except Exception:
            asset.firebase_sync_error = str(exc)
            asset.save(update_fields=['firebase_sync_error', 'modifie_le'])
            raise


def _get_firebase_app():
    if not firebase_is_configured():
        raise FirebaseSyncSkipped("Firebase credentials are not configured.")

    import firebase_admin
    from firebase_admin import credentials

    if not firebase_admin._apps:
        cred = credentials.Certificate(settings.FIREBASE_CREDENTIALS_PATH)
        options = {'projectId': settings.FIREBASE_PROJECT_ID}
        if settings.FIREBASE_DATABASE_URL:
            options['databaseURL'] = settings.FIREBASE_DATABASE_URL
        firebase_admin.initialize_app(cred, options)
    return firebase_admin.get_app()


def _sync_asset_to_realtime_database(asset) -> bool:
    if not settings.FIREBASE_DATABASE_URL:
        raise FirebaseSyncSkipped("Firebase Realtime Database URL is not configured.")

    from firebase_admin import db

    _get_firebase_app()
    doc_id = asset.firebase_document_id or asset.public_id.replace('/', '_')
    payload = _json_ready(_asset_payload(asset))
    db.reference(f"media/{doc_id}", url=settings.FIREBASE_DATABASE_URL).set(payload)
    db.reference(f"{settings.FIREBASE_MEDIA_COLLECTION}/{doc_id}", url=settings.FIREBASE_DATABASE_URL).set(payload)

    asset.firebase_document_id = doc_id
    asset.firebase_synced_at = timezone.now()
    asset.firebase_sync_error = ''
    asset.save(update_fields=[
        'firebase_document_id',
        'firebase_synced_at',
        'firebase_sync_error',
        'modifie_le',
    ])
    return True


def write_firebase_document(collection: str, document_id: str, payload: dict) -> bool:
    if not firebase_is_configured():
        raise FirebaseSyncSkipped("Firebase credentials are not configured.")
    payload = _json_ready({**payload, 'updatedAt': timezone.now()})
    try:
        _get_firebase_app()
        from firebase_admin import firestore
        firestore.client().collection(collection).document(document_id).set(payload, merge=True, timeout=10, retry=None)
        return True
    except Exception:
        if not settings.FIREBASE_DATABASE_URL:
            raise
        from firebase_admin import db
        _get_firebase_app()
        db.reference(f"{collection}/{document_id}", url=settings.FIREBASE_DATABASE_URL).set(payload)
        return True


def push_firebase_document(collection: str, payload: dict) -> str:
    payload = _json_ready({**payload, 'createdAt': timezone.now()})
    try:
        _get_firebase_app()
        from firebase_admin import firestore
        doc = firestore.client().collection(collection).document()
        doc.set(payload)
        return doc.id
    except Exception:
        if not settings.FIREBASE_DATABASE_URL:
            raise
        from firebase_admin import db
        _get_firebase_app()
        ref = db.reference(collection, url=settings.FIREBASE_DATABASE_URL).push(payload)
        return ref.key


def _asset_payload(asset) -> dict:
    return {
        'public_id': asset.public_id,
        'mediaId': asset.public_id,
        'nom_fichier': asset.nom_fichier,
        'reference': asset.reference,
        'nom_produit': asset.nom_produit,
        'categorie': asset.categorie,
        'marque': asset.marque,
        'labels': asset.labels,
        'conservation': asset.conservation,
        'type_fichier': asset.type_fichier,
        'type': asset.type_fichier,
        'status': getattr(asset, 'media_status', ''),
        'couche_actuelle': asset.couche_actuelle,
        'pipeline_complet': asset.pipeline_complet,
        'url_bronze': asset.url_bronze,
        'url_silver': asset.url_silver,
        'url_gold': asset.url_gold,
        'url_production': asset.url_production,
        'title': getattr(asset, 'gold_title', '') or getattr(asset, 'ai_title', ''),
        'description': getattr(asset, 'gold_description', '') or asset.ai_caption,
        'tags': getattr(asset, 'gold_tags', []) or asset.ai_tags,
        'categories': getattr(asset, 'gold_categories', []) or getattr(asset, 'ai_categories', []),
        'detectedObjects': getattr(asset, 'ai_objects', []),
        'detectedPeople': getattr(asset, 'ai_people', []),
        'detectedLogos': getattr(asset, 'ai_logos', []),
        'ocr': getattr(asset, 'ai_ocr', []),
        'context': getattr(asset, 'ai_context', []),
        'embedding': getattr(asset, 'ai_embedding', []),
        'aiConfidence': getattr(asset, 'ai_confidence', {}),
        'validationStatus': 'APPROVED' if asset.tags_validated else 'ADMIN_REVIEW',
        'validatedBy': asset.tags_validated_by,
        'validatedAt': asset.tags_validated_at,
        'ai_caption': asset.ai_caption,
        'ai_tags': asset.ai_tags,
        'ai_title': getattr(asset, 'ai_title', ''),
        'ai_tag_source': asset.ai_tag_source,
        'ai_analyzed_at': asset.ai_analyzed_at,
        'tags_validated': asset.tags_validated,
        'updated_at': timezone.now(),
    }


def _json_ready(value):
    if isinstance(value, dict):
        return {str(k): _json_ready(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_ready(v) for v in value]
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    return value
