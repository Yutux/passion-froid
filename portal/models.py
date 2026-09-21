from django.db import models
from django.utils import timezone


class Tag(models.Model):
    name = models.CharField(max_length=80)
    key = models.CharField(max_length=100, unique=True)
    category = models.CharField(max_length=80, blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']


class TagCorrection(models.Model):
    asset = models.ForeignKey('MediaAsset', on_delete=models.CASCADE, related_name='corrections')
    before = models.JSONField(default=list)
    after = models.JSONField(default=list)
    reference = models.CharField(max_length=20, blank=True)
    author = models.CharField(max_length=150)
    created_at = models.DateTimeField(auto_now_add=True)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ['-created_at']


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
        ('archive',    'Archive'),
        ('termine',    'Terminé'),
    ]

    MEDIA_STATUS_CHOICES = [
        ('UPLOADED', 'Uploaded'),
        ('AI_ANALYZING', 'AI analyzing'),
        ('AI_ANALYZED', 'AI analyzed'),
        ('ADMIN_REVIEW', 'Admin review'),
        ('APPROVED', 'Approved'),
        ('REJECTED', 'Rejected'),
        ('NEEDS_CORRECTION', 'Needs correction'),
        ('ARCHIVED', 'Archived'),
    ]

    public_id    = models.CharField(max_length=255, unique=True)
    nom_fichier  = models.CharField(max_length=255, blank=True)
    md5_source = models.CharField(max_length=32, unique=True, null=True, blank=True, db_index=True)
    perceptual_hash = models.CharField(max_length=16, blank=True, db_index=True)
    color_signature = models.JSONField(default=list, blank=True)

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
    media_status     = models.CharField(max_length=30, choices=MEDIA_STATUS_CHOICES, default='UPLOADED', db_index=True)
    couche_actuelle  = models.CharField(max_length=10, choices=LAYER_CHOICES, default='bronze')
    pipeline_complet = models.BooleanField(default=False)
    ai_title         = models.CharField(max_length=255, blank=True)
    ai_caption       = models.TextField(blank=True)
    ai_tags          = models.JSONField(default=list, blank=True)
    ai_categories    = models.JSONField(default=list, blank=True)
    ai_objects       = models.JSONField(default=list, blank=True)
    ai_people        = models.JSONField(default=list, blank=True)
    ai_logos         = models.JSONField(default=list, blank=True)
    ai_ocr           = models.JSONField(default=list, blank=True)
    ai_context       = models.JSONField(default=list, blank=True)
    ai_places        = models.JSONField(default=list, blank=True)
    ai_colors        = models.JSONField(default=list, blank=True)
    ai_concepts      = models.JSONField(default=list, blank=True)
    ai_visual_types  = models.JSONField(default=list, blank=True)
    ai_confidence    = models.JSONField(default=dict, blank=True)
    ai_analysis      = models.JSONField(default=dict, blank=True)
    ai_embedding     = models.JSONField(default=list, blank=True)
    search_embedding_model = models.CharField(max_length=150, blank=True)
    search_embedding_hash = models.CharField(max_length=64, blank=True)
    ai_tag_source    = models.CharField(max_length=100, blank=True)
    ai_analyzed_at   = models.DateTimeField(null=True, blank=True)
    gold_title       = models.CharField(max_length=255, blank=True)
    gold_description = models.TextField(blank=True)
    gold_tags        = models.JSONField(default=list, blank=True)
    gold_categories  = models.JSONField(default=list, blank=True)
    gold_feedback    = models.JSONField(default=list, blank=True)
    tags_validated   = models.BooleanField(default=False, db_index=True)
    tags_validated_at = models.DateTimeField(null=True, blank=True)
    tags_validated_by = models.CharField(max_length=150, blank=True)
    duplicate_key    = models.CharField(max_length=255, blank=True, db_index=True)
    duplicate_group  = models.CharField(max_length=255, blank=True, db_index=True)
    validation_notes = models.TextField(blank=True)
    firebase_document_id = models.CharField(max_length=255, blank=True)
    firebase_synced_at   = models.DateTimeField(null=True, blank=True)
    firebase_sync_error  = models.TextField(blank=True)

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


class AnalysisJob(models.Model):
    asset = models.OneToOneField(MediaAsset, on_delete=models.CASCADE, related_name='analysis_job')
    status = models.CharField(max_length=12, default='PENDING', db_index=True)
    attempts = models.PositiveIntegerField(default=0)
    next_run = models.DateTimeField(default=timezone.now, db_index=True)
    lease_until = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)


class WorkerHeartbeat(models.Model):
    name = models.CharField(max_length=40, primary_key=True)
    last_seen = models.DateTimeField(default=timezone.now)


class TagFeedback(models.Model):
    asset = models.ForeignKey(MediaAsset, on_delete=models.CASCADE, related_name='tag_events')
    action = models.CharField(max_length=10, choices=[('add', 'Ajouter'), ('remove', 'Retirer')])
    tag = models.CharField(max_length=80)
    reason = models.CharField(max_length=500)
    author = models.CharField(max_length=150)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-pk']


class FirebaseOutbox(models.Model):
    collection = models.CharField(max_length=80)
    document_id = models.CharField(max_length=180)
    payload = models.JSONField(default=dict)
    attempts = models.PositiveIntegerField(default=0)
    next_run = models.DateTimeField(default=timezone.now, db_index=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    error = models.CharField(max_length=300, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['collection', 'document_id'], name='unique_outbox_document')]
