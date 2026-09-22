import os
import subprocess
import sys
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = (
        "Lance le flux complet PassionFroid: scraping images/videos, puis import "
        "Cloudinary Medallion avec dedoublonnage MD5."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--skip-scrape",
            action="store_true",
            help="Importer uniquement les fichiers deja recuperes localement.",
        )
        parser.add_argument(
            "--skip-ai",
            action="store_true",
            help="Ne pas generer les tags IA pendant l'import.",
        )

    def handle(self, *args, **options):
        scraper = Path(settings.BASE_DIR) / "Scraperpassionfroid.py"

        missing_cloudinary = [
            name for name in ("CLOUDINARY_CLOUD_NAME", "CLOUDINARY_API_KEY", "CLOUDINARY_API_SECRET")
            if not getattr(settings, name, "")
        ]
        if missing_cloudinary:
            raise CommandError(
                "Configuration Cloudinary manquante: "
                + ", ".join(missing_cloudinary)
                + ". Ajoute ces variables dans .env avant la synchronisation."
            )

        if not options["skip_scrape"]:
            if not scraper.exists():
                raise CommandError(f"Scraper introuvable: {scraper}")

            self.stdout.write(self.style.WARNING("Recuperation images/videos PassionFroid..."))
            try:
                env = os.environ.copy()
                env["PYTHONIOENCODING"] = "utf-8"
                subprocess.run(
                    [sys.executable, str(scraper)],
                    cwd=str(settings.BASE_DIR),
                    env=env,
                    check=True,
                )
            except subprocess.CalledProcessError as exc:
                raise CommandError(f"Le scraper PassionFroid a echoue: {exc}") from exc

        self.stdout.write(self.style.WARNING("Import Cloudinary bronze/silver/gold..."))
        import_args = []
        if options["skip_ai"]:
            import_args.append("--skip-ai")
        call_command("import_scraped_media", *import_args)
        self.stdout.write(self.style.SUCCESS("Flux PassionFroid termine."))
