from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name='MediaAsset',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('public_id',    models.CharField(max_length=255, unique=True)),
                ('nom_fichier',  models.CharField(blank=True, max_length=255)),
                ('url_bronze',   models.URLField(blank=True, max_length=500)),
                ('url_silver',   models.URLField(blank=True, max_length=500)),
                ('url_gold',     models.URLField(blank=True, max_length=500)),
                ('format',       models.CharField(blank=True, max_length=20)),
                ('width',        models.PositiveIntegerField(blank=True, null=True)),
                ('height',       models.PositiveIntegerField(blank=True, null=True)),
                ('taille_bronze',models.PositiveIntegerField(blank=True, null=True)),
                ('taille_gold',  models.PositiveIntegerField(blank=True, null=True)),
                ('couche_actuelle', models.CharField(
                    choices=[('bronze','🥉 Bronze'),('silver','🥈 Silver'),('gold','🥇 Gold')],
                    default='bronze', max_length=10
                )),
                ('pipeline_complet', models.BooleanField(default=False)),
                ('cree_le',    models.DateTimeField(auto_now_add=True)),
                ('modifie_le', models.DateTimeField(auto_now=True)),
            ],
            options={'verbose_name': 'Asset Média', 'verbose_name_plural': 'Assets Médias', 'ordering': ['-cree_le']},
        ),
    ]
