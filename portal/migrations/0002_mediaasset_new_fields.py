from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('portal', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='mediaasset',
            name='nom_produit',
            field=models.CharField(blank=True, max_length=500),
        ),
        migrations.AddField(
            model_name='mediaasset',
            name='categorie',
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name='mediaasset',
            name='url_image_source',
            field=models.URLField(blank=True, max_length=1000),
        ),
        migrations.AddField(
            model_name='mediaasset',
            name='fichier_source',
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name='mediaasset',
            name='type_fichier',
            field=models.CharField(
                choices=[('image','Image'),('video','Vidéo'),('json','JSON'),('csv','CSV'),('autre','Autre')],
                default='image', max_length=10,
            ),
        ),
        migrations.AddField(
            model_name='mediaasset',
            name='statut',
            field=models.CharField(
                choices=[('en_attente','En attente'),('en_cours','En cours'),('termine','Terminé')],
                default='en_cours', max_length=20,
            ),
        ),
    ]
