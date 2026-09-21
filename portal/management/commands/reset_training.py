from pathlib import Path
from datetime import datetime
import sqlite3
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from portal.models import MediaAsset, TagCorrection, TagFeedback, AnalysisJob
from portal.firebase_outbox import enqueue_document
from portal.firebase_sync import _asset_payload


class Command(BaseCommand):
    help = 'Sauvegarder puis retirer les validations et réinitialiser la mémoire active pour un nouvel entraînement.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, **options):
        if not options['apply']:
            self.stdout.write(f'{MediaAsset.objects.count()} médias à remettre en attente. Utiliser --apply pour exécuter.')
            return
        if AnalysisJob.objects.filter(status='RUNNING',lease_until__gt=timezone.now()).exists():
            raise CommandError('Arrêtez le worker et attendez la fin de son analyse avant la remise à zéro.')
        folder=Path(settings.BASE_DIR)/'backups'
        folder.mkdir(exist_ok=True)
        backup=folder/('training-before-reset-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'.sqlite3')
        with sqlite3.connect(settings.DATABASES['default']['NAME']) as source, sqlite3.connect(backup) as destination:
            source.backup(destination)
        now=timezone.now()
        with transaction.atomic():
            for item in TagFeedback.objects.filter(active=True):
                enqueue_document('tag_feedback',str(item.pk),{'active':False,'resetAt':now,'mediaId':item.asset.public_id})
            for item in TagCorrection.objects.filter(active=True):
                enqueue_document('training_validations',str(item.pk),{'active':False,'resetAt':now,'mediaId':item.asset.public_id})
            TagFeedback.objects.filter(active=True).update(active=False)
            TagCorrection.objects.filter(active=True).update(active=False)
            count=MediaAsset.objects.update(tags_validated=False,tags_validated_at=None,tags_validated_by='',
                gold_title='',gold_description='',gold_tags=[],gold_categories=[],gold_feedback=[],
                ai_title='',ai_caption='',ai_tags=[],ai_categories=[],ai_objects=[],ai_people=[],
                ai_logos=[],ai_ocr=[],ai_context=[],ai_places=[],ai_colors=[],ai_concepts=[],ai_visual_types=[],
                ai_confidence={},ai_analysis={},ai_embedding=[],search_embedding_hash='',search_embedding_model='',
                ai_tag_source='',ai_analyzed_at=None,media_status='UPLOADED',statut='en_attente',
                pipeline_complet=False,url_gold='',validation_notes='',modifie_le=now)
            for asset in MediaAsset.objects.all().iterator():
                asset.couche_actuelle='silver' if asset.url_silver else 'bronze'
                asset.save(update_fields=['couche_actuelle'])
                if asset.type_fichier=='image':
                    AnalysisJob.objects.update_or_create(asset=asset,defaults={'status':'PENDING','attempts':0,'next_run':now,'lease_until':None,'error':''})
                payload=_asset_payload(asset)
                document_id=asset.firebase_document_id or asset.public_id.replace('/','_')
                enqueue_document(settings.FIREBASE_MEDIA_COLLECTION,document_id,payload)
                enqueue_document('media',document_id,payload)
        self.stdout.write(f'Sauvegarde : {backup}')
        self.stdout.write(f'{count} médias remis en attente. Recherche vide. Mémoire précédente archivée ; nouvelle session active.')
