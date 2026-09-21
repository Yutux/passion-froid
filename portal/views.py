import base64
import hashlib
import json
import os
import re
import threading
import time
import uuid

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ObjectDoesNotExist
from django.core.exceptions import ValidationError
from django.db import close_old_connections
from django.db.models import Count
from django.shortcuts import redirect, render
from django.http import JsonResponse
from django.core.serializers.json import DjangoJSONEncoder
from django.utils import timezone
from django.views.decorators.http import require_POST

from .auto_sync import get_sync_status, start_background_sync
from .ai_config import get_ai_config
from .models import MediaAsset, Tag, TagCorrection, TagFeedback, AnalysisJob, FirebaseOutbox, WorkerHeartbeat
from .tag_learning import canonical_tags, apply_corrections, tag_key
from .semantic_search import start_index_asset
from .ai_tags import TaggingError, build_metadata_fallback_for_asset, generate_ai_metadata_for_asset
from .firebase_sync import (
    FirebaseSyncSkipped,
    push_firebase_document,
    sync_asset_to_firestore,
    write_firebase_document,
)
from .cloudinary_medallion import (
    configure_cloudinary,
    create_medallion_folders,
    run_medallion_pipeline,
    list_layer_assets,
    compare_layers,
)


def _init_cloudinary():
    """Configure Cloudinary depuis les settings Django."""
    import cloudinary
    cloudinary.config(
        cloud_name=settings.CLOUDINARY_CLOUD_NAME,
        api_key=settings.CLOUDINARY_API_KEY,
        api_secret=settings.CLOUDINARY_API_SECRET,
        secure=True,
    )


def _store_ai_tags(asset, allow_fallback=True):
    started_at = timezone.now()
    result = generate_ai_metadata_for_asset(asset, allow_fallback=allow_fallback)
    config = get_ai_config()
    detected_objects = _merge_tags(result.objects or [], [] if result.details else _detect_objects_for_asset(asset), max_tags=18)
    normalized_tags = _normalize_french_tags(result.tags)
    normalized_tags = _merge_tags(normalized_tags, _normalize_french_tags(detected_objects), max_tags=18)
    normalized_tags = _merge_tags(normalized_tags, result.people or [], result.context or [], max_tags=24)
    if not result.details:
        normalized_tags = _expand_business_tags(asset, result.caption, normalized_tags)
    memory = _memory_profile_for_asset(asset)
    if memory.get('tags') and not result.details:
        normalized_tags = _merge_tags(memory['tags'], normalized_tags, max_tags=24)
    normalized_tags, correction_ids = apply_corrections(asset, normalized_tags)
    asset.ai_title = (result.title.strip() if result.details else memory.get('title')) or _clean_title(result.title) or _build_asset_title(asset, result.caption, normalized_tags)
    current = MediaAsset.objects.get(pk=asset.pk)
    if current.tags_validated or (current.ai_analysis or {}).get('draftUpdatedAt'):
        raise TaggingError('Une correction humaine existe : analyse ignorée pour la préserver.')
    asset.ai_caption = result.caption
    asset.ai_tags = normalized_tags
    asset.ai_objects = detected_objects
    asset.ai_people = _merge_tags(result.people or [], max_tags=8)
    asset.ai_context = _merge_tags(result.context or [], max_tags=12)
    asset.ai_categories = _merge_tags(result.categories or [], [asset.categorie] if asset.categorie and not result.details else [], max_tags=8)
    for field in ('places', 'colors', 'concepts', 'visual_types', 'logos', 'ocr'):
        setattr(asset, 'ai_' + field, getattr(result, field) or [])
    asset.ai_analysis = {
        **(result.details or {}),
        'title': asset.ai_title,
        'description': asset.ai_caption,
        'tags': asset.ai_tags,
        'categories': asset.ai_categories,
        'objects': asset.ai_objects,
        'people': asset.ai_people,
        'logos': asset.ai_logos,
        'ocr': asset.ai_ocr,
        'context': asset.ai_context,
        'confidence': asset.ai_confidence,
        'correction_ids': correction_ids,
    }
    asset.ai_tag_source = result.source
    asset.ai_analyzed_at = timezone.now()
    asset.tags_validated = False
    asset.media_status = 'ADMIN_REVIEW'
    asset.duplicate_key = _duplicate_key_for_asset(asset)
    asset.save(update_fields=[
        'ai_title', 'ai_caption', 'ai_tags', 'ai_categories', 'ai_objects', 'ai_people', 'ai_context',
        'ai_analysis', 'ai_tag_source', 'ai_analyzed_at',
        'ai_places', 'ai_colors', 'ai_concepts', 'ai_visual_types', 'ai_logos', 'ai_ocr',
        'tags_validated', 'media_status', 'duplicate_key', 'modifie_le',
    ])
    _try_sync_firebase(asset)
    try:
        push_firebase_document('ai_runs', {
            'mediaId': asset.public_id,
            'modelName': result.source,
            'modelVersion': config.vision_model,
            'promptVersion': config.prompt_version,
            'inputHash': asset.md5_source or asset.public_id,
            'output': {'title': asset.ai_title, 'caption': asset.ai_caption, 'tags': asset.ai_tags},
            'confidence': asset.ai_confidence,
            'processingTime': max(0, (timezone.now() - started_at).total_seconds()),
        })
    except Exception:
        pass
    result.tags = asset.ai_tags
    return result


def _ensure_minimum_french_tags(asset):
    """Donne immediatement des tags francais avant l'analyse visuelle distante."""
    if asset.type_fichier != 'image':
        return False
    if asset.ai_tags and asset.ai_title:
        return False

    memory = _memory_profile_for_asset(asset)
    if memory.get('tags'):
        tags = _normalize_french_tags(memory['tags'])
        title = memory.get('title') or _build_asset_title(asset, "", tags)
        source = f"memory:{memory.get('source', 'gold')}"
    else:
        fallback = build_metadata_fallback_for_asset(asset)
        tags = _normalize_french_tags(fallback.tags)
        tags = _expand_business_tags(asset, fallback.caption, tags)
        title = _build_asset_title(asset, fallback.caption, tags)
        source = "metadata-fallback:auto"

    if not tags:
        tags = _expand_business_tags(asset, "", ['media a qualifier'])
    if not tags:
        tags = ['media a qualifier']

    asset.ai_title = title or "Asset PassionFroid"
    asset.ai_caption = asset.ai_caption or ""
    asset.ai_tags = tags[:24]
    asset.ai_categories = _merge_tags(asset.ai_categories or [], [asset.categorie] if asset.categorie else [], max_tags=8)
    asset.ai_analysis = {
        'title': asset.ai_title,
        'description': asset.ai_caption,
        'tags': asset.ai_tags,
        'categories': asset.ai_categories,
        'objects': asset.ai_objects,
        'people': asset.ai_people,
        'logos': asset.ai_logos,
        'ocr': asset.ai_ocr,
        'context': asset.ai_context,
        'confidence': asset.ai_confidence,
        'source': source,
    }
    asset.ai_tag_source = source
    asset.ai_analyzed_at = timezone.now()
    if asset.media_status in {'UPLOADED', 'AI_ANALYZING', '', None}:
        asset.media_status = 'ADMIN_REVIEW'
    asset.duplicate_key = _duplicate_key_for_asset(asset)
    asset.save(update_fields=[
        'ai_title', 'ai_caption', 'ai_tags', 'ai_categories', 'ai_analysis',
        'ai_tag_source', 'ai_analyzed_at', 'media_status', 'duplicate_key', 'modifie_le',
    ])
    return True


def _run_ai_analysis_worker(public_ids):
    close_old_connections()
    try:
        queryset = MediaAsset.objects.filter(public_id__in=public_ids, type_fichier='image')
        for asset in queryset:
            try:
                if asset.tags_validated or asset.media_status in {'APPROVED', 'ARCHIVED'}:
                    continue
                if asset.media_status not in {'APPROVED', 'ARCHIVED'}:
                    asset.media_status = 'AI_ANALYZING'
                    asset.save(update_fields=['media_status', 'modifie_le'])
                    _try_sync_firebase(asset)
                _store_ai_tags(asset, allow_fallback=True)
            except Exception:
                MediaAsset.objects.filter(pk=asset.pk).update(media_status='NEEDS_CORRECTION', modifie_le=timezone.now())
    finally:
        close_old_connections()


def _start_ai_analysis_background(assets):
    from .ai_worker import enqueue_asset
    for asset in assets:
        enqueue_asset(asset)


OBJECT_FR_MAP = {
    'person': 'personne',
    'knife': 'couteau',
    'fork': 'fourchette',
    'spoon': 'cuillere',
    'bottle': 'bouteille',
    'cup': 'verre',
    'bowl': 'bol',
    'dining table': 'table',
    'chair': 'chaise',
    'pizza': 'pizza',
    'sandwich': 'sandwich',
    'hot dog': 'snack',
    'cake': 'gateau',
    'broccoli': 'brocoli',
    'carrot': 'carotte',
    'apple': 'fruit',
    'orange': 'fruit',
    'banana': 'fruit',
    'refrigerator': 'refrigerateur',
    'oven': 'four',
    'microwave': 'four micro-ondes',
    'sink': 'evier',
    'truck': 'camion',
    'box': 'carton',
}


def _detect_objects_for_asset(asset):
    token = getattr(settings, "HUGGINGFACE_API_TOKEN", "")
    if not token:
        return []
    image_url = asset.url_gold or asset.url_silver or asset.url_bronze or asset.url_image_source
    if not image_url:
        return []
    try:
        from huggingface_hub import InferenceClient
        client = InferenceClient(provider="hf-inference", api_key=token, timeout=20)
        output = client.object_detection(
            image_url,
            model=getattr(settings, "HUGGINGFACE_OBJECT_DETECTION_MODEL", "facebook/detr-resnet-50"),
        )
    except Exception:
        return []

    labels = []
    for item in output or []:
        label = ""
        score = 1
        if isinstance(item, dict):
            label = item.get("label") or item.get("name") or ""
            score = item.get("score", 1)
        else:
            label = getattr(item, "label", "") or getattr(item, "name", "")
            score = getattr(item, "score", 1)
        try:
            if float(score) < 0.45:
                continue
        except Exception:
            pass
        key = _normalize_key(label)
        labels.append(OBJECT_FR_MAP.get(key, label))
    return _merge_tags(_normalize_french_tags(labels), max_tags=10)


def _build_asset_title(asset, caption="", tags=None):
    tags = tags or []
    candidates = [
        getattr(asset, "nom_produit", "") or "",
        caption or "",
        " ".join(tags[:3]),
        getattr(asset, "nom_fichier", "") or "",
    ]
    for value in candidates:
        cleaned = _clean_title(value)
        if cleaned and not re.fullmatch(r"[a-f0-9]{16,}", cleaned.lower()):
            return cleaned[:255]
    return "Asset PassionFroid"


TAG_FR_MAP = {
    'beef': 'boeuf', 'boeuf': 'boeuf', 'meat': 'viande', 'chef': 'chef cuisinier', 'cook': 'cuisinier',
    'kitchen': 'cuisine professionnelle', 'chicken': 'poulet', 'fish': 'poisson',
    'shrimp': 'crevettes', 'prawn': 'crevettes', 'restaurant': 'restaurant',
    'plate': 'assiette', 'knife': 'couteau', 'board': 'planche', 'bread': 'pain',
    'cheese': 'fromage', 'vegetable': 'legume', 'vegetables': 'legumes',
    'person': 'personne', 'people': 'personnes', 'logo': 'logo',
    'table': 'table', 'professional': 'professionnel', 'product': 'produit',
    'packaging': 'emballage', 'bottle': 'bouteille', 'box': 'carton',
}

def _normalize_french_tags(tags):
    cleaned = []
    seen = set()
    noise = {'there', 'are', 'with', 'some', 'raw', 'surface', 'image', 'photo', 'food'}
    acronyms = {'msc', 'asc', 'bio', 'igp', 'vbf', 'vpf'}
    for tag in tags or []:
        key = _normalize_key(tag)
        if not key or key in noise:
            continue
        raw_value = str(tag).strip()
        value = TAG_FR_MAP.get(key, raw_value)
        if key in acronyms:
            value = key.upper()
        else:
            value = re.sub(r"\s+", " ", value).strip().lower()
        norm = _normalize_key(value)
        if value and norm not in seen:
            seen.add(norm)
            cleaned.append(value)
        if len(cleaned) >= 24:
            break
    return cleaned


BUSINESS_TAG_RULES = [
    (('boeuf', 'steak', 'beef', 'viande rouge', 'entrecote'), ['viande', 'boeuf', 'viande rouge']),
    (('poulet', 'chicken'), ['volaille', 'poulet']),
    (('poisson', 'fish', 'saumon', 'cabillaud'), ['poisson', 'produit de la mer']),
    (('crevette', 'shrimp', 'prawn'), ['crevettes', 'fruits de mer']),
    (('chef', 'cuisinier', 'cook'), ['chef cuisinier', 'professionnel de cuisine']),
    (('cuisine', 'kitchen'), ['cuisine professionnelle']),
    (('restaurant',), ['restaurant']),
    (('emballage', 'packaging', 'box', 'carton'), ['emballage', 'produit conditionne']),
    (('bouteille', 'bottle'), ['bouteille']),
    (('logo',), ['logo']),
    (('packshot',), ['packshot']),
    (('surgel', 'frozen'), ['surgele']),
    (('fromage', 'cheese'), ['fromage', 'produit laitier']),
    (('legume', 'vegetable'), ['legumes']),
]


def _merge_tags(*groups, max_tags=18):
    merged = []
    seen = set()
    for group in groups:
        for tag in group or []:
            value = str(tag or '').strip()
            if not value:
                continue
            key = _normalize_key(value)
            if not key or key in seen:
                continue
            seen.add(key)
            merged.append(value)
            if len(merged) >= max_tags:
                return merged
    return merged


def _expand_business_tags(asset, caption, tags):
    text = " ".join([
        caption or "",
        asset.nom_produit or "",
        asset.nom_fichier or "",
        asset.categorie or "",
        " ".join(tags or []),
    ])
    key = _normalize_key(text)
    extra = []
    for needles, additions in BUSINESS_TAG_RULES:
        if any(re.search(r'\b' + re.escape(needle) + r'\b', key) for needle in needles):
            extra.extend(additions)
    if asset.marque:
        extra.append(asset.marque)
    if asset.categorie:
        extra.append(asset.categorie)
    return _merge_tags(tags, _normalize_french_tags(extra), max_tags=18)


def _memory_profile_for_asset(asset):
    if asset.md5_source:
        exact = (
            MediaAsset.objects
            .filter(md5_source=asset.md5_source, media_status='APPROVED')
            .exclude(pk=asset.pk)
            .order_by('-tags_validated_at')
            .first()
        )
        if exact and exact.gold_tags:
            return {
                'title': exact.gold_title or exact.ai_title,
                'tags': exact.gold_tags,
                'source': 'exact-md5',
            }

    candidates = MediaAsset.objects.filter(media_status='APPROVED').exclude(pk=asset.pk)
    if asset.reference:
        same_ref = candidates.filter(reference=asset.reference).order_by('-tags_validated_at').first()
        if same_ref and same_ref.gold_tags:
            return {'title': same_ref.gold_title or same_ref.ai_title, 'tags': same_ref.gold_tags, 'source': 'reference'}
    if asset.nom_produit:
        product_key = _normalize_key(asset.nom_produit)
        for candidate in candidates.exclude(gold_tags=[]).order_by('-tags_validated_at')[:80]:
            if product_key and product_key == _normalize_key(candidate.nom_produit):
                return {'title': candidate.gold_title or candidate.ai_title, 'tags': candidate.gold_tags, 'source': 'product'}
    return {}


def _clean_title(value):
    base = os.path.splitext(os.path.basename(str(value or "")))[0]
    base = re.sub(r"[_-]+", " ", base)
    base = re.sub(r"\s+", " ", base).strip()
    if not base:
        return ""
    replacements = {
        'piece of beef': 'piece de boeuf',
        'beef': 'boeuf',
        'boeuf': 'boeuf',
        'meat': 'viande',
        'chicken': 'poulet',
        'fish': 'poisson',
        'chef': 'chef cuisinier',
        'kitchen': 'cuisine',
        'plate': 'assiette',
        'bowl': 'bol',
        'knife': 'couteau',
    }
    lowered = base.lower()
    for source, target in replacements.items():
        lowered = lowered.replace(source, target)
    base = lowered
    return base[:1].upper() + base[1:]


def _normalize_key(value):
    value = re.sub(r"[^a-z0-9]+", " ", tag_key(value or ""))
    value = re.sub(r"\b(image|photo|produit|passionfroid|jpg|jpeg|png|webp)\b", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _duplicate_key_for_asset(asset):
    text = " ".join([
        asset.ai_title or "",
        asset.nom_produit or "",
        asset.reference or "",
        " ".join(asset.ai_tags or []),
    ])
    normalized = _normalize_key(text)
    return f"sim:{normalized[:180]}" if normalized else ""


def _sync_gold_metadata_to_cloudinary(asset) -> dict:
    import cloudinary.uploader

    _init_cloudinary()
    resource_type = 'video' if asset.type_fichier == 'video' else 'image'
    cloudinary_tags = ['gold', 'approved', 'admin-validated']
    cloudinary_tags.extend(_normalize_key(tag).replace(' ', '-')[:40] for tag in (asset.gold_tags or [])[:10])
    cloudinary_tags = [tag for tag in cloudinary_tags if tag]
    context = {
        'layer': 'gold',
        'validation_status': 'APPROVED',
        'title': asset.gold_title or asset.ai_title,
        'description': (asset.gold_description or asset.ai_caption or '')[:900],
        'tags': ', '.join(asset.gold_tags or asset.ai_tags or [])[:900],
        'validated_by': asset.tags_validated_by,
        'validated_at': asset.tags_validated_at.isoformat() if asset.tags_validated_at else '',
    }
    if not asset.url_gold:
        from .cloudinary_medallion.gold import promote_to_gold
        promoted = promote_to_gold(asset.public_id, resource_type=resource_type, width=settings.CLOUDINARY_GOLD_WIDTH, quality=settings.CLOUDINARY_GOLD_QUALITY)
        asset.url_gold = promoted['url']
        asset.taille_gold = promoted['bytes']
    result = cloudinary.uploader.explicit(
        f"gold/{asset.public_id}",
        type='upload',
        resource_type=resource_type,
        tags=cloudinary_tags,
        context=context,
        invalidate=True,
    )
    asset.couche_actuelle = 'gold'
    asset.pipeline_complet = True
    return result


def _record_admin_feedback(asset, previous: dict, corrected: dict, user, reason=""):
    feedback_items = []
    for field in ['title', 'description', 'tags', 'categories']:
        if previous.get(field) != corrected.get(field):
            feedback_items.append({
                'mediaId': asset.public_id,
                'model': asset.ai_tag_source or settings.HUGGINGFACE_BLIP_MODEL,
                'field': field,
                'aiValue': previous.get(field),
                'correctedValue': corrected.get(field),
                'adminId': user.get_username(),
                'reason': reason,
            })
    for item in feedback_items:
        try:
            from .firebase_outbox import enqueue_document
            enqueue_document('ai_feedback', uuid.uuid4().hex, item)
        except Exception:
            pass
    return feedback_items


def _try_sync_firebase(asset):
    try:
        sync_asset_to_firestore(asset)
    except FirebaseSyncSkipped:
        return False
    except Exception:
        return False
    return True


def _is_admin_user(user):
    return user.is_authenticated and (user.is_staff or user.is_superuser)


def _firebase_user_profile(uid):
    if not uid:
        return {}
    try:
        import firebase_admin
        from firebase_admin import credentials, firestore
        if not firebase_admin._apps:
            cred = credentials.Certificate(settings.FIREBASE_CREDENTIALS_PATH)
            options = {'projectId': settings.FIREBASE_PROJECT_ID}
            if settings.FIREBASE_DATABASE_URL:
                options['databaseURL'] = settings.FIREBASE_DATABASE_URL
            firebase_admin.initialize_app(cred, options)
        snap = firestore.client().collection('users').document(uid).get()
        if snap.exists:
            return snap.to_dict() or {}
    except Exception:
        pass
    try:
        if not settings.FIREBASE_DATABASE_URL:
            return {}
        from firebase_admin import db
        return db.reference(f"users/{uid}").get() or {}
    except Exception:
        return {}


def _ensure_firebase_admin():
    import firebase_admin
    from firebase_admin import credentials

    if not firebase_admin._apps:
        if not settings.FIREBASE_CREDENTIALS_PATH:
            raise RuntimeError('Firebase non configure.')
        cred = credentials.Certificate(settings.FIREBASE_CREDENTIALS_PATH)
        options = {'projectId': settings.FIREBASE_PROJECT_ID}
        if settings.FIREBASE_DATABASE_URL:
            options['databaseURL'] = settings.FIREBASE_DATABASE_URL
        firebase_admin.initialize_app(cred, options)


def _is_google_cert_network_error(exc):
    text = str(exc)
    return (
        'www.googleapis.com' in text
        or 'securetoken@system.gserviceaccount.com' in text
        or 'WinError 10013' in text
        or 'Failed to establish a new connection' in text
    )


def _decode_firebase_token_without_google(id_token):
    try:
        header, payload, _signature = id_token.split('.', 2)
        padded = payload + '=' * (-len(payload) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(padded.encode('utf-8')).decode('utf-8'))
    except Exception as exc:
        raise ValueError('Token Firebase illisible.') from exc

    project_id = settings.FIREBASE_PROJECT_ID
    if project_id:
        if decoded.get('aud') != project_id:
            raise ValueError('Token Firebase invalide pour ce projet.')
        expected_issuer = f"https://securetoken.google.com/{project_id}"
        if decoded.get('iss') != expected_issuer:
            raise ValueError('Emetteur Firebase invalide.')
    if int(decoded.get('exp') or 0) < int(time.time()):
        raise ValueError('Token Firebase expire.')

    uid = decoded.get('uid') or decoded.get('user_id') or decoded.get('sub')
    if not uid:
        raise ValueError('UID Firebase manquant.')
    decoded['uid'] = uid
    return decoded


def _verify_firebase_token(id_token):
    from firebase_admin import auth as firebase_auth
    _ensure_firebase_admin()
    return firebase_auth.verify_id_token(id_token, check_revoked=True)


# â”€â”€ Pages statiques â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def login_view(request):
    if request.user.is_authenticated:
        return redirect('portal:admin_dashboard' if _is_admin_user(request.user) else 'portal:search')

    context = {**_base_context(request)}
    if request.method == 'POST':
        username = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')
        user = authenticate(request, username=username, password=password)
        if user is None and '@' in username:
            user = authenticate(request, username=username.split('@', 1)[0], password=password)

        if user is None:
            messages.error(request, "Identifiants invalides.")
            return render(request, '01_login.html', context)

        login(request, user)
        return redirect('portal:admin_dashboard' if _is_admin_user(user) else 'portal:search')

    return render(request, '01_login.html', context)


def signup_view(request):
    if request.user.is_authenticated:
        return redirect('portal:search')

    context = _base_context(request)
    if request.method == 'POST':
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        email = request.POST.get('email', '').strip().lower()
        password = request.POST.get('password', '')
        password2 = request.POST.get('password_confirm', '')

        if not first_name or not last_name or not email:
            messages.error(request, "Tous les champs sont obligatoires.")
            return render(request, '00_signup.html', context)
        if password != password2:
            messages.error(request, "Les mots de passe ne correspondent pas.")
            return render(request, '00_signup.html', context)
        try:
            validate_password(password)
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
            return render(request, '00_signup.html', context)

        try:
            import firebase_admin
            from firebase_admin import credentials
            from firebase_admin import auth as firebase_auth
            from .firebase_sync import write_firebase_document

            if not firebase_admin._apps:
                cred = credentials.Certificate(settings.FIREBASE_CREDENTIALS_PATH)
                options = {'projectId': settings.FIREBASE_PROJECT_ID}
                if settings.FIREBASE_DATABASE_URL:
                    options['databaseURL'] = settings.FIREBASE_DATABASE_URL
                firebase_admin.initialize_app(cred, options)

            uid = firebase_auth.create_user(
                email=email,
                password=password,
                display_name=f"{first_name} {last_name}",
                email_verified=False,
                disabled=False,
            ).uid
            write_firebase_document('users', uid, {
                'firstName': first_name,
                'lastName': last_name,
                'email': email,
                'role': 'user',
                'status': 'active',
                'createdAt': timezone.now(),
            })
        except Exception as exc:
            if 'EMAIL_EXISTS' in str(exc) or 'already exists' in str(exc).lower():
                messages.error(request, "Cet email est deja utilise.")
            else:
                messages.error(request, f"Inscription Firebase impossible : {exc}")
            return render(request, '00_signup.html', context)

        User = get_user_model()
        user, created = User.objects.get_or_create(
            username=email,
            defaults={'email': email, 'first_name': first_name, 'last_name': last_name, 'is_active': True},
        )
        updates = []
        if user.email != email:
            user.email = email
            updates.append('email')
        if user.first_name != first_name:
            user.first_name = first_name
            updates.append('first_name')
        if user.last_name != last_name:
            user.last_name = last_name
            updates.append('last_name')
        if not user.is_active:
            user.is_active = True
            updates.append('is_active')
        if created:
            user.set_unusable_password()
            updates.append('password')
        if updates:
            user.save(update_fields=sorted(set(updates)))
        messages.success(request, "Compte cree. Connectez-vous avec votre email et mot de passe.")
        return redirect('portal:login')

    return render(request, '00_signup.html', context)


@require_POST
def logout_view(request):
    logout(request)
    response = render(request, 'logout.html', _base_context(request))
    response['Cache-Control'] = 'no-store'
    return response


@require_POST
def api_firebase_login(request):
    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except json.JSONDecodeError:
        payload = {}

    id_token = payload.get('id_token', '')
    if not id_token:
        return JsonResponse({'error': 'id_token manquant.'}, status=400)

    try:
        decoded = _verify_firebase_token(id_token)
    except Exception as exc:
        return JsonResponse({'error': str(exc)}, status=401)

    uid = decoded.get('uid', '')
    email = decoded.get('email') or f"{uid}@firebase.local"
    User = get_user_model()
    existing_user = User.objects.filter(username=email).first() or User.objects.filter(email=email).first()
    profile = _firebase_user_profile(uid)
    if profile.get('status') == 'disabled':
        return JsonResponse({'error': 'Compte desactive.'}, status=403)

    email = email or profile.get('email') or f"{uid}@firebase.local"
    username = email
    user, created = User.objects.get_or_create(
        username=username,
        defaults={'email': email, 'is_active': True},
    )
    if not user.is_active:
        return JsonResponse({'error': 'Compte désactivé.'}, status=403)
    claims_admin = bool(decoded.get('admin') is True or decoded.get('role') == 'admin' or (existing_user and (existing_user.is_staff or existing_user.is_superuser)))
    if user.email != email or user.is_staff != claims_admin:
        user.email = email
        user.is_staff = claims_admin
        user.save(update_fields=['email', 'is_staff'])

    login(request, user)
    return JsonResponse({
        'success': True,
        'redirect_url': '/admin/' if user.is_staff else '/recherche/',
        'is_admin': user.is_staff,
    })


@require_POST
def api_firebase_signup(request):
    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except json.JSONDecodeError:
        payload = {}

    id_token = payload.get('id_token', '')
    first_name = (payload.get('first_name') or '').strip()
    last_name = (payload.get('last_name') or '').strip()
    if not id_token or not first_name or not last_name:
        return JsonResponse({'error': 'Informations inscription manquantes.'}, status=400)

    try:
        decoded = _verify_firebase_token(id_token)
    except Exception as exc:
        return JsonResponse({'error': str(exc)}, status=401)

    uid = decoded.get('uid', '')
    email = (decoded.get('email') or '').lower()
    if not uid or not email:
        return JsonResponse({'error': 'Compte Firebase invalide.'}, status=400)

    profile = _firebase_user_profile(uid)
    role = 'user'
    status = profile.get('status') if profile.get('status') in {'active', 'disabled'} else 'active'
    user_payload = {
        'firstName': first_name,
        'lastName': last_name,
        'email': email,
        'role': role,
        'status': status,
        'createdAt': profile.get('createdAt') or timezone.now(),
        'updatedAt': timezone.now(),
    }
    if not settings.DEBUG:
        try:
            write_firebase_document('users', uid, user_payload)
        except Exception as exc:
            return JsonResponse({'error': f'Profil Firebase impossible : {exc}'}, status=500)

    User = get_user_model()
    user, created = User.objects.get_or_create(
        username=email,
        defaults={'email': email, 'first_name': first_name, 'last_name': last_name, 'is_active': status == 'active'},
    )
    updates = []
    for field, value in [('email', email), ('first_name', first_name), ('last_name', last_name)]:
        if getattr(user, field) != value:
            setattr(user, field, value)
            updates.append(field)
    is_staff = role == 'admin'
    if user.is_staff != is_staff:
        user.is_staff = is_staff
        updates.append('is_staff')
    if user.is_active != (status == 'active'):
        user.is_active = status == 'active'
        updates.append('is_active')
    if created:
        user.set_unusable_password()
        updates.append('password')
    if updates:
        user.save(update_fields=sorted(set(updates)))

    login(request, user)
    return JsonResponse({
        'success': True,
        'redirect_url': '/admin/' if user.is_staff else '/recherche/',
    })


@login_required
def page(request, template_name):
    return render(request, template_name, _base_context(request))


@login_required
@user_passes_test(_is_admin_user)
def admin_dashboard_view(request, section="dashboard"):
    assets = MediaAsset.objects.all().order_by('-cree_le')
    training_statuses = ['UPLOADED', 'AI_ANALYZING', 'AI_ANALYZED', 'ADMIN_REVIEW', 'NEEDS_CORRECTION']
    pending_count = assets.filter(media_status__in=training_statuses).count()
    archived_count = assets.filter(media_status='ARCHIVED').count()
    tagged_count = sum(1 for asset in assets if asset.ai_tags)
    validated_count = assets.filter(media_status='APPROVED').count()
    category_count = assets.exclude(categorie='').values('categorie').distinct().count()
    user_count = get_user_model().objects.count()
    duplicate_count = (
        assets.exclude(duplicate_key='')
        .values('duplicate_key')
        .annotate(total=Count('id'))
        .filter(total__gt=1)
        .count()
    )
    assets_json = json.dumps(
        list(assets.values(
            'public_id', 'nom_fichier', 'nom_produit', 'categorie', 'marque',
            'reference', 'url_bronze', 'url_silver', 'url_gold', 'url_image_source',
            'type_fichier', 'statut', 'media_status', 'couche_actuelle', 'pipeline_complet',
            'ai_title', 'ai_caption', 'ai_tags', 'ai_categories', 'ai_objects',
            'ai_people', 'ai_logos', 'ai_ocr', 'ai_context', 'ai_confidence',
            'ai_places', 'ai_colors', 'ai_concepts', 'ai_visual_types', 'ai_analysis',
            'gold_title', 'gold_description', 'gold_tags', 'gold_categories',
            'ai_tag_source', 'ai_analyzed_at',
            'analysis_job__status', 'analysis_job__error', 'analysis_job__next_run',
            'tags_validated', 'tags_validated_at', 'tags_validated_by',
            'duplicate_key', 'duplicate_group', 'firebase_synced_at',
            'firebase_sync_error', 'cree_le',
        )),
        cls=DjangoJSONEncoder,
    )
    context = {
        'section': section,
        'correction_count': TagCorrection.objects.filter(active=True).count(),
        'queue_count': AnalysisJob.objects.filter(status__in=['PENDING','RUNNING','RETRY']).count(),
        'feedback_pending': FirebaseOutbox.objects.filter(sent_at__isnull=True).count(),
        'tag_count': Tag.objects.filter(active=True).count(),
        'history': TagCorrection.objects.filter(active=True).select_related('asset')[:12],
        'asset_data': json.loads(assets_json),
        'assets': assets,
        'assets_json': assets_json,
        'total': assets.count(),
        'images': assets.filter(type_fichier='image').count(),
        'videos': assets.filter(type_fichier='video').count(),
        'synced': assets.exclude(firebase_synced_at__isnull=True).count(),
        'pending_count': pending_count,
        'archived_count': archived_count,
        'tagged': tagged_count,
        'validated_count': validated_count,
        'category_count': category_count,
        'user_count': user_count,
        'duplicate_count': duplicate_count,
        'sync_status': get_sync_status(),
        'ai_config': get_ai_config(),
        **_base_context(request),
    }
    return render(request, '04_admin.html', context)


def _base_context(request):
    firebase_web_config = {
        'apiKey': getattr(settings, 'FIREBASE_API_KEY', ''),
        'authDomain': getattr(settings, 'FIREBASE_AUTH_DOMAIN', ''),
        'projectId': getattr(settings, 'FIREBASE_PROJECT_ID', ''),
        'storageBucket': getattr(settings, 'FIREBASE_STORAGE_BUCKET', ''),
        'messagingSenderId': getattr(settings, 'FIREBASE_MESSAGING_SENDER_ID', ''),
        'appId': getattr(settings, 'FIREBASE_APP_ID', ''),
        'measurementId': getattr(settings, 'FIREBASE_MEASUREMENT_ID', ''),
        'databaseURL': getattr(settings, 'FIREBASE_DATABASE_URL', ''),
    }
    return {
        'firebase_configured': bool(getattr(settings, 'FIREBASE_PROJECT_ID', '')),
        'firebase_web_config_json': json.dumps(firebase_web_config),
        'firebase_web_config': firebase_web_config,
        'hf_speech_model': getattr(settings, 'HUGGINGFACE_SPEECH_MODEL', ''),
        'studio_admin': _is_admin_user(request.user),
        'nav_total': MediaAsset.objects.count() if _is_admin_user(request.user) else 0,
        'nav_pending': MediaAsset.objects.filter(tags_validated=False).exclude(media_status='ARCHIVED').count() if _is_admin_user(request.user) else 0,
    }


@login_required
def search_view(request, template_name='02_search.html'):
    """
    Page Recherche â€” affiche tous les assets dont le pipeline est complet,
    avec leurs mÃ©tadonnÃ©es produit et tags IA pour la recherche/filtrage cÃ´tÃ© client.
    """
    assets = MediaAsset.objects.filter(
        pipeline_complet=True,
        tags_validated=True,
        media_status='APPROVED',
    ).exclude(statut='archive').order_by('-cree_le')

    assets_json = json.dumps(
        list(assets.values(
            'public_id', 'nom_fichier', 'nom_produit', 'categorie', 'marque',
            'labels', 'conservation', 'nouveaute', 'url_produit',
            'url_image_source', 'url_bronze', 'url_silver', 'url_gold',
            'format', 'width', 'height', 'taille_gold', 'type_fichier',
            'ai_title', 'ai_caption', 'ai_tags', 'ai_tag_source', 'tags_validated', 'cree_le',
            'reference', 'gold_title', 'gold_description', 'gold_tags',
            'ai_objects', 'ai_people', 'ai_places', 'ai_colors', 'ai_concepts', 'ai_visual_types',
        )),
        cls=DjangoJSONEncoder,
    )

    context = {
        'assets_json': assets_json,
        'asset_data': json.loads(assets_json),
        'section': 'search',
        'total': assets.count(),
        **_base_context(request),
    }
    return render(request, template_name, context)


@require_POST
@login_required
def api_search_feedback(request):
    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except json.JSONDecodeError:
        payload = {}

    query = (payload.get('query') or '').strip()
    if not query:
        return JsonResponse({'error': 'Requete vide.'}, status=400)

    feedback = {
        'query': query,
        'resultCount': int(payload.get('result_count') or 0),
        'matchedCriteria': payload.get('matched_criteria') or [],
        'missingCriteria': payload.get('missing_criteria') or [],
        'status': 'OPEN',
        'source': 'user_search',
        'userId': str(request.user.pk),
        'userEmail': request.user.email or request.user.get_username(),
        'createdAt': timezone.now(),
    }
    try:
        push_firebase_document('search_logs', feedback)
    except Exception:
        pass
    try:
        push_firebase_document('admin_requests', {
            **feedback,
            'type': 'MISSING_MEDIA',
            'message': "Recherche utilisateur sans resultat exact.",
        })
    except Exception:
        pass
    return JsonResponse({'success': True})


def redirect_to(request, target_name):
    return redirect(target_name)


# â”€â”€ Helpers import â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _safe_name(name):
    return "".join(c if c.isalnum() or c in '-_' else '_' for c in name)


def _md5_de_fichier(fichier) -> str:
    """
    Calcule le MD5 du contenu d'un fichier Django (InMemoryUploadedFile / TemporaryUploadedFile)
    sans le vider, pour permettre l'upload Cloudinary juste aprÃ¨s.
    """
    hasher = hashlib.md5()
    for chunk in fichier.chunks():
        hasher.update(chunk)
    fichier.seek(0)  # remet le curseur Ã  0 : le fichier sera relu par run_medallion_pipeline
    return hasher.hexdigest()


def _import_json(fichier):
    """
    Upload le fichier JSON brut vers bronze (raw),
    puis crÃ©e un MediaAsset par produit ayant un url_image.
    Retourne le nombre d'assets crÃ©Ã©s.
    """
    import cloudinary.uploader

    content = fichier.read()

    # 1. Upload le JSON lui-mÃªme en bronze (raw)
    json_public_id = f"json_{_safe_name(os.path.splitext(fichier.name)[0])}_{uuid.uuid4().hex[:6]}"
    cloudinary.uploader.upload(
        content,
        folder="bronze",
        public_id=json_public_id,
        resource_type="raw",
        tags=["bronze", "raw", "json"],
        overwrite=True,
        invalidate=True,
    )

    # 2. Parser le JSON
    data = json.loads(content)
    if isinstance(data, dict):
        data = [data]

    created = 0
    for item in data:
        url_image = item.get('url_image', '').strip()
        public_id = item.get('cloudinary_public_id', '').strip()
        if not public_id:
            public_id = f"product_{uuid.uuid4().hex[:8]}"

        # Ã‰vite les doublons
        if MediaAsset.objects.filter(public_id=public_id).exists():
            continue

        MediaAsset.objects.create(
            public_id=public_id,
            nom_fichier=fichier.name,
            reference=item.get('reference', '').strip(),
            nom_produit=item.get('nom', ''),
            categorie=item.get('categorie', ''),
            marque=item.get('marque', ''),
            labels=item.get('labels', ''),
            conservation=item.get('conservation', ''),
            nouveaute=(item.get('nouveaute', 'Non').strip().lower() == 'oui'),
            url_produit=item.get('url_produit', '').strip(),
            url_image_source=url_image,
            url_bronze=url_image,  # on utilise l'URL source comme bronze pour l'affichage
            fichier_source=fichier.name,
            format=item.get('format', ''),
            type_fichier='image',
            statut='en_cours',
            media_status='UPLOADED',
            couche_actuelle='bronze',
            pipeline_complet=False,
        )
        created += 1

    return created


def _import_csv(fichier):
    """Upload CSV brut vers bronze (raw). Retourne le nom du public_id."""
    import cloudinary.uploader

    content = fichier.read()
    public_id = f"csv_{_safe_name(os.path.splitext(fichier.name)[0])}_{uuid.uuid4().hex[:6]}"
    cloudinary.uploader.upload(
        content,
        folder="bronze",
        public_id=public_id,
        resource_type="raw",
        tags=["bronze", "raw", "csv"],
        overwrite=True,
        invalidate=True,
    )
    return public_id


def _process_uploaded_file(request, fichier):
    ext = os.path.splitext(fichier.name)[1].lower()

    if ext == '.json':
        count = _import_json(fichier)
        return {'created': count, 'skipped': 0, 'message': f"JSON importe: {count} produit(s) ajoute(s) dans bronze."}

    if ext == '.csv':
        pid = _import_csv(fichier)
        return {'created': 1, 'skipped': 0, 'message': f"CSV '{fichier.name}' uploade en bronze (id: {pid})."}

    md5 = _md5_de_fichier(fichier)
    existant = MediaAsset.objects.filter(md5_source=md5).first()
    if existant:
        _start_ai_analysis_background([existant])
        return {
            'created': 0,
            'skipped': 1,
            'message': f"Fichier deja importe: {fichier.name} -> asset {existant.public_id}. Tags existants conserves.",
        }

    base_name = os.path.splitext(fichier.name)[0]
    public_id = f"{_safe_name(base_name)}_{uuid.uuid4().hex[:8]}"
    result = run_medallion_pipeline(
        file=fichier,
        public_id=public_id,
        silver_max_size=settings.CLOUDINARY_SILVER_MAX_SIZE,
        gold_width=settings.CLOUDINARY_GOLD_WIDTH,
        gold_quality=settings.CLOUDINARY_GOLD_QUALITY,
    )

    bronze_info = result['layers']['bronze']
    gold_info = result['layers']['gold']
    video_exts = {'.mp4', '.mov', '.avi', '.mkv', '.webm'}
    type_f = 'video' if ext in video_exts else 'image'

    asset = MediaAsset.objects.create(
        public_id=public_id,
        nom_fichier=fichier.name,
        md5_source=md5,
        ai_title=_clean_title(fichier.name),
        url_bronze=result['urls']['bronze'],
        url_silver=result['urls']['silver'],
        url_gold=result['urls']['gold'],
        url_image_source=result['urls']['gold'] or result['urls']['bronze'],
        format=bronze_info.get('format', ''),
        width=bronze_info.get('width'),
        height=bronze_info.get('height'),
        taille_bronze=bronze_info.get('bytes'),
        taille_gold=gold_info.get('bytes'),
        type_fichier=type_f,
        statut='termine',
        media_status='ADMIN_REVIEW',
        couche_actuelle='silver',
        pipeline_complet=False,
    )
    asset.duplicate_key = _duplicate_key_for_asset(asset)
    asset.save(update_fields=['duplicate_key', 'modifie_le'])
    from .image_memory import fingerprint
    fichier.seek(0)
    asset.perceptual_hash, asset.color_signature = fingerprint(fichier)
    asset.save(update_fields=['perceptual_hash', 'color_signature'])
    _ensure_minimum_french_tags(asset)
    _try_sync_firebase(asset)
    _start_ai_analysis_background([asset])
    return {'created': 1, 'skipped': 0, 'message': f"{fichier.name}: pipeline Medallion termine en {result['duration']}."}


# â”€â”€ Upload & Pipeline Medallion â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@login_required
@user_passes_test(_is_admin_user)
def upload_view(request):
    """
    Page d'import â€” affiche le formulaire et la liste des assets.
    POST : gÃ¨re JSON, CSV, image et vidÃ©o.
    """
    _init_cloudinary()

    if request.method == 'POST':
        fichiers = request.FILES.getlist('fichiers') or request.FILES.getlist('fichier')
        if not fichiers:
            messages.error(request, "Aucun fichier selectionne.")
            return redirect('portal:upload')

        created = 0
        skipped = 0
        errors = []
        try:
            for fichier in fichiers:
                try:
                    result = _process_uploaded_file(request, fichier)
                    created += int(result.get('created') or 0)
                    skipped += int(result.get('skipped') or 0)
                except Exception as exc:
                    errors.append(f"{fichier.name}: {exc}")
            if created:
                messages.success(request, f"{created} fichier(s) importe(s). Analyse IA automatique lancee.")
            if skipped:
                messages.info(request, f"{skipped} doublon(s) ignore(s), tags existants conserves.")
            if errors:
                messages.error(request, "Erreurs import: " + " | ".join(errors[:5]))
        except Exception as e:
            messages.error(request, f"Erreur import : {e}")

        return redirect('portal:upload')

    # GET â€” rÃ©cupÃ©rer les assets
    assets = MediaAsset.objects.all().order_by('-cree_le')

    assets_json = json.dumps(
        list(assets.values(
            'public_id', 'nom_fichier', 'nom_produit', 'categorie',
            'url_image_source', 'url_bronze', 'url_silver', 'url_gold',
            'format', 'width', 'height', 'taille_bronze', 'taille_gold',
            'type_fichier', 'statut', 'couche_actuelle', 'pipeline_complet',
            'fichier_source', 'cree_le', 'ai_title', 'ai_caption', 'ai_tags',
            'ai_tag_source', 'ai_analyzed_at', 'tags_validated',
        )),
        cls=DjangoJSONEncoder,
    )

    context = {
        'assets': assets,
        'recent_assets': assets[:6],
        'section': 'upload',
        'assets_json': assets_json,
        'total': assets.count(),
        'complets': assets.filter(pipeline_complet=True).count(),
        'en_cours': assets.filter(statut='en_cours').count(),
        'en_attente': assets.filter(statut='en_attente').count(),
        'termine': assets.filter(statut='termine').count(),
        'has_huggingface_token': bool(settings.HUGGINGFACE_API_TOKEN),
        **_base_context(request),
    }
    return render(request, '03_upload.html', context)


# â”€â”€ API JSON â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@login_required
@user_passes_test(_is_admin_user)
def api_setup_folders(request):
    _init_cloudinary()
    results = create_medallion_folders()
    return JsonResponse({'success': True, 'folders': results})


@login_required
@user_passes_test(_is_admin_user)
@require_POST
def api_run_passionfroid_sync(request):
    started = start_background_sync(reason="admin")
    status = get_sync_status()
    return JsonResponse({
        'success': True,
        'started': started,
        'status': status,
        'message': "Synchronisation lancee." if started else "Synchronisation deja en cours.",
    })


@login_required
@user_passes_test(_is_admin_user)
def api_passionfroid_sync_status(request):
    return JsonResponse({'success': True, 'status': get_sync_status()})


@login_required
@user_passes_test(_is_admin_user)
def api_list_assets(request):
    _init_cloudinary()
    layer = request.GET.get('layer', 'gold')
    if layer not in ('bronze', 'silver', 'gold'):
        return JsonResponse({'error': 'layer invalide'}, status=400)
    try:
        assets = list_layer_assets(layer)
        return JsonResponse({'layer': layer, 'count': len(assets), 'assets': assets})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@user_passes_test(_is_admin_user)
def api_compare_asset(request, public_id):
    _init_cloudinary()
    try:
        data = compare_layers(public_id)
        return JsonResponse(data)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
def api_assets_db(request):
    from .semantic_search import published_assets
    queryset = MediaAsset.objects.all() if _is_admin_user(request.user) else published_assets()
    assets = list(queryset.values(
        'public_id', 'nom_fichier', 'nom_produit', 'categorie',
        'url_image_source', 'url_bronze', 'url_silver', 'url_gold',
        'format', 'width', 'height', 'taille_bronze', 'taille_gold',
        'type_fichier', 'statut', 'couche_actuelle', 'pipeline_complet',
        'cree_le', 'ai_title', 'ai_caption', 'ai_tags', 'ai_tag_source',
        'ai_analyzed_at', 'tags_validated', 'tags_validated_at', 'tags_validated_by',
    ))
    return JsonResponse({'count': len(assets), 'assets': assets}, json_dumps_params={'default': str})


@login_required
def api_asset_detail(request, public_id):
    from .semantic_search import published_assets
    queryset = MediaAsset.objects.all() if _is_admin_user(request.user) else published_assets()
    try:
        asset = queryset.values(
            'public_id', 'nom_fichier', 'nom_produit', 'categorie',
            'url_image_source', 'url_bronze', 'url_silver', 'url_gold',
            'format', 'width', 'height', 'taille_bronze', 'taille_gold',
            'type_fichier', 'statut', 'couche_actuelle', 'pipeline_complet',
            'fichier_source', 'cree_le', 'ai_title', 'ai_caption', 'ai_tags',
            'ai_tag_source', 'ai_analyzed_at', 'tags_validated',
            'tags_validated_at', 'tags_validated_by',
        ).get(public_id=public_id)
    except ObjectDoesNotExist:
        return JsonResponse({'error': 'asset introuvable'}, status=404)

    if not _is_admin_user(request.user):
        asset.pop('fichier_source', None)
    return JsonResponse(asset, json_dumps_params={'default': str})


@require_POST
@login_required
@user_passes_test(_is_admin_user)
def api_save_asset_draft(request):
    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except json.JSONDecodeError:
        payload = {}

    public_id = payload.get('public_id') or ''
    if not public_id:
        return JsonResponse({'error': 'public_id manquant'}, status=400)
    try:
        asset = MediaAsset.objects.get(public_id=public_id)
    except MediaAsset.DoesNotExist:
        return JsonResponse({'error': 'asset introuvable'}, status=404)

    title = str(payload.get('title') or asset.ai_title or asset.nom_produit or asset.nom_fichier).strip()[:255]
    tags = payload.get('tags', asset.ai_tags)
    if isinstance(tags, str):
        tags = [t.strip() for t in re.split(r"[,;|]", tags) if t.strip()]
    if not isinstance(tags, list):
        return JsonResponse({'error': 'tags doit etre une liste.'}, status=400)

    previous = {
        'title': asset.ai_title,
        'tags': asset.ai_tags,
        'categories': asset.ai_categories,
    }
    draft_original_tags = asset.gold_tags if asset.tags_validated else (asset.ai_analysis or {}).get('original_tags', asset.ai_tags)
    asset.ai_caption = str(payload.get('description', asset.ai_caption)).strip()[:2500]
    asset.ai_title = title or "Asset PassionFroid"
    asset.ai_tags = _normalize_french_tags([str(t).strip() for t in tags if str(t).strip()])[:24]
    asset.ai_tag_source = asset.ai_tag_source or 'admin-draft'
    asset.tags_validated = False
    if asset.media_status in {'UPLOADED', 'AI_ANALYZING', 'AI_ANALYZED', 'NEEDS_CORRECTION', 'APPROVED'}:
        asset.media_status = 'ADMIN_REVIEW'
    asset.ai_analysis = {
        **(asset.ai_analysis or {}),
        'original_tags': draft_original_tags,
        'title': asset.ai_title,
        'tags': asset.ai_tags,
        'draftUpdatedBy': request.user.get_username(),
        'draftUpdatedAt': timezone.now().isoformat(),
    }
    asset.duplicate_key = _duplicate_key_for_asset(asset)
    asset.save(update_fields=[
        'ai_title', 'ai_caption', 'ai_tags', 'ai_tag_source', 'tags_validated',
        'media_status', 'ai_analysis', 'duplicate_key', 'modifie_le',
    ])
    _record_admin_feedback(asset, previous, {'title': asset.ai_title, 'tags': asset.ai_tags, 'categories': asset.ai_categories}, request.user, 'draft')
    return JsonResponse({
        'success': True,
        'asset': {
            'public_id': asset.public_id,
            'ai_title': asset.ai_title,
            'ai_tags': asset.ai_tags,
            'media_status': asset.media_status,
        },
    })


@require_POST
@login_required
@user_passes_test(_is_admin_user)
def api_validate_asset_tags(request, public_id):
    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except json.JSONDecodeError:
        payload = {}

    try:
        asset = MediaAsset.objects.get(public_id=public_id)
    except MediaAsset.DoesNotExist:
        return JsonResponse({'error': 'asset introuvable'}, status=404)

    previous = {
        'title': asset.ai_title,
        'description': asset.ai_caption,
        'tags': (asset.ai_analysis or {}).get('original_tags', asset.ai_tags),
        'categories': asset.ai_categories,
    }
    title = str(payload.get('title') or asset.ai_title or asset.nom_produit or asset.nom_fichier).strip()[:255]
    description = (payload.get('description') or asset.ai_caption or '').strip()
    tags = payload.get('tags', asset.ai_tags)
    categories = payload.get('categories', asset.ai_categories or ([asset.categorie] if asset.categorie else []))
    if isinstance(tags, str):
        tags = [t.strip() for t in re.split(r"[,;|]", tags) if t.strip()]
    if isinstance(categories, str):
        categories = [t.strip() for t in re.split(r"[,;|]", categories) if t.strip()]
    if not isinstance(tags, list):
        return JsonResponse({'error': 'tags doit etre une liste ou une chaine separee par virgules.'}, status=400)

    asset.ai_title = title or "Asset PassionFroid"
    asset.ai_tags = _normalize_french_tags([str(t).strip() for t in tags if str(t).strip()])[:24]
    asset.ai_tags = canonical_tags(asset.ai_tags)
    if not asset.ai_tags:
        return JsonResponse({'error': 'Ajoutez au moins un tag actif.'}, status=400)
    asset.gold_title = asset.ai_title
    asset.gold_description = description
    asset.gold_tags = asset.ai_tags
    asset.gold_categories = [str(c).strip() for c in categories if str(c).strip()][:8] if isinstance(categories, list) else []
    asset.validation_notes = (payload.get('notes') or '').strip()
    asset.tags_validated = True
    asset.tags_validated_at = timezone.now()
    asset.tags_validated_by = request.user.get_username()
    asset.media_status = 'APPROVED'
    asset.statut = 'termine'
    corrected = {
        'title': asset.gold_title,
        'description': asset.gold_description,
        'tags': asset.gold_tags,
        'categories': asset.gold_categories,
    }
    feedback = _record_admin_feedback(asset, previous, corrected, request.user, asset.validation_notes)
    asset.gold_feedback = feedback
    asset.duplicate_key = _duplicate_key_for_asset(asset)
    cloudinary_error = ''
    firebase_error = ''
    try:
        _sync_gold_metadata_to_cloudinary(asset)
    except Exception as exc:
        cloudinary_error = str(exc)
    asset.save(update_fields=[
        'ai_title', 'ai_tags', 'gold_title', 'gold_description', 'gold_tags',
        'gold_categories', 'gold_feedback', 'validation_notes', 'tags_validated',
        'tags_validated_at', 'tags_validated_by', 'media_status', 'statut',
        'duplicate_key', 'url_gold', 'taille_gold', 'couche_actuelle', 'pipeline_complet', 'modifie_le',
    ])
    correction = TagCorrection.objects.create(asset=asset, before=previous['tags'], after=asset.gold_tags, reference=asset.reference, author=request.user.get_username())
    from .firebase_outbox import enqueue_document
    enqueue_document('training_validations', str(correction.pk), {
        'mediaId':asset.public_id, 'before':correction.before, 'after':correction.after,
        'added': [t for t in correction.after if tag_key(t) not in {tag_key(v) for v in correction.before}],
        'removed': [t for t in correction.before if tag_key(t) not in {tag_key(v) for v in correction.after}],
        'reason':asset.validation_notes, 'author':correction.author, 'active':True,
        'reference':asset.reference, 'imageHash':asset.perceptual_hash, 'createdAt':correction.created_at,
    })
    start_index_asset(asset.pk)
    for value in asset.gold_tags:
        Tag.objects.get_or_create(key=tag_key(value), defaults={'name': value})
    try:
        _try_sync_firebase(asset)
        write_firebase_document('admin_validations', asset.public_id, {
            'mediaId': asset.public_id,
            'validatedBy': request.user.get_username(),
            'validatedAt': asset.tags_validated_at,
            'title': asset.gold_title,
            'tags': asset.gold_tags,
            'categories': asset.gold_categories,
            'notes': asset.validation_notes,
            'cloudinaryGoldPublicId': f"gold/{asset.public_id}",
        })
        write_firebase_document('media_analysis', asset.public_id, {
            'mediaId': asset.public_id,
            'bronze': asset.ai_analysis,
            'silver': {
                'title': asset.ai_title,
                'description': asset.ai_caption,
                'tags': asset.ai_tags,
                'objects': asset.ai_objects,
                'people': asset.ai_people,
                'logos': asset.ai_logos,
                'ocr': asset.ai_ocr,
                'confidence': asset.ai_confidence,
            },
            'gold': corrected,
        })
    except Exception as exc:
        firebase_error = str(exc)
    return JsonResponse({
        'success': not cloudinary_error and not firebase_error,
        'cloudinary_synced': not bool(cloudinary_error),
        'firebase_synced': not bool(firebase_error),
        'cloudinary_error': cloudinary_error,
        'firebase_error': firebase_error,
        'asset': {
            'public_id': asset.public_id,
            'ai_title': asset.ai_title,
            'gold_title': asset.gold_title,
            'ai_tags': asset.ai_tags,
            'gold_tags': asset.gold_tags,
            'media_status': asset.media_status,
            'tags_validated': asset.tags_validated,
            'tags_validated_by': asset.tags_validated_by,
        }
    })


@login_required
@user_passes_test(_is_admin_user)
def api_duplicate_assets(request):
    groups = []
    duplicates = (
        MediaAsset.objects.exclude(duplicate_key='')
        .values('duplicate_key')
        .annotate(total=Count('id'))
        .filter(total__gt=1)
        .order_by('-total')
    )
    for group in duplicates[:50]:
        assets = list(
            MediaAsset.objects.filter(duplicate_key=group['duplicate_key'])
            .order_by('-tags_validated', '-cree_le')
            .values('public_id', 'ai_title', 'nom_fichier', 'url_gold', 'url_silver', 'url_bronze', 'tags_validated')
        )
        groups.append({'key': group['duplicate_key'], 'total': group['total'], 'assets': assets})
    return JsonResponse({'count': len(groups), 'groups': groups}, json_dumps_params={'default': str})


@require_POST
@login_required
@user_passes_test(_is_admin_user)
def api_delete_duplicates(request):
    deleted = 0
    groups = (
        MediaAsset.objects.exclude(duplicate_key='')
        .values('duplicate_key')
        .annotate(total=Count('id'))
        .filter(total__gt=1)
    )
    for group in groups:
        assets = list(MediaAsset.objects.filter(duplicate_key=group['duplicate_key']).order_by('-tags_validated', '-cree_le'))
        for asset in assets[1:]:
            _delete_asset_cloudinary_layers(asset)
            asset.delete()
            deleted += 1
    return JsonResponse({'success': True, 'deleted': deleted})


def _delete_asset_cloudinary_layers(asset):
    try:
        import cloudinary.uploader
        _init_cloudinary()
        resource_type = 'video' if asset.type_fichier == 'video' else 'image'
        for layer in ['bronze', 'silver', 'gold']:
            cloudinary.uploader.destroy(f"{layer}/{asset.public_id}", resource_type=resource_type, invalidate=True)
    except Exception:
        return False
    return True


@require_POST
@login_required
@user_passes_test(_is_admin_user)
def api_generate_tags(request):
    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except json.JSONDecodeError:
        payload = {}

    if not isinstance(payload, dict):
        return JsonResponse({'error': 'Objet JSON requis.'}, status=400)
    mode = payload.get('mode', 'missing')
    public_ids = payload.get('public_ids') or []
    force_visual = bool(payload.get('force_visual'))

    if not isinstance(public_ids, list) or any(not isinstance(value, str) for value in public_ids):
        return JsonResponse({'error': 'public_ids doit être une liste.'}, status=400)
    if mode not in {'missing', 'fallback', 'all'}:
        return JsonResponse({'error': 'Mode invalide.'}, status=400)
    queryset = MediaAsset.objects.filter(type_fichier='image').order_by('-cree_le')
    if public_ids:
        queryset = queryset.filter(public_id__in=public_ids)

    if payload.get('async'):
        from .ai_worker import enqueue_asset
        queued = []
        for asset in queryset:
            if (asset.ai_analysis or {}).get('draftUpdatedAt'):
                continue
            if enqueue_asset(asset, force=True):
                queued.append({'public_id':asset.public_id, 'status':'queued'})
        return JsonResponse({'success':True,'queued':len(queued),'results':queued})

    results = []
    updated = 0
    skipped = 0
    errors = 0

    for asset in queryset:
        if asset.tags_validated or asset.media_status == 'ARCHIVED':
            skipped += 1
            continue
        if mode == 'missing' and asset.ai_tags and not asset.ai_tag_source.startswith('metadata-fallback'):
            skipped += 1
            results.append({
                'public_id': asset.public_id,
                'status': 'skipped',
                'reason': 'already_tagged',
                'tags': asset.ai_tags,
                'caption': asset.ai_caption,
            })
            continue
        if mode == 'fallback' and not asset.ai_tag_source.startswith('metadata-fallback'):
            skipped += 1
            results.append({
                'public_id': asset.public_id,
                'status': 'skipped',
                'reason': 'already_visual',
                'tags': asset.ai_tags,
                'caption': asset.ai_caption,
            })
            continue

        try:
            tagging = _store_ai_tags(asset, allow_fallback=not force_visual)
            updated += 1
            results.append({
                'public_id': asset.public_id,
                'status': 'updated',
                'tags': asset.ai_tags,
                'title': asset.ai_title,
                'analysis': asset.ai_analysis,
                'caption': tagging.caption,
                'source': tagging.source,
                'analyzed_at': asset.ai_analyzed_at.isoformat() if asset.ai_analyzed_at else None,
            })
        except TaggingError as exc:
            errors += 1
            results.append({
                'public_id': asset.public_id,
                'status': 'error',
                'error': str(exc),
            })
        except Exception:
            errors += 1
            results.append({
                'public_id': asset.public_id,
                'status': 'error',
                'error': "Erreur inattendue pendant l'analyse IA.",
            })

    return JsonResponse({
        'success': errors == 0,
        'count': queryset.count(),
        'updated': updated,
        'skipped': skipped,
        'errors': errors,
        'results': results,
    })


@login_required
@require_POST
def api_speech_to_text(request):
    audio_file = request.FILES.get('audio')
    if not audio_file:
        return JsonResponse({'error': 'Aucun fichier audio recu.'}, status=400)

    token = getattr(settings, "HUGGINGFACE_API_TOKEN", "")
    if not token:
        return JsonResponse({'error': 'HUGGINGFACE_API_TOKEN manquant.'}, status=400)

    try:
        from huggingface_hub import InferenceClient

        client = InferenceClient(
            provider="hf-inference",
            api_key=token,
            timeout=int(getattr(settings, "HUGGINGFACE_API_TIMEOUT", 45)),
        )
        output = client.automatic_speech_recognition(
            audio_file.read(),
            model=getattr(settings, "HUGGINGFACE_SPEECH_MODEL", "openai/whisper-large-v3"),
        )
    except Exception as exc:
        return JsonResponse({'error': str(exc)}, status=500)

    if isinstance(output, str):
        text = output
    elif isinstance(output, dict):
        text = output.get('text') or output.get('generated_text') or ''
    elif hasattr(output, 'text'):
        text = output.text
    else:
        text = str(output)

    text = re.sub(r'\s*[.!?â€¦]+$', '', (text or '').strip())
    return JsonResponse({'text': text})






@login_required
@user_passes_test(_is_admin_user)
def api_tags(request, tag_id=None):
    if request.method == 'GET':
        return JsonResponse({'tags': list(Tag.objects.values('id', 'name', 'category', 'active'))})
    if request.method not in {'POST', 'PATCH', 'DELETE'}:
        return JsonResponse({'error': 'Méthode non autorisée.'}, status=405)
    try:
        payload = json.loads(request.body or '{}')
        if not isinstance(payload, dict):
            raise ValueError()
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({'error': 'JSON invalide.'}, status=400)
    from django.db import transaction, IntegrityError
    try:
        with transaction.atomic():
            tag = Tag.objects.select_for_update().get(pk=tag_id) if tag_id else None
            if request.method == 'DELETE':
                if not tag:
                    return JsonResponse({'error': 'Tag requis.'}, status=400)
                # Retain a tombstone to prevent deleted tags from returning in predictions.
                tag.active = False
                tag.save(update_fields=['active'])
                return JsonResponse({'success': True})
            name = payload.get('name', '')
            category = payload.get('category', '')
            if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80 or not isinstance(category, str) or len(category) > 80:
                return JsonResponse({'error': 'Nom requis (80 caractères maximum).'}, status=400)
            old_name = tag.name if tag else None
            if tag is None:
                tag = Tag()
            tag.name, tag.key, tag.category = name.strip(), tag_key(name), category.strip()
            tag.active = True
            tag.save()
            if old_name and old_name != tag.name:
                for asset in MediaAsset.objects.all().iterator():
                    changed = []
                    for field in ('ai_tags', 'gold_tags'):
                        values = getattr(asset, field)
                        new = [tag.name if tag_key(t) == tag_key(old_name) else t for t in values]
                        if new != values:
                            setattr(asset, field, list(dict.fromkeys(new)))
                            changed.append(field)
                    if changed:
                        asset.save(update_fields=changed)
                for correction in TagCorrection.objects.all().iterator():
                    correction.before = [tag.name if tag_key(t) == tag_key(old_name) else t for t in correction.before]
                    correction.after = [tag.name if tag_key(t) == tag_key(old_name) else t for t in correction.after]
                    correction.save(update_fields=['before', 'after'])
            return JsonResponse({'success': True, 'id': tag.pk})
    except Tag.DoesNotExist:
        return JsonResponse({'error': 'Tag introuvable.'}, status=404)
    except IntegrityError:
        return JsonResponse({'error': 'Ce tag existe déjà.'}, status=409)


@login_required
def api_semantic_search(request):
    if request.method != 'GET':
        return JsonResponse({'error': 'GET requis.'}, status=405)
    from .semantic_search import search
    query = request.GET.get('q', '').strip()
    if len(query) > 300:
        return JsonResponse({'error': 'Recherche trop longue (300 caractères maximum).'}, status=400)
    return JsonResponse(search(query, category=request.GET.get('category', '')[:255],
        color=request.GET.get('color', '')[:80], visual_type=request.GET.get('visual_type', '')[:80],
        media_type=request.GET.get('type', '')[:10], semantic=request.GET.get('semantic', '1') != '0'))


@require_POST
@login_required
@user_passes_test(_is_admin_user)
def api_tag_feedback(request, public_id):
    from django.db import transaction
    from .firebase_outbox import enqueue_document
    try:
        payload = json.loads(request.body or '{}')
        action = payload.get('action')
        tag = payload.get('tag')
        reason = payload.get('reason')
        if action not in {'add','remove','replace'} or not isinstance(tag,str) or not 1<=len(tag.strip())<=80 or not isinstance(reason,str) or not 3<=len(reason.strip())<=500:
            return JsonResponse({'error':'Un tag et une raison de 3 à 500 caractères sont requis.'}, status=400)
    except (ValueError, AttributeError):
        return JsonResponse({'error':'Données invalides.'}, status=400)
    try:
        with transaction.atomic():
            asset = MediaAsset.objects.select_for_update().get(public_id=public_id)
            if asset.tags_validated or asset.media_status == 'ARCHIVED':
                return JsonResponse({'error':'Rouvrez le média avant de le corriger.'}, status=409)
            original = list(asset.ai_tags)
            value = tag.strip()
            replacement = payload.get('replacement', '')
            if action == 'replace' and (not isinstance(replacement,str) or not 1<=len(replacement.strip())<=80):
                return JsonResponse({'error':'Nouveau tag invalide.'}, status=400)
            if action == 'replace':
                values = canonical_tags([t for t in original if tag_key(t)!=tag_key(value)]+[replacement.strip()])
                if tag_key(replacement.strip()) not in {tag_key(t) for t in values}:
                    return JsonResponse({'error':'Ce tag est désactivé.'}, status=400)
            elif action == 'remove':
                values = [t for t in original if tag_key(t)!=tag_key(value)]
            else:
                values = canonical_tags(original+[value])
                if tag_key(value) not in {tag_key(t) for t in values}:
                    return JsonResponse({'error':'Tag désactivé ou limite de tags atteinte.'}, status=400)
            if values == original:
                return JsonResponse({'success':True, 'tags':values, 'unchanged':True})
            asset.ai_tags = values
            asset.ai_analysis = {**(asset.ai_analysis or {}), 'original_tags':(asset.ai_analysis or {}).get('original_tags',original), 'tags':values, 'draftUpdatedAt':timezone.now().isoformat(), 'draftUpdatedBy':request.user.get_username()}
            asset.media_status = 'ADMIN_REVIEW'
            asset.save(update_fields=['ai_tags','ai_analysis','media_status','modifie_le'])
            changes = [('remove',value),('add',replacement.strip())] if action=='replace' else [(action,value)]
            for change, changed_tag in changes:
                event = TagFeedback.objects.create(asset=asset, action=change, tag=changed_tag, reason=reason.strip(), author=request.user.get_username())
                enqueue_document('tag_feedback', str(event.pk), {
                    'mediaId':asset.public_id, 'action':change, 'tag':changed_tag, 'reason':event.reason,
                    'author':event.author, 'active':True, 'reference':asset.reference,
                    'imageHash':asset.perceptual_hash, 'colorSignature':asset.color_signature,
                    'before':original, 'after':values, 'createdAt':event.created_at,
                })
    except MediaAsset.DoesNotExist:
        return JsonResponse({'error':'Média introuvable.'}, status=404)
    return JsonResponse({'success':True, 'tags':values, 'feedback_id':event.pk, 'firebase':'pending'})


@login_required
@user_passes_test(_is_admin_user)
def api_learning_status(request):
    assets = list(MediaAsset.objects.filter(type_fichier='image').values(
        'public_id','ai_title','ai_caption','ai_tags','ai_tag_source','ai_analyzed_at','media_status',
        'ai_analysis','tags_validated','gold_tags','gold_title','gold_description',
        'analysis_job__status','analysis_job__error','analysis_job__next_run'))
    from datetime import timedelta
    worker_alive = WorkerHeartbeat.objects.filter(name='analysis',last_seen__gte=timezone.now()-timedelta(minutes=8)).exists()
    return JsonResponse({'worker_alive':worker_alive, 'assets':assets, 'queued':AnalysisJob.objects.filter(status__in=['PENDING','RUNNING','RETRY']).count(),
        'running':AnalysisJob.objects.filter(status='RUNNING').count(),
        'firebase_pending':FirebaseOutbox.objects.filter(sent_at__isnull=True).count()})
