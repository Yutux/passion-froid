import hashlib
import json
import os
import uuid

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import ObjectDoesNotExist
from django.shortcuts import redirect, render
from django.http import JsonResponse
from django.core.serializers.json import DjangoJSONEncoder
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import MediaAsset
from .ai_tags import TaggingError, generate_ai_metadata_for_asset
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
    result = generate_ai_metadata_for_asset(asset, allow_fallback=allow_fallback)
    asset.ai_caption = result.caption
    asset.ai_tags = result.tags
    asset.ai_tag_source = result.source
    asset.ai_analyzed_at = timezone.now()
    asset.save(update_fields=['ai_caption', 'ai_tags', 'ai_tag_source', 'ai_analyzed_at', 'modifie_le'])
    return result


# ── Pages statiques ────────────────────────────────────────────

def page(request, template_name):
    return render(request, template_name)


def search_view(request, template_name='02_search.html'):
    """
    Page Recherche — affiche tous les assets dont le pipeline est complet,
    avec leurs métadonnées produit et tags IA pour la recherche/filtrage côté client.
    """
    assets = MediaAsset.objects.filter(pipeline_complet=True).order_by('-cree_le')

    assets_json = json.dumps(
        list(assets.values(
            'public_id', 'nom_fichier', 'nom_produit', 'categorie', 'marque',
            'labels', 'conservation', 'nouveaute', 'url_produit',
            'url_image_source', 'url_bronze', 'url_silver', 'url_gold',
            'format', 'width', 'height', 'taille_gold', 'type_fichier',
            'ai_caption', 'ai_tags', 'ai_tag_source', 'cree_le',
        )),
        cls=DjangoJSONEncoder,
    )

    context = {
        'assets_json': assets_json,
        'total': assets.count(),
    }
    return render(request, template_name, context)


def redirect_to(request, target_name):
    return redirect(target_name)


# ── Helpers import ─────────────────────────────────────────────

def _safe_name(name):
    return "".join(c if c.isalnum() or c in '-_' else '_' for c in name)


def _md5_de_fichier(fichier) -> str:
    """
    Calcule le MD5 du contenu d'un fichier Django (InMemoryUploadedFile / TemporaryUploadedFile)
    sans le vider, pour permettre l'upload Cloudinary juste après.
    """
    hasher = hashlib.md5()
    for chunk in fichier.chunks():
        hasher.update(chunk)
    fichier.seek(0)  # remet le curseur à 0 : le fichier sera relu par run_medallion_pipeline
    return hasher.hexdigest()


def _import_json(fichier):
    """
    Upload le fichier JSON brut vers bronze (raw),
    puis crée un MediaAsset par produit ayant un url_image.
    Retourne le nombre d'assets créés.
    """
    import cloudinary.uploader

    content = fichier.read()

    # 1. Upload le JSON lui-même en bronze (raw)
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

        # Évite les doublons
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


# ── Upload & Pipeline Medallion ────────────────────────────────

