from django.core.management.base import BaseCommand
from portal.ai_worker import run_worker, discover_missing, process_one
from portal.firebase_outbox import flush_outbox


class Command(BaseCommand):
    help = 'Analyser en continu les images avec les modèles distants et synchroniser la mémoire Firebase.'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true')
        parser.add_argument('--poll', type=int, default=10)

    def handle(self, *args, **options):
        if options['once']:
            discover_missing()
            process_one()
            flush_outbox()
            return
        self.stdout.write('Worker IA distant actif. Arrêt : Ctrl+C.')
        try:
            run_worker(poll=max(3,options['poll']))
        except KeyboardInterrupt:
            self.stdout.write('Worker arrêté.')
