import csv
import hashlib
import json
import os
import re
import sys
import uuid
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from portal.ai_tags import TaggingError
from portal.views import _store_ai_tags
from portal.cloudinary_medallion import configure_cloudinary, run_medallion_pipeline
from portal.firebase_sync import FirebaseSyncSkipped, sync_asset_to_firestore
from portal.models import MediaAsset

# MÃªmes dossiers que ceux utilisÃ©s par le scraper (scrape_passionfroid.py)
DOSSIERS = [
    (Path("medias_passionfroid/images"), "image"),
    (Path("medias_passionfroid/videos/site"), "video"),
    (Path("medias_passionfroid/videos/youtube"), "video"),
]

# CSV produits gÃ©nÃ©rÃ© par scrape_passionfroid.py (export_csv)
CSV_PRODUITS = Path("passionfroid_complet.csv")

# Log des Ã©checs â€” permet de savoir aprÃ¨s coup quels fichiers ont Ã©chouÃ© et pourquoi,
# mÃªme si le terminal a Ã©tÃ© fermÃ© entre-temps.
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
    Charge passionfroid_complet.csv et indexe chaque ligne par rÃ©fÃ©rence produit,
    pour retrouver marque/labels/conservation/etc. Ã  partir du nom de fichier local.
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
    """Retrouve la fiche produit CSV via la rÃ©fÃ©rence en tÃªte du nom de fichier local (ex: '123456.jpg')."""
    m = re.match(r"(\d{4,7})", nom_fichier)
    if not m:
        return {}
    return index.get(m.group(1), {})


class Command(BaseCommand):
    help = (
        "IngÃ¨re automatiquement les images/vidÃ©os dÃ©jÃ  tÃ©lÃ©chargÃ©es par le scraper : "
        "pipeline Medallion complet (bronzeâ†’silverâ†’gold) + tagging IA, "
        "exactement comme le fait l'upload manuel d'un seul fichier. "
        "DÃ©doublonne par MD5 : ne retraite jamais un fichier dÃ©jÃ  importÃ©."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--skip-ai",
            action="store_true",
            help="Ne pas lancer le tagging IA aprÃ¨s le pipeline (utile pour aller vite).",
        )
        parser.add_argument(
            "--skip-firebase",
            action="store_true",
            help="Ne pas synchroniser les assets dans Firestore apres l'upload Cloudinary.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Simulation : liste ce qui serait traitÃ©, sans toucher Cloudinary ni la base.",
        )

    def handle(self, *args, **options):
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")

        dry_run = options["dry_run"]
        configure_cloudinary()

        index_produits = _charger_index_produits()
        if index_produits:
            self.stdout.write(f"ðŸ“‹ {len(index_produits)} produit(s) chargÃ©(s) depuis {CSV_PRODUITS}")
        else:
            self.stdout.write(f"âš ï¸  {CSV_PRODUITS} introuvable â€” les assets seront crÃ©Ã©s sans mÃ©tadonnÃ©es produit.")

        log_erreurs = _charger_log_erreurs()
        if log_erreurs:
            self.stdout.write(f"ðŸ“‹ {len(log_erreurs)} Ã©chec(s) enregistrÃ©(s) lors d'un run prÃ©cÃ©dent")

        if dry_run:
            self.stdout.write(self.style.WARNING("ðŸ” DRY-RUN â€” aucun upload, aucune Ã©criture en base\n"))

        traites = 0
        ignores = 0
        erreurs = 0

        for dossier, type_defaut in DOSSIERS:
            if not dossier.exists():
                self.stdout.write(f"âš ï¸  Dossier introuvable, ignorÃ© : {dossier}")
                continue

            exts = IMAGE_EXTS if type_defaut == "image" else VIDEO_EXTS
            fichiers = sorted(f for f in dossier.rglob("*") if f.suffix.lower() in exts)

            self.stdout.write(f"\nðŸ“‚ {dossier} â€” {len(fichiers)} fichier(s)")

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
                        statut="termine",
                        couche_actuelle="silver",
                        pipeline_complet=False,
                    )

                    # â”€â”€ Tagging IA automatique, comme upload_view â”€â”€
                    if type_f == "image" and not options["skip_ai"]:
                        from portal.ai_worker import enqueue_asset
                        enqueue_asset(asset)

                    if not options["skip_firebase"]:
                        try:
                            sync_asset_to_firestore(asset)
                        except FirebaseSyncSkipped:
                            pass
                        except Exception as exc:
                            self.stderr.write(f"  âš ï¸  Sync Firebase Ã©chouÃ©e pour {chemin.name} : {exc}")

                    traites += 1
                    self.stdout.write(f"  âœ…  {chemin.name}")

                    # Si ce fichier avait Ã©chouÃ© avant et rÃ©ussit maintenant, on nettoie le log
                    if md5 in log_erreurs:
                        del log_erreurs[md5]
                        _sauvegarder_log_erreurs(log_erreurs)

                except Exception as exc:
                    erreurs += 1
                    self.stderr.write(f"  âŒ  {chemin.name} : {exc}")

                    log_erreurs[md5] = {
                        "fichier": chemin.name,
                        "chemin": str(chemin),
                        "erreur": str(exc),
                        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    }
                    _sauvegarder_log_erreurs(log_erreurs)

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"TraitÃ©s : {traites}"))
        self.stdout.write(f"DÃ©jÃ  importÃ©s (ignorÃ©s) : {ignores}")
        if erreurs:
            self.stderr.write(self.style.ERROR(f"Erreurs : {erreurs} â€” dÃ©tails dans {LOG_ERREURS}"))