def upload_view(request):
    """
    Page d'import — affiche le formulaire et la liste des assets.
    POST : gère JSON, CSV, image et vidéo.
    """
    _init_cloudinary()

    if request.method == 'POST':
        fichier = request.FILES.get('fichier')
        if not fichier:
            messages.error(request, "Aucun fichier sélectionné.")
            return redirect('portal:upload')

        ext = os.path.splitext(fichier.name)[1].lower()

        try:
            if ext == '.json':
                count = _import_json(fichier)
                messages.success(request, f"✅ JSON importé — {count} produit(s) ajouté(s) dans bronze.")

            elif ext == '.csv':
                pid = _import_csv(fichier)
                messages.success(request, f"✅ CSV '{fichier.name}' uploadé en bronze (id: {pid}).")

            else:
                # ── Dédoublonnage par MD5 avant tout upload ──
                md5 = _md5_de_fichier(fichier)
                existant = MediaAsset.objects.filter(md5_source=md5).first()

                if existant:
                    messages.info(
                        request,
                        f"⏭️ Fichier déjà importé (asset {existant.public_id}) — aucun nouvel upload."
                    )
                    return redirect('portal:upload')
                # ──────────────────────────────────────────────

                # Image / Vidéo → pipeline Medallion complet
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
                gold_info   = result['layers']['gold']

                # Détecter si c'est une vidéo
                video_exts = {'.mp4', '.mov', '.avi', '.mkv', '.webm'}
                type_f = 'video' if ext in video_exts else 'image'

                asset = MediaAsset.objects.create(
                    public_id=public_id,
                    nom_fichier=fichier.name,
                    md5_source=md5,
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
                    couche_actuelle='gold',
                    pipeline_complet=True,
                )

                if type_f == 'image':
                    try:
                        _store_ai_tags(asset)
                    except TaggingError:
                        pass

                messages.success(
                    request,
                    f"✅ Pipeline Medallion terminé en {result['duration']} — Gain : {result['savings']}"
                )

        except Exception as e:
            messages.error(request, f"❌ Erreur import : {e}")

        return redirect('portal:upload')

    # GET — récupérer les assets
    assets = MediaAsset.objects.all().order_by('-cree_le')

    assets_json = json.dumps(
        list(assets.values(
            'public_id', 'nom_fichier', 'nom_produit', 'categorie',
            'url_image_source', 'url_bronze', 'url_silver', 'url_gold',
            'format', 'width', 'height', 'taille_bronze', 'taille_gold',
            'type_fichier', 'statut', 'couche_actuelle', 'pipeline_complet',
            'fichier_source', 'cree_le', 'ai_caption', 'ai_tags',
            'ai_tag_source', 'ai_analyzed_at',
        )),
        cls=DjangoJSONEncoder,
    )

    context = {
        'assets': assets,
        'assets_json': assets_json,
        'total': assets.count(),
        'complets': assets.filter(pipeline_complet=True).count(),
        'en_cours': assets.filter(statut='en_cours').count(),
        'en_attente': assets.filter(statut='en_attente').count(),
        'termine': assets.filter(statut='termine').count(),
        'has_huggingface_token': bool(settings.HUGGINGFACE_API_TOKEN),
    }
    return render(request, '03_upload.html', context)


# ── API JSON ────────────────────────────────────────────────────

def api_setup_folders(request):
    _init_cloudinary()
    results = create_medallion_folders()
    return JsonResponse({'success': True, 'folders': results})


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


def api_compare_asset(request, public_id):
    _init_cloudinary()
    try:
        data = compare_layers(public_id)
        return JsonResponse(data)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


def api_assets_db(request):
    assets = list(MediaAsset.objects.values(
        'public_id', 'nom_fichier', 'nom_produit', 'categorie',
        'url_image_source', 'url_bronze', 'url_silver', 'url_gold',
        'format', 'width', 'height', 'taille_bronze', 'taille_gold',
        'type_fichier', 'statut', 'couche_actuelle', 'pipeline_complet',
        'cree_le', 'ai_caption', 'ai_tags', 'ai_tag_source', 'ai_analyzed_at',
    ))
    return JsonResponse({'count': len(assets), 'assets': assets}, json_dumps_params={'default': str})


def api_asset_detail(request, public_id):
    try:
        asset = MediaAsset.objects.values(
            'public_id', 'nom_fichier', 'nom_produit', 'categorie',
            'url_image_source', 'url_bronze', 'url_silver', 'url_gold',
            'format', 'width', 'height', 'taille_bronze', 'taille_gold',
            'type_fichier', 'statut', 'couche_actuelle', 'pipeline_complet',
            'fichier_source', 'cree_le', 'ai_caption', 'ai_tags',
            'ai_tag_source', 'ai_analyzed_at',
        ).get(public_id=public_id)
    except ObjectDoesNotExist:
        return JsonResponse({'error': 'asset introuvable'}, status=404)

    return JsonResponse(asset, json_dumps_params={'default': str})


@require_POST
def api_generate_tags(request):
    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except json.JSONDecodeError:
        payload = {}

    mode = payload.get('mode', 'missing')
    public_ids = payload.get('public_ids') or []
    force_visual = bool(payload.get('force_visual'))

    queryset = MediaAsset.objects.filter(type_fichier='image').order_by('-cree_le')
    if public_ids:
        queryset = queryset.filter(public_id__in=public_ids)

    results = []
    updated = 0
    skipped = 0
    errors = 0

    for asset in queryset:
        if mode == 'missing' and asset.ai_tags:
            skipped += 1
            results.append({
                'public_id': asset.public_id,
                'status': 'skipped',
                'reason': 'already_tagged',
                'tags': asset.ai_tags,
                'caption': asset.ai_caption,
            })
            continue
        if mode == 'fallback' and asset.ai_tag_source != 'metadata-fallback':
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
                'tags': tagging.tags,
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