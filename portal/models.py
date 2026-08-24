from django.db import models


class MediaAsset(models.Model):
    """
    Représente un asset passé par le pipeline Medallion.
    Stocke les URLs des 3 couches : bronze, silver, gold.
    """

    LAYER_CHOICES = [
        ('bronze', '🥉 Bronze'),
        ('silver', '🥈 Silver'),
        ('gold',   '🥇 Gold'),
    ]

    TYPE_CHOICES = [
        ('image', 'Image'),
        ('video', 'Vidéo'),
        ('json',  'JSON'),
        ('csv',   'CSV'),
        ('autre', 'Autre'),
    ]

    STATUT_CHOICES = [
        ('en_attente', 'En attente'),
        ('en_cours',   'En cours'),
        ('termine',    'Terminé'),
    ]

    public_id    = models.CharField(max_length=255, unique=True)
    nom_fichier  = models.CharField(max_length=255, blank=True)
    md5_source = models.CharField(max_length=32, unique=True, null=True, blank=True, db_index=True)

   # Champs enrichis (JSON/produits)
    reference      = models.CharField(max_length=20, blank=True, db_index=True)
    nom_produit    = models.CharField(max_length=500, blank=True)
    categorie      = models.CharField(max_length=255, blank=True)
    marque         = models.CharField(max_length=255, blank=True)
    labels         = models.CharField(max_length=500, blank=True)
    conservation   = models.CharField(max_length=50, blank=True)
    nouveaute      = models.BooleanField(default=False)
    url_produit    = models.URLField(max_length=1000, blank=True)
    url_image_source = models.URLField(max_length=1000, blank=True)
    fichier_source = models.CharField(max_length=255, blank=True)


    url_bronze   = models.URLField(max_length=500, blank=True)
    url_silver   = models.URLField(max_length=500, blank=True)
    url_gold     = models.URLField(max_length=500, blank=True)

    format       = models.CharField(max_length=20, blank=True)
    width        = models.PositiveIntegerField(null=True, blank=True)
    height       = models.PositiveIntegerField(null=True, blank=True)
    taille_bronze = models.PositiveIntegerField(null=True, blank=True)
    taille_gold   = models.PositiveIntegerField(null=True, blank=True)

    type_fichier     = models.CharField(max_length=10, choices=TYPE_CHOICES, default='image')
    statut           = models.CharField(max_length=20, choices=STATUT_CHOICES, default='en_cours')
    couche_actuelle  = models.CharField(max_length=10, choices=LAYER_CHOICES, default='bronze')
    pipeline_complet = models.BooleanField(default=False)
    ai_caption       = models.TextField(blank=True)
    ai_tags          = models.JSONField(default=list, blank=True)
    ai_tag_source    = models.CharField(max_length=100, blank=True)
    ai_analyzed_at   = models.DateTimeField(null=True, blank=True)

    cree_le    = models.DateTimeField(auto_now_add=True)
    modifie_le = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Asset Média"
        verbose_name_plural = "Assets Médias"
        ordering = ['-cree_le']

    def __str__(self):
        return f"{self.public_id} [{self.couche_actuelle}]"

    @property
    def gain_compression(self):
        if self.taille_bronze and self.taille_gold:
            gain = (1 - self.taille_gold / self.taille_bronze) * 100
            return f"{round(gain, 1)}%"
        return None

    @property
    def url_production(self):
        return self.url_gold or self.url_silver or self.url_bronze

    @property
    def has_ai_tags(self):
        return bool(self.ai_tags)
