"""Hybrid retrieval over approved media: French lexical matches + multilingual E5."""
import hashlib
import math
import re
import threading

from django.conf import settings
from django.core.cache import cache
from django.db import close_old_connections
from .models import MediaAsset
from .tag_learning import tag_key

STOPWORDS = set('je veux cherche recherche trouve trouver une un des de du la le les l d avec et dans sur pour photo photos image images montrer montre voudrais qui que'.split())
SYNONYMS = {
    'legume': ['legumes'], 'legumes': ['legume', 'carotte', 'brocoli', 'courgette'],
    'poisson': ['saumon', 'cabillaud', 'colin', 'truite'],
    'crevette': ['crevettes'], 'crevettes': ['crevette'],
    'cuisinier': ['chef cuisinier', 'cuisiniere'], 'chef': ['chef cuisinier', 'cuisinier'],
    'dessert': ['gateau', 'tarte', 'patisserie', 'glace'],
    'boeuf': ['bœuf', 'steak', 'entrecote'], 'bœuf': ['boeuf', 'steak', 'entrecote'],
    'rouges': ['rouge'], 'verts': ['vert'], 'blancs': ['blanc'],
}


def published_assets():
    return MediaAsset.objects.filter(pipeline_complet=True, tags_validated=True, media_status='APPROVED').exclude(statut='archive')


def document(asset):
    # Only approved text contributes to semantic retrieval. Rejected AI tags do not leak back.
    return ' '.join(str(v) for v in [asset.gold_title or asset.ai_title, asset.gold_description,
        ' '.join(asset.gold_tags), asset.nom_produit, asset.categorie, asset.reference] if v)


def document_hash(asset):
    return hashlib.sha256(document(asset).encode()).hexdigest()


def normalize_vector(value):
    if hasattr(value, 'tolist'):
        value = value.tolist()
    if isinstance(value, list) and len(value) == 1 and isinstance(value[0], list):
        value = value[0]
    if not isinstance(value, list) or len(value) < 2 or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in value):
        raise ValueError('Vecteur de recherche invalide.')
    norm = math.sqrt(sum(v*v for v in value))
    if norm == 0:
        raise ValueError('Vecteur nul.')
    return [v/norm for v in value]


def embed(text, prefix):
    from huggingface_hub import InferenceClient
    if not getattr(settings, 'HUGGINGFACE_API_TOKEN', ''):
        raise ValueError('Token IA non configuré.')
    client = InferenceClient(provider='hf-inference', api_key=settings.HUGGINGFACE_API_TOKEN, timeout=12)
    output = client.feature_extraction(prefix + ': ' + text[:6000], model=settings.HUGGINGFACE_SEARCH_MODEL)
    return normalize_vector(output)


def index_asset(asset):
    if not asset.tags_validated or asset.media_status != 'APPROVED':
        return False
    digest = document_hash(asset)
    if asset.search_embedding_model == settings.HUGGINGFACE_SEARCH_MODEL and asset.search_embedding_hash == digest and asset.ai_embedding:
        return False
    vector = embed(document(asset), 'passage')
    # Optimistic check prevents publishing an embedding of a superseded review.
    current = MediaAsset.objects.get(pk=asset.pk)
    if not current.tags_validated or current.media_status != 'APPROVED' or document_hash(current) != digest:
        return False
    MediaAsset.objects.filter(pk=asset.pk, modifie_le=current.modifie_le, tags_validated=True).update(
        ai_embedding=vector, search_embedding_model=settings.HUGGINGFACE_SEARCH_MODEL, search_embedding_hash=digest)
    return True


def start_index_asset(asset_id):
    if not getattr(settings, 'HUGGINGFACE_SEARCH_ENABLED', True):
        return
    def worker():
        close_old_connections()
        try:
            index_asset(MediaAsset.objects.get(pk=asset_id))
        except Exception:
            # Failed remote indexing leaves lexical search fully available; command can retry.
            pass
        finally:
            close_old_connections()
    threading.Thread(target=worker, daemon=True).start()


def tokens(text):
    return [t for t in re.findall(r'[\wœ]+', tag_key(text)) if t not in STOPWORDS]


def lexical_score(asset, query):
    primary = tokens(query)
    if not primary:
        return 0, []
    fields = [(asset.gold_title or asset.ai_title, 5), (' '.join(asset.gold_tags), 6),
              (asset.gold_description, 3), (' '.join([asset.nom_produit,asset.categorie,asset.reference]), 2)]
    fields = [(tag_key(text), weight) for text, weight in fields]
    score, matches = 0, []
    for term in primary:
        alternatives = [term] + SYNONYMS.get(term, [])
        best = 0
        for text, weight in fields:
            if re.search(r'(?<!\w)' + re.escape(term) + r'(?!\w)', text):
                best = max(best, weight * 2)
            elif any(re.search(r'(?<!\w)' + re.escape(other) + r'(?!\w)', text) for other in alternatives[1:]):
                best = max(best, weight)
        if best:
            matches.append(term)
            score += best
    coverage = len(matches) / len(primary)
    return score * coverage + (15 if coverage == 1 else 0), matches


def search(query, category='', color='', visual_type='', media_type='', limit=120, semantic=True):
    assets = list(published_assets().order_by('-cree_le'))
    if category:
        assets = [a for a in assets if tag_key(a.categorie) == tag_key(category)]
    # Facet filters only match tags accepted by the reviewer.
    for value in (color, visual_type):
        if value:
            assets = [a for a in assets if tag_key(value) in {tag_key(t) for t in a.gold_tags}]
    if media_type:
        assets = [a for a in assets if a.type_fichier == media_type]
    mode = 'lexical'
    qvector = None
    indexed = [a for a in assets if a.ai_embedding and a.search_embedding_model == settings.HUGGINGFACE_SEARCH_MODEL and a.search_embedding_hash == document_hash(a)]
    notice = ''
    if query and semantic and indexed and getattr(settings, 'HUGGINGFACE_SEARCH_ENABLED', True):
        query_key = 'semantic:query:' + hashlib.sha256((settings.HUGGINGFACE_SEARCH_MODEL + query).encode()).hexdigest()
        qvector = cache.get(query_key)
        if qvector is None and not cache.get('semantic:unavailable'):
            try:
                qvector = embed(query, 'query')
                cache.set(query_key, qvector, 3600)
            except Exception:
                cache.set('semantic:unavailable', True, 60)
        if qvector:
            mode = 'hybrid'
        else:
            notice = 'Recherche par mots-clés : le service de recherche sémantique est temporairement indisponible.'
    elif query and semantic:
        notice = 'Recherche par mots-clés. Les médias validés sont progressivement indexés pour la recherche par sens.'
    indexed_ids = {a.pk for a in indexed}
    rows = []
    for asset in assets:
        score, matched = lexical_score(asset, query)
        semantic_match = False
        if qvector and asset.pk in indexed_ids and len(qvector) == len(asset.ai_embedding):
            similarity = sum(a*b for a,b in zip(qvector, asset.ai_embedding))
            if similarity >= .80:
                semantic_match = True
                score += (similarity-.75)*70
        if not query or score > 0:
            rows.append({'public_id':asset.public_id, 'score':round(score,3), 'matched':matched, 'semantic':semantic_match})
    if query:
        rows.sort(key=lambda row: row['score'], reverse=True)
    return {'results':rows[:limit], 'count':len(rows), 'mode':mode, 'notice':notice, 'indexed':len(indexed)}
