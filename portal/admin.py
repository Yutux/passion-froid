from django.contrib import admin
from .models import MediaAsset


@admin.register(MediaAsset)
class MediaAssetAdmin(admin.ModelAdmin):
    list_display  = ('public_id', 'reference', 'ai_title', 'categorie', 'couche_actuelle',
                      'pipeline_complet', 'tags_validated', 'ai_caption_courte', 'ai_tags', 'firebase_synced_at',
                      'gain_compression', 'cree_le')
    list_filter   = ('couche_actuelle', 'pipeline_complet', 'tags_validated', 'ai_tag_source', 'categorie', 'conservation', 'nouveaute')
    search_fields = ('public_id', 'nom_fichier', 'reference', 'nom_produit', 'marque', 'ai_title', 'ai_caption')
    readonly_fields = ('gain_compression', 'url_production', 'cree_le', 'modifie_le',
                       'ai_tag_source', 'ai_analyzed_at',
                       'firebase_document_id', 'firebase_synced_at', 'firebase_sync_error')
    fieldsets = (
        ('Identification', {
            'fields': ('public_id', 'nom_fichier', 'md5_source', 'format', 'width', 'height')
        }),
        ('Produit', {
            'fields': ('reference', 'nom_produit', 'categorie', 'marque', 'labels',
                       'conservation', 'nouveaute', 'url_produit'),
        }),
        ('URLs Medallion', {
            'fields': ('url_bronze', 'url_silver', 'url_gold', 'url_production')
        }),
        ('Statistiques', {
            'fields': ('taille_bronze', 'taille_gold', 'gain_compression')
        }),
        ('Intelligence Artificielle', {
            'fields': ('ai_title', 'ai_caption', 'ai_tags', 'ai_tag_source', 'ai_analyzed_at',
                       'tags_validated', 'tags_validated_at', 'tags_validated_by',
                       'duplicate_key', 'duplicate_group', 'validation_notes'),
            'description': "Résultat du tagging IA (BLIP ou fallback métadonnées) — lecture seule.",
        }),
        ('Statut Pipeline', {
            'fields': ('couche_actuelle', 'pipeline_complet', 'cree_le', 'modifie_le')
        }),
        ('Firebase', {
            'fields': ('firebase_document_id', 'firebase_synced_at', 'firebase_sync_error'),
            'description': "Index Firestore utilise par la recherche IA et les tags.",
        }),
    )

    @admin.display(description="Description IA")
    def ai_caption_courte(self, obj):
        return (obj.ai_caption[:60] + "…") if len(obj.ai_caption or "") > 60 else obj.ai_caption
