from django.contrib import admin
from .models import MediaAsset


@admin.register(MediaAsset)
class MediaAssetAdmin(admin.ModelAdmin):
    list_display  = ('public_id', 'reference', 'nom_produit', 'categorie', 'couche_actuelle',
                      'pipeline_complet', 'ai_caption_courte', 'ai_tags', 'gain_compression', 'cree_le')
    list_filter   = ('couche_actuelle', 'pipeline_complet', 'ai_tag_source', 'categorie', 'conservation', 'nouveaute')
    search_fields = ('public_id', 'nom_fichier', 'reference', 'nom_produit', 'marque', 'ai_caption')
    readonly_fields = ('gain_compression', 'url_production', 'cree_le', 'modifie_le',
                       'ai_caption', 'ai_tags', 'ai_tag_source', 'ai_analyzed_at')
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
            'fields': ('ai_caption', 'ai_tags', 'ai_tag_source', 'ai_analyzed_at'),
            'description': "Résultat du tagging IA (BLIP ou fallback métadonnées) — lecture seule.",
        }),
        ('Statut Pipeline', {
            'fields': ('couche_actuelle', 'pipeline_complet', 'cree_le', 'modifie_le')
        }),
    )

    @admin.display(description="Description IA")
    def ai_caption_courte(self, obj):
        return (obj.ai_caption[:60] + "…") if len(obj.ai_caption or "") > 60 else obj.ai_caption