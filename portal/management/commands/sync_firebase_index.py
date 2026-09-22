from django.core.management.base import BaseCommand

from portal.firebase_sync import FirebaseSyncSkipped, sync_asset_to_firestore
from portal.models import MediaAsset


class Command(BaseCommand):
    help = "Synchronise les assets existants vers Firestore pour la recherche IA/Firebase."

    def add_arguments(self, parser):
        parser.add_argument(
            "--only-complete",
            action="store_true",
            help="Synchroniser uniquement les assets dont le pipeline Medallion est complet.",
        )

    def handle(self, *args, **options):
        queryset = MediaAsset.objects.all().order_by("public_id")
        if options["only_complete"]:
            queryset = queryset.filter(pipeline_complet=True)

        synced = 0
        errors = 0
        skipped = 0

        for asset in queryset:
            try:
                sync_asset_to_firestore(asset)
                synced += 1
                self.stdout.write(f"OK {asset.public_id}")
            except FirebaseSyncSkipped as exc:
                skipped += 1
                self.stdout.write(self.style.WARNING(str(exc)))
                break
            except Exception as exc:
                errors += 1
                self.stderr.write(f"ERREUR {asset.public_id}: {exc}")

        self.stdout.write(self.style.SUCCESS(f"Synchronises: {synced}"))
        if skipped:
            self.stdout.write(f"Ignores: {skipped}")
        if errors:
            self.stderr.write(self.style.ERROR(f"Erreurs: {errors}"))
