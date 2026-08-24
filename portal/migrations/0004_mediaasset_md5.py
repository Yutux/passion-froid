from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('portal', '0003_mediaasset_ai_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='mediaasset',
            name='md5_source',
            field=models.CharField(blank=True, db_index=True, max_length=32, null=True, unique=True),
        ),
    ]