import csv
import json
from pathlib import Path

from django.core.management.base import BaseCommand
from django.core.serializers.json import DjangoJSONEncoder

from portal.models import MediaAsset

# Noms distincts de ceux du script standalone (medallion_catalogue.*)
# pour ne jamais écraser son propre catalogue si les deux tournent dans le même dossier.
JSON_DEFAUT = Path("dam_catalogue.json")
CSV_DEFAUT  = Path("dam_catalogue.csv")

CHAMPS = [
    "public_id", "nom_fichier", "reference", "nom_produit", "categorie",
    "marque", "labels", "conservation", "nouveaute", "url_produit",
    "type_fichier", "format", "width", "height",
    "url_bronze", "url_silver", "url_gold",
    "taille_bronze", "taille_gold", "gain_compression",
    "couche_actuelle", "pipeline_complet", "statut",
    "ai_caption", "ai_tags", "ai_tag_source", "ai_analyzed_at",
    "cree_le",
]


class Command(BaseCommand):
    help = "Exporte tous les MediaAsset de la base Django en catalogue CSV + JSON unifié."

    def add_arguments(self, parser):
        parser.add_argument("--out-json", default=str(JSON_DEFAUT))
        parser.add_argument("--out-csv", default=str(CSV_DEFAUT))

    def handle(self, *args, **options):
        assets = MediaAsset.objects.all().order_by("-cree_le")

        catalogue = []
        for a in assets:
            catalogue.append({
                "public_id":         a.public_id,
                "nom_fichier":       a.nom_fichier,
                "reference":         a.reference,
                "nom_produit":       a.nom_produit,
                "categorie":         a.categorie,
                "marque":            a.marque,
                "labels":            a.labels,
                "conservation":      a.conservation,
                "nouveaute":         a.nouveaute,
                "url_produit":       a.url_produit,
                "type_fichier":      a.type_fichier,
                "format":            a.format,
                "width":             a.width,
                "height":            a.height,
                "url_bronze":        a.url_bronze,
                "url_silver":        a.url_silver,
                "url_gold":          a.url_gold,
                "taille_bronze":     a.taille_bronze,
                "taille_gold":       a.taille_gold,
                "gain_compression":  a.gain_compression,
                "couche_actuelle":   a.couche_actuelle,
                "pipeline_complet":  a.pipeline_complet,
                "statut":            a.statut,
                "ai_caption":        a.ai_caption,
                "ai_tags":           a.ai_tags,
                "ai_tag_source":     a.ai_tag_source,
                "ai_analyzed_at":    a.ai_analyzed_at,
                "cree_le":           a.cree_le,
            })

        json_path = Path(options["out_json"])
        csv_path = Path(options["out_csv"])

        # ── JSON ──
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(catalogue, f, ensure_ascii=False, indent=2, cls=DjangoJSONEncoder)

        # ── CSV ──
        with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=CHAMPS, extrasaction="ignore")
            writer.writeheader()
            for row in catalogue:
                # ai_tags est une liste JSON → aplatie en chaîne pour le CSV
                row = dict(row)
                row["ai_tags"] = " | ".join(row["ai_tags"]) if row["ai_tags"] else ""
                writer.writerow(row)

        self.stdout.write(self.style.SUCCESS(f"✅ {len(catalogue)} asset(s) exporté(s)"))
        self.stdout.write(f"   💾 {json_path}")
        self.stdout.write(f"   💾 {csv_path}")