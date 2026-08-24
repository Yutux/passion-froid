import csv
import hashlib
import json
import os
import re
import uuid
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from portal.ai_tags import TaggingError, generate_ai_metadata_for_asset
from portal.cloudinary_medallion import configure_cloudinary, run_medallion_pipeline
from portal.models import MediaAsset

# Mêmes dossiers que ceux utilisés par le scraper (scrape_passionfroid.py)
DOSSIERS = [
    (Path("medias_passionfroid/images"), "image"),
    (Path("medias_passionfroid/videos/site"), "video"),
    (Path("medias_passionfroid/videos/youtube"), "video"),
]

# CSV produits généré par scrape_passionfroid.py (export_csv)
CSV_PRODUITS = Path("passionfroid_complet.csv")

# Log des échecs — permet de savoir après coup quels fichiers ont échoué et pourquoi,
# même si le terminal a été fermé entre-temps.
LOG_ERREURS = Path("import_scraped_media_erreurs.json")

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
VIDEO_EXTS = {".mp4", ".webm", ".mov", ".avi", ".mkv", ".m4v", ".ogg"}


def _charger_log_erreurs() -> dict:
    if LOG_ERREURS.exists():
        try:
            with open(LOG_ERREURS, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _sauvegarder_log_erreurs(log: dict):
    with open(LOG_ERREURS, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)


def _safe_name(name):
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in name)


def _md5_de_chemin(chemin: Path) -> str:
    hasher = hashlib.md5()
    with open(chemin, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _charger_index_produits() -> dict:
    """
    Charge passionfroid_complet.csv et indexe chaque ligne par référence produit,
    pour retrouver marque/labels/conservation/etc. à partir du nom de fichier local.
    """
    index = {}
    if not CSV_PRODUITS.exists():
        return index
    with open(CSV_PRODUITS, "r", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            ref = (row.get("reference") or "").strip()
            if ref:
                index[ref] = row
    return index


def _produit_depuis_fichier(nom_fichier: str, index: dict) -> dict:
    """Retrouve la fiche produit CSV via la référence en tête du nom de fichier local (ex: '123456.jpg')."""
    m = re.match(r"(\d{4,7})", nom_fichier)
    if not m:
        return {}
    return index.get(m.group(1), {})


class Command(BaseCommand):
    help = (
        "Ingère automatiquement les images/vidéos déjà téléchargées par le scraper : "
        "pipeline Medallion complet (bronze→silver→gold) + tagging IA, "
        "exactement comme le fait l'upload manuel d'un seul fichier. "
        "Dédoublonne par MD5 : ne retraite jamais un fichier déjà importé."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--skip-ai",
            action="store_true",
            help="Ne pas lancer le tagging IA après le pipeline (utile pour aller vite).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Simulation : liste ce qui serait traité, sans toucher Cloudinary ni la base.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        configure_cloudinary()

        index_produits = _charger_index_produits()
        if index_produits:
            self.stdout.write(f"📋 {len(index_produits)} produit(s) chargé(s) depuis {CSV_PRODUITS}")
        else:
            self.stdout.write(f"⚠️  {CSV_PRODUITS} introuvable — les assets seront créés sans métadonnées produit.")

        log_erreurs = _charger_log_erreurs()
        if log_erreurs:
            self.stdout.write(f"📋 {len(log_erreurs)} échec(s) enregistré(s) lors d'un run précédent")

        if dry_run:
            self.stdout.write(self.style.WARNING("🔍 DRY-RUN — aucun upload, aucune écriture en base\n"))

        traites = 0
        ignores = 0
        erreurs = 0

        for dossier, type_defaut in DOSSIERS:
            if not dossier.exists():
                self.stdout.write(f"⚠️  Dossier introuvable, ignoré : {dossier}")
                continue

            exts = IMAGE_EXTS if type_defaut == "image" else VIDEO_EXTS
            fichiers = sorted(f for f in dossier.rglob("*") if f.suffix.lower() in exts)

            self.stdout.write(f"\n📂 {dossier} — {len(fichiers)} fichier(s)")

            for chemin in fichiers:
                md5 = _md5_de_chemin(chemin)

                if MediaAsset.objects.filter(md5_source=md5).exists():
                    ignores += 1
                    continue

                if dry_run:
                    self.stdout.write(f"  [DRY] {chemin.name}")
                    traites += 1
                    continue

                try:
                    base_name = os.path.splitext(chemin.name)[0]
                    public_id = f"{_safe_name(base_name)}_{uuid.uuid4().hex[:8]}"
                    produit = _produit_depuis_fichier(chemin.name, index_produits)

                    result = run_medallion_pipeline(
                        file=str(chemin),
                        public_id=public_id,
                        silver_max_size=settings.CLOUDINARY_SILVER_MAX_SIZE,
                        gold_width=settings.CLOUDINARY_GOLD_WIDTH,
                        gold_quality=settings.CLOUDINARY_GOLD_QUALITY,
                    )
                    bronze_info = result["layers"]["bronze"]
                    gold_info = result["layers"]["gold"]

                    video_exts = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
                    type_f = "video" if chemin.suffix.lower() in video_exts else "image"

                    asset = MediaAsset.objects.create(
                        public_id=public_id,
                        nom_fichier=chemin.name,
                        fichier_source=str(chemin),
                        md5_source=md5,
                        reference=produit.get("reference", ""),
                        nom_produit=produit.get("nom", ""),
                        categorie=produit.get("categorie", ""),
                        marque=produit.get("marque", ""),
                        labels=produit.get("labels", ""),
                        conservation=produit.get("conservation", ""),
                        nouveaute=(produit.get("nouveaute", "Non").strip().lower() == "oui"),
                        url_produit=produit.get("url_produit", ""),
                        url_bronze=result["urls"]["bronze"],
                        url_silver=result["urls"]["silver"],
                        url_gold=result["urls"]["gold"],
                        url_image_source=result["urls"]["gold"] or result["urls"]["bronze"],
                        format=bronze_info.get("format", ""),
                        width=bronze_info.get("width"),
                        height=bronze_info.get("height"),
                        taille_bronze=bronze_info.get("bytes"),
                        taille_gold=gold_info.get("bytes"),
                        type_fichier=type_f,
                        statut="en_cours",
                        couche_actuelle="gold",
                        pipeline_complet=True,
                    )

                    # ── Tagging IA automatique, comme upload_view ──
                    if type_f == "image" and not options["skip_ai"]:
                        try:
                            tagging = generate_ai_metadata_for_asset(asset, allow_fallback=True)
                            asset.ai_caption = tagging.caption
                            asset.ai_tags = tagging.tags
                            asset.ai_tag_source = tagging.source
                            from django.utils import timezone
                            asset.ai_analyzed_at = timezone.now()
                            asset.save(update_fields=[
                                "ai_caption", "ai_tags", "ai_tag_source",
                                "ai_analyzed_at", "modifie_le",
                            ])
                        except TaggingError as exc:
                            self.stderr.write(f"  ⚠️  IA échouée pour {chemin.name} : {exc}")

                    traites += 1
                    self.stdout.write(f"  ✅  {chemin.name}")

                    # Si ce fichier avait échoué avant et réussit maintenant, on nettoie le log
                    if md5 in log_erreurs:
                        del log_erreurs[md5]
                        _sauvegarder_log_erreurs(log_erreurs)

                except Exception as exc:
                    erreurs += 1
                    self.stderr.write(f"  ❌  {chemin.name} : {exc}")

                    log_erreurs[md5] = {
                        "fichier": chemin.name,
                        "chemin": str(chemin),
                        "erreur": str(exc),
                        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    }
                    _sauvegarder_log_erreurs(log_erreurs)

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"Traités : {traites}"))
        self.stdout.write(f"Déjà importés (ignorés) : {ignores}")
        if erreurs:
            self.stderr.write(self.style.ERROR(f"Erreurs : {erreurs} — détails dans {LOG_ERREURS}"))