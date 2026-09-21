from django.db import migrations
import unicodedata
import re


def seed_tags(apps, schema_editor):
    Asset = apps.get_model('portal', 'MediaAsset')
    Tag = apps.get_model('portal', 'Tag')
    seen = set()
    for asset in Asset.objects.all().iterator():
        for value in (asset.gold_tags or []) + (asset.ai_tags or []):
            if not isinstance(value, str) or not value.strip():
                continue
            name = value.strip()[:80]
            key = unicodedata.normalize('NFKD', name)
            key = ''.join(c for c in key if not unicodedata.combining(c))
            key = re.sub(r'\s+', ' ', key.casefold()).strip()
            if key in seen:
                continue
            seen.add(key)
            Tag.objects.get_or_create(key=key, defaults={'name': name})


class Migration(migrations.Migration):
    dependencies = [('portal', '0009_tag_tagcorrection')]
    operations = [migrations.RunPython(seed_tags, migrations.RunPython.noop)]
