from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('portal', '0005_mediaasset_conservation_mediaasset_labels_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='mediaasset',
            name='firebase_document_id',
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name='mediaasset',
            name='firebase_sync_error',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='mediaasset',
            name='firebase_synced_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
