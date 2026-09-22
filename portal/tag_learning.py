"""Controlled vocabulary and human-approved, product-scoped correction memory."""
import unicodedata
import re
from .models import Tag, TagCorrection, TagFeedback, MediaAsset


def tag_key(value):
    value = unicodedata.normalize('NFKD', str(value))
    value = ''.join(c for c in value if not unicodedata.combining(c))
    return re.sub(r'\s+', ' ', value.casefold()).strip()


def canonical_tags(values):
    vocabulary = {tag.key: tag for tag in Tag.objects.all()}
    result, seen = [], set()
    for value in values:
        key = tag_key(value)
        tag = vocabulary.get(key)
        if not key or key in seen or (tag and not tag.active):
            continue
        seen.add(key)
        result.append(tag.name if tag else str(value).strip()[:80])
    return result[:24]


def apply_corrections(asset, tags):
    history = TagCorrection.objects.filter(asset=asset, active=True)
    if asset.reference:
        from django.db.models import Q
        history = TagCorrection.objects.filter(Q(asset=asset) | Q(reference=asset.reference), active=True)
    # Latest reviewed example wins per tag, including explicit removals.
    decisions = {}
    applied = []
    decided_at = {}
    for correction in history[:100]:
        before = {tag_key(t): t for t in correction.before}
        after = {tag_key(t): t for t in correction.after}
        for key in before.keys() | after.keys():
            if key not in decisions:
                decisions[key] = after.get(key)
                decided_at[key] = correction.created_at
        applied.append(correction.pk)
    # Explicit tag feedback is reusable immediately, including on near-duplicates.
    from .image_memory import is_near_duplicate
    related_ids = {asset.pk}
    candidates = MediaAsset.objects.filter(tag_events__active=True).exclude(pk=asset.pk).distinct()
    for candidate in candidates[:500]:
        if (asset.reference and asset.reference == candidate.reference) or is_near_duplicate(asset, candidate):
            related_ids.add(candidate.pk)
    events = TagFeedback.objects.filter(asset_id__in=related_ids, active=True)
    for event in events[:300]:
        key = tag_key(event.tag)
        if key not in decided_at or event.created_at > decided_at[key]:
            decisions[key] = event.tag if event.action == 'add' else None
            decided_at[key] = event.created_at
    result = [t for t in tags if tag_key(t) not in decisions]
    result.extend(value for value in decisions.values() if value is not None)
    return canonical_tags(result), applied


def feedback_context(asset, limit=12):
    """Give the remote model the reviewed rationale, not just a blacklist."""
    from .image_memory import is_near_duplicate
    related_ids = {asset.pk}
    for candidate in MediaAsset.objects.filter(tag_events__active=True).exclude(pk=asset.pk).distinct()[:500]:
        if (asset.reference and asset.reference == candidate.reference) or is_near_duplicate(asset,candidate):
            related_ids.add(candidate.pk)
    return [{'action':event.action,'tag':event.tag,'reason':event.reason,
             'scope':'same_image' if event.asset_id==asset.pk else 'same_product_or_near_duplicate'}
            for event in TagFeedback.objects.filter(asset_id__in=related_ids,active=True)[:limit]]
