from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from portal.ai_tags import TaggingError
from portal.views import _store_ai_tags
from portal.models import MediaAsset


class Command(BaseCommand):
    help = "Regenerer les tags IA des images a partir de la description BLIP."

    def add_arguments(self, parser):
        parser.add_argument(
            "--public-id",
            dest="public_id",
            help="Regenerer un seul asset par public_id.",
        )
        parser.add_argument(
            "--only-fallback",
            action="store_true",
            help="Regenerer uniquement les assets dont la source actuelle est metadata-fallback.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Limiter le nombre d'assets traites.",
        )
        parser.add_argument(
            "--allow-fallback",
            action="store_true",
            help="Autoriser le fallback metadata si BLIP echoue.",
        )

    def handle(self, *args, **options):
        queryset = MediaAsset.objects.filter(type_fichier="image", tags_validated=False).exclude(media_status="ARCHIVED").order_by("id")

        if options["public_id"]:
            queryset = queryset.filter(public_id=options["public_id"])
            if not queryset.exists():
                raise CommandError("Aucun asset trouve pour ce public_id.")

        if options["only_fallback"]:
            queryset = queryset.filter(ai_tag_source__startswith="metadata-fallback")

        if options["limit"]:
            queryset = queryset[: options["limit"]]

        processed = 0
        updated = 0
        errors = 0

        for asset in queryset:
            processed += 1
            try:
                result = _store_ai_tags(
                    asset,
                    allow_fallback=options["allow_fallback"],
                )
                updated += 1
                self.stdout.write(
                    self.style.SUCCESS(
                        f"{asset.public_id}: {', '.join(result.tags) if result.tags else '(aucun tag)'} [{result.source}]"
                    )
                )
            except TaggingError as exc:
                errors += 1
                self.stderr.write(f"{asset.public_id}: {exc}")

        self.stdout.write("")
        self.stdout.write(f"Traites : {processed}")
        self.stdout.write(self.style.SUCCESS(f"Mis a jour : {updated}"))
        if errors:
            self.stderr.write(self.style.ERROR(f"Erreurs : {errors}"))
