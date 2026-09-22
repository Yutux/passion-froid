from django.core.management.base import BaseCommand
from portal.semantic_search import published_assets, index_asset


class Command(BaseCommand):
    help = 'Indexer les descriptions et tags validés avec multilingual-e5 pour la recherche par sens.'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=50)

    def handle(self, *args, **options):
        updated = failed = 0
        for asset in published_assets().order_by('pk')[:max(1, options['limit'])]:
            try:
                updated += int(index_asset(asset))
            except Exception:
                failed += 1
                self.stderr.write(f'{asset.public_id}: indexation indisponible.')
                if failed >= 3:
                    break
        self.stdout.write(f'Indexés : {updated}. Erreurs : {failed}.')
