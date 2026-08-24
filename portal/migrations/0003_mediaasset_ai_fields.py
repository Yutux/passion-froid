from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('portal', '0002_mediaasset_new_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='mediaasset',
            name='ai_analyzed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='mediaasset',
            name='ai_caption',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='mediaasset',
            name='ai_tag_source',
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name='mediaasset',
            name='ai_tags',
            field=models.JSONField(blank=True, default=list),
        ),
    ]
