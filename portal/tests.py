import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .ai_tags import TaggingError, TaggingResult, build_tags_for_asset
from .models import MediaAsset


class PortalRoutesTests(TestCase):
    def setUp(self):
        for target, value in [('portal.views._detect_objects_for_asset', []), ('portal.views._try_sync_firebase', None), ('portal.views.push_firebase_document', None)]:
            remote = patch(target, return_value=value)
            remote.start()
            self.addCleanup(remote.stop)
        User = get_user_model()
        self.user = User.objects.create_user(username='user', password='pass')
        self.admin = User.objects.create_user(username='admin', password='pass', is_staff=True)

    def test_main_pages_are_available(self):
        response = self.client.get(reverse('portal:login'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, '01_login.html')

        pages = [
            ('portal:search', '02_search.html', self.user),
            ('portal:upload', '03_upload.html', self.admin),
            ('portal:admin_dashboard', '04_admin.html', self.admin),
        ]

        for route_name, template_name, user in pages:
            with self.subTest(route_name=route_name):
                self.client.force_login(user)
                response = self.client.get(reverse(route_name))
                self.assertEqual(response.status_code, 200)
                self.assertTemplateUsed(response, template_name)
                self.client.logout()

    def test_legacy_routes_redirect_to_named_pages(self):
        redirects = [
            ('/', reverse('portal:login')),
            ('/index.html', reverse('portal:login')),
            ('/01_login.html', reverse('portal:login')),
            ('/02_search.html', reverse('portal:search')),
            ('/03_upload.html', reverse('portal:upload')),
            ('/04_admin.html', reverse('portal:admin_dashboard')),
        ]

        for source, target in redirects:
            with self.subTest(source=source):
                response = self.client.get(source)
                self.assertRedirects(response, target, fetch_redirect_response=False)

    def test_generate_tags_api_updates_image_assets(self):
        asset = MediaAsset.objects.create(
            public_id='asset-crevettes',
            nom_fichier='crevettes.jpg',
            nom_produit='Queues de crevettes MSC',
            categorie='Poisson',
            url_image_source='https://example.com/crevettes.jpg',
            type_fichier='image',
            statut='en_cours',
        )

        self.client.force_login(self.admin)
        with patch(
            'portal.views.generate_ai_metadata_for_asset',
            return_value=TaggingResult(
                caption='a plate of shrimp',
                tags=['Poisson', 'MSC', 'Crevettes'],
                source='huggingface:Salesforce/blip-image-captioning-base',
            ),
        ):
            response = self.client.post(
                reverse('portal:api_generate_tags'),
                data=json.dumps({'mode': 'missing'}),
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['updated'], 1)
        self.assertEqual(payload['errors'], 0)

        asset.refresh_from_db()
        self.assertEqual(asset.ai_tags[:3], ['poisson', 'MSC', 'crevettes'])
        self.assertIn('produit de la mer', asset.ai_tags)
        self.assertIn('fruits de mer', asset.ai_tags)
        self.assertEqual(asset.ai_caption, 'a plate of shrimp')
        self.assertTrue(asset.ai_analyzed_at)

    def test_asset_detail_api_returns_ai_tags(self):
        asset = MediaAsset.objects.create(
            public_id='asset-detail',
            nom_fichier='detail.jpg',
            nom_produit='Pave de saumon MSC',
            categorie='Poisson',
            url_image_source='https://example.com/detail.jpg',
            type_fichier='image',
            statut='termine',
            tags_validated=True,
            media_status='APPROVED',
            pipeline_complet=True,
            ai_tags=['Poisson', 'MSC', 'Saumon'],
            ai_caption='salmon on a plate',
            ai_tag_source='metadata-fallback',
        )

        self.client.force_login(self.user)
        response = self.client.get(reverse('portal:api_asset_detail', args=[asset.public_id]))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['public_id'], asset.public_id)
        self.assertEqual(payload['ai_tags'], ['Poisson', 'MSC', 'Saumon'])
        self.assertEqual(payload['ai_caption'], 'salmon on a plate')


class AITagRulesTests(TestCase):
    def setUp(self):
        head = patch('requests.head')
        head.start().return_value.headers = {'Content-Type':'image/jpeg'}
        self.addCleanup(head.stop)
        specialist = patch('portal.ai_tags._remote_image_specialists', return_value={})
        specialist.start()
        self.addCleanup(specialist.stop)
        # Caption tests exercise BLIP independently of the remote vision provider.
        vision = patch('portal.ai_tags._generate_french_structured_analysis', return_value=None)
        vision.start()
        self.addCleanup(vision.stop)

    def test_build_tags_for_asset_uses_metadata_and_caption(self):
        asset = MediaAsset(
            nom_produit='Queues de crevettes MSC',
            categorie='Poisson',
        )

        tags = build_tags_for_asset(asset, 'a plate of shrimp')

        self.assertIn('Poisson', tags)
        self.assertIn('MSC', tags)
        self.assertIn('Crevettes', tags)

    def test_build_tags_for_asset_ignores_hash_like_metadata_when_caption_present(self):
        asset = MediaAsset(
            nom_produit='b24e571ae34e9abce4ea1e590d5b7da2',
            categorie='Petits Grammages',
        )

        tags = build_tags_for_asset(asset, 'a plate of shrimp with lemon')

        self.assertIn('Crevettes', tags)
        self.assertIn('Citron', tags)
        self.assertNotIn('B24e571ae34e9abce4ea1e590d5b7da2', tags)
        self.assertNotIn('Petits', tags)

    @patch('portal.ai_tags.settings.HUGGINGFACE_API_TOKEN', '')
    def test_generate_ai_metadata_falls_back_to_metadata_when_token_missing(self):
        from .ai_tags import generate_ai_metadata_for_asset

        asset = MediaAsset(
            nom_produit='Queues de crevettes MSC',
            categorie='Poisson',
            url_image_source='https://example.com/crevettes.jpg',
            type_fichier='image',
        )

        result = generate_ai_metadata_for_asset(asset)

        self.assertEqual(result.source, 'metadata-fallback')
        self.assertIn('Poisson', result.tags)
        self.assertIn('MSC', result.tags)
        self.assertIn('Crevettes', result.tags)

    @patch('portal.ai_tags.settings.HUGGINGFACE_API_TOKEN', '')
    def test_generate_ai_metadata_uses_generic_image_tag_when_no_metadata(self):
        from .ai_tags import generate_ai_metadata_for_asset

        asset = MediaAsset(
            public_id='webimage_123',
            url_image_source='https://example.com/webimage.jpg',
            type_fichier='image',
        )

        result = generate_ai_metadata_for_asset(asset)

        self.assertEqual(result.source, 'metadata-fallback')
        self.assertEqual(result.tags, ['Image'])

    @patch('portal.ai_tags._generate_caption', side_effect=TaggingError('network down'))
    @patch('portal.ai_tags.settings.HUGGINGFACE_API_TOKEN', 'hf_test_token')
    def test_generate_ai_metadata_can_require_visual_analysis(self, _caption):
        from .ai_tags import generate_ai_metadata_for_asset

        asset = MediaAsset(
            nom_produit='Queues de crevettes MSC',
            categorie='Poisson',
            url_image_source='https://example.com/crevettes.jpg',
            type_fichier='image',
        )

        with self.assertRaises(TaggingError):
            generate_ai_metadata_for_asset(asset, allow_fallback=False)

    @patch('portal.ai_tags._generate_caption', return_value='a plate of shrimp with lemon')
    @patch('portal.cloudinary_medallion.run_medallion_pipeline')
    @patch('portal.cloudinary_medallion.configure_cloudinary')
    @patch('portal.ai_tags.settings.HUGGINGFACE_API_TOKEN', 'hf_test_token')
    def test_generate_ai_metadata_mirrors_external_asset_to_cloudinary(
        self,
        _configure,
        mock_pipeline,
        _caption,
    ):
        from .ai_tags import generate_ai_metadata_for_asset

        mock_pipeline.return_value = {
            'urls': {
                'bronze': 'https://res.cloudinary.com/demo/image/upload/v1/bronze/test.jpg',
                'silver': 'https://res.cloudinary.com/demo/image/upload/v1/silver/test.jpg',
                'gold': 'https://res.cloudinary.com/demo/image/upload/v1/gold/test.jpg',
            },
            'layers': {
                'bronze': {'format': 'jpg', 'width': 1200, 'height': 800, 'bytes': 1000},
                'silver': {'format': 'jpg', 'width': 1200, 'height': 800, 'bytes': 900},
                'gold': {'format': 'jpg', 'width': 1200, 'height': 800, 'bytes': 800},
            },
        }

        asset = MediaAsset.objects.create(
            public_id='external-asset',
            url_image_source='https://example.com/source.jpg',
            type_fichier='image',
            statut='en_cours',
        )

        result = generate_ai_metadata_for_asset(asset, allow_fallback=False)

        asset.refresh_from_db()
        self.assertTrue(asset.url_gold.startswith('https://res.cloudinary.com/'))
        self.assertEqual(result.source, 'huggingface:Salesforce/blip-image-captioning-large')
        self.assertIn('Crevettes', result.tags)
        self.assertIn('Citron', result.tags)


class TagLearningTests(TestCase):
    def setUp(self):
        index = patch('portal.views.start_index_asset')
        index.start()
        self.addCleanup(index.stop)
        self.admin = get_user_model().objects.create_user(username='reviewer', password='pass', is_staff=True)
        self.client.force_login(self.admin)
        self.asset = MediaAsset.objects.create(public_id='learning', reference='R1', ai_tags=['poulet', 'assiette'], ai_tag_source='metadata-fallback:auto')

    def test_tag_crud_normalization_and_disabled_suggestions(self):
        from .models import Tag
        from .tag_learning import canonical_tags
        url = reverse('portal:api_tags')
        response = self.client.post(url, json.dumps({'name': 'Légumes', 'category': 'Aliment'}), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        tag = Tag.objects.get()
        self.assertEqual(self.client.post(url, json.dumps({'name': 'LEGUMES'}), content_type='application/json').status_code, 409)
        self.assertEqual(canonical_tags(['LEGUMES', 'légumes']), ['Légumes'])
        detail = reverse('portal:api_tag', args=[tag.pk])
        self.assertEqual(self.client.patch(detail, json.dumps({'name': 'Légume'}), content_type='application/json').status_code, 200)
        self.assertEqual(self.client.delete(detail).status_code, 200)
        self.assertEqual(canonical_tags(['legume', 'assiette']), ['assiette'])

    def test_correction_removes_errors_and_is_product_scoped(self):
        from .models import TagCorrection
        from .tag_learning import apply_corrections
        TagCorrection.objects.create(asset=self.asset, reference='R1', before=['poulet', 'assiette'], after=['dinde', 'assiette'], author='reviewer')
        sibling = MediaAsset.objects.create(public_id='sibling', reference='R1')
        other = MediaAsset.objects.create(public_id='other', reference='R2')
        self.assertEqual(set(apply_corrections(sibling, ['poulet', 'assiette'])[0]), {'dinde', 'assiette'})
        self.assertEqual(apply_corrections(other, ['poulet'])[0], ['poulet'])
        TagCorrection.objects.create(asset=self.asset, reference='R1', before=['dinde'], after=['canard'], author='reviewer')
        self.assertIn('canard', apply_corrections(sibling, ['dinde'])[0])
        self.assertNotIn('dinde', apply_corrections(sibling, ['dinde'])[0])

    @patch('portal.views._detect_objects_for_asset', return_value=[])
    @patch('portal.views._try_sync_firebase')
    @patch('portal.views.push_firebase_document')
    @patch('portal.views.generate_ai_metadata_for_asset', return_value=TaggingResult(caption='turkey', tags=['dinde'], source='vision:test'))
    def test_fallback_auto_is_analyzed_and_approved_is_protected(self, generate, *_):
        url = reverse('portal:api_generate_tags')
        response = self.client.post(url, json.dumps({'mode': 'fallback', 'force_visual': True}), content_type='application/json')
        self.assertEqual(response.json()['updated'], 1)
        generate.assert_called_once()
        self.asset.refresh_from_db()
        self.asset.tags_validated = True
        self.asset.media_status = 'APPROVED'
        self.asset.save()
        response = self.client.post(url, json.dumps({'mode': 'all'}), content_type='application/json')
        self.assertEqual(response.json()['updated'], 0)
        generate.assert_called_once()

    @patch('portal.views._sync_gold_metadata_to_cloudinary')
    @patch('portal.views._try_sync_firebase')
    @patch('portal.views.write_firebase_document')
    @patch('portal.views.push_firebase_document')
    def test_draft_then_validation_remembers_original_prediction(self, *_):
        from .models import TagCorrection
        self.client.post(reverse('portal:api_save_asset_draft'), json.dumps({'public_id': self.asset.public_id, 'title': 'Dinde', 'tags': ['dinde']}), content_type='application/json')
        self.assertEqual(TagCorrection.objects.count(), 0)
        response = self.client.post(reverse('portal:api_validate_asset_tags', args=[self.asset.public_id]), json.dumps({'title': 'Dinde', 'tags': ['dinde']}), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        correction = TagCorrection.objects.get()
        self.assertEqual(correction.before, ['poulet', 'assiette'])
        self.assertEqual(correction.after, ['dinde'])

    def test_pages_have_direct_links_and_do_not_start_analysis(self):
        with patch('portal.views._start_ai_analysis_background') as start:
            for route in ('admin_dashboard', 'ai_learning', 'tags', 'admin_assets', 'archives'):
                response = self.client.get(reverse('portal:'+route))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, reverse('portal:ai_learning'))
            start.assert_not_called()

    @patch('portal.views.push_firebase_document')
    def test_approved_media_can_be_reopened_for_correction(self, _push):
        self.asset.tags_validated = True
        self.asset.media_status = 'APPROVED'
        self.asset.gold_tags = ['poulet']
        self.asset.ai_analysis = {'original_tags': ['boeuf']}
        self.asset.save()
        response = self.client.post(reverse('portal:api_save_asset_draft'), json.dumps({'public_id': self.asset.public_id, 'title': 'Dinde', 'tags': ['dinde']}), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.asset.refresh_from_db()
        self.assertFalse(self.asset.tags_validated)
        self.assertEqual(self.asset.media_status, 'ADMIN_REVIEW')
        self.assertEqual(self.asset.ai_analysis['original_tags'], ['poulet'])

    def test_non_admin_cannot_change_tags(self):
        user = get_user_model().objects.create_user(username='reader', password='pass')
        self.client.force_login(user)
        response = self.client.post(reverse('portal:api_tags'), json.dumps({'name': 'secret'}), content_type='application/json')
        self.assertEqual(response.status_code, 302)

    def test_tag_api_rejects_invalid_payload(self):
        response = self.client.post(reverse('portal:api_tags'), '[]', content_type='application/json')
        self.assertEqual(response.status_code, 400)

    def test_image_script_payload_is_escaped(self):
        self.asset.ai_title = '</script><script>alert(1)</script>'
        self.asset.save()
        response = self.client.get(reverse('portal:ai_learning'))
        self.assertNotContains(response, '</script><script>alert(1)</script>')


class VisionProviderTests(TestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.clear()

    @patch('portal.ai_tags.settings.HUGGINGFACE_API_TOKEN', 'test-token')
    @patch('portal.vision_engine.chat')
    def test_saturated_provider_is_reported_without_false_visual_success(self, chat):
        import requests
        from .ai_tags import _generate_french_structured_analysis
        error = requests.HTTPError('capacity')
        error.response = type('Response', (), {'status_code': 503})()
        chat.side_effect = error
        with self.assertRaisesRegex(TaggingError, 'saturé'):
            _generate_french_structured_analysis('https://example.com/image.jpg')

    @patch('portal.ai_tags.settings.HUGGINGFACE_API_TOKEN', 'test-token')
    @patch('portal.vision_engine.chat')
    def test_structured_image_tags_are_decoded(self, chat):
        from .ai_tags import _generate_french_structured_analysis
        chat.return_value = json.dumps({'title':'Une assiette', 'description':'Une assiette de légumes', 'tags':['Légumes', 'légumes', 'Assiette']})
        result = _generate_french_structured_analysis('https://example.com/image.jpg')
        self.assertEqual(result['tags'], ['Légumes', 'Assiette'])


class AutomaticWorkflowTests(TestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.admin = get_user_model().objects.create_user(username='workflow-admin', password='pass', is_staff=True)
        self.user = get_user_model().objects.create_user(username='workflow-user', password='pass')
        self.asset = MediaAsset.objects.create(public_id='workflow-image', ai_tags=['poulet'], reference='R1', url_silver='https://example.com/image.jpg')
        self.client.force_login(self.admin)

    def test_discovery_and_exclusive_job_lease(self):
        from .ai_worker import discover_missing, claim_job
        self.asset.ai_tags=[]
        self.asset.save()
        discover_missing()
        first=claim_job()
        self.assertEqual(first.asset_id,self.asset.pk)
        self.assertIsNone(claim_job())

    @patch('portal.views._store_ai_tags', side_effect=TaggingError('service indisponible'))
    @patch('portal.image_memory.ensure_fingerprint')
    def test_worker_preserves_retry_state(self, *_):
        from .ai_worker import enqueue_asset, process_one
        from .models import AnalysisJob
        from django.utils import timezone
        enqueue_asset(self.asset)
        self.assertTrue(process_one())
        job=AnalysisJob.objects.get(asset=self.asset)
        self.assertEqual(job.status,'RETRY')
        self.assertGreater(job.next_run,timezone.now())
        self.asset.refresh_from_db()
        self.assertFalse(self.asset.tags_validated)

    def test_feedback_replacement_is_atomic_and_queued_for_firebase(self):
        from .models import TagFeedback, FirebaseOutbox
        response=self.client.post(reverse('portal:api_tag_feedback',args=[self.asset.public_id]),json.dumps({'action':'replace','tag':'poulet','replacement':'dinde','reason':'Identification incorrecte : une dinde'}),content_type='application/json')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['tags'],['dinde'])
        self.assertEqual(TagFeedback.objects.count(),2)
        self.assertEqual(FirebaseOutbox.objects.count(),2)
        from .tag_learning import apply_corrections
        sibling=MediaAsset.objects.create(public_id='related',reference='R1')
        self.assertEqual(apply_corrections(sibling,['poulet'])[0],['dinde'])

    def test_feedback_requires_reason_and_admin(self):
        url=reverse('portal:api_tag_feedback',args=[self.asset.public_id])
        payload=json.dumps({'action':'remove','tag':'poulet','reason':''})
        self.assertEqual(self.client.post(url,payload,content_type='application/json').status_code,400)
        self.client.force_login(self.user)
        self.assertEqual(self.client.post(url,payload,content_type='application/json').status_code,302)

    @patch('portal.firebase_outbox.write_firebase_document', side_effect=RuntimeError('offline'))
    def test_firebase_failure_keeps_feedback_durable(self, _write):
        from .firebase_outbox import enqueue_document,flush_outbox
        item=enqueue_document('tag_feedback','42',{'tag':'dinde'})
        flush_outbox()
        item.refresh_from_db()
        self.assertIsNone(item.sent_at)
        self.assertEqual(item.attempts,1)
        self.assertEqual(item.payload['tag'],'dinde')

    def test_nonadmin_sees_search_without_admin_navigation(self):
        self.client.force_login(self.user)
        response=self.client.get(reverse('portal:search'))
        self.assertEqual(response.status_code,200)
        self.assertNotContains(response,reverse('portal:admin_dashboard'))
        self.assertNotContains(response,reverse('portal:upload'))
        self.assertEqual(self.client.get(reverse('portal:admin_dashboard')).status_code,302)

    def test_real_logout_invalidates_django_session(self):
        self.assertEqual(self.client.get(reverse('portal:logout')).status_code,405)
        response=self.client.post(reverse('portal:logout'))
        self.assertEqual(response.status_code,200)
        self.assertNotIn('_auth_user_id',self.client.session)
        self.assertEqual(self.client.get(reverse('portal:search')).status_code,302)

    @patch('portal.views._ensure_firebase_admin')
    @patch('firebase_admin.auth.verify_id_token', side_effect=ValueError('invalid signature'))
    def test_unverified_firebase_token_is_never_accepted(self, verify, _init):
        from .views import _verify_firebase_token
        with self.assertRaises(ValueError):
            _verify_firebase_token('unsigned.payload.signature')
        verify.assert_called_once_with('unsigned.payload.signature',check_revoked=True)

    def test_search_excludes_unvalidated_and_rejected_ai_tags(self):
        from .semantic_search import search
        self.assertEqual(search('poulet',semantic=False)['count'],0)
        self.asset.tags_validated=True
        self.asset.media_status='APPROVED'
        self.asset.pipeline_complet=True
        self.asset.gold_title='Dinde'
        self.asset.gold_tags=['dinde']
        self.asset.save()
        self.assertEqual(search('poulet',semantic=False)['count'],0)
        self.assertEqual(search('dinde',semantic=False)['count'],1)

    @patch('portal.semantic_search.embed',side_effect=RuntimeError('network'))
    def test_semantic_service_failure_retains_lexical_results(self, _embed):
        from .semantic_search import search,document_hash
        from django.conf import settings
        self.asset.tags_validated=True
        self.asset.media_status='APPROVED'
        self.asset.pipeline_complet=True
        self.asset.gold_title='Dinde'
        self.asset.gold_tags=['dinde']
        self.asset.ai_embedding=[.6,.8]
        self.asset.search_embedding_model=settings.HUGGINGFACE_SEARCH_MODEL
        self.asset.search_embedding_hash=document_hash(self.asset)
        self.asset.save()
        result=search('dinde')
        self.assertEqual(result['count'],1)
        self.assertEqual(result['mode'],'lexical')
        self.assertIn('temporairement',result['notice'])

    def test_old_training_session_does_not_affect_new_predictions(self):
        from .models import TagCorrection,TagFeedback
        from .tag_learning import apply_corrections
        TagCorrection.objects.create(asset=self.asset,before=['poulet'],after=['dinde'],author='admin',active=False)
        TagFeedback.objects.create(asset=self.asset,action='remove',tag='poulet',reason='ancien essai',author='admin',active=False)
        self.assertEqual(apply_corrections(self.asset,['poulet'])[0],['poulet'])

    def test_near_duplicates_need_hash_color_and_aspect_agreement(self):
        from .image_memory import is_near_duplicate
        left=MediaAsset(perceptual_hash='aaaaaaaaaaaaaaaa',color_signature=[100,110,120],width=100,height=100)
        right=MediaAsset(perceptual_hash='aaaaaaaaaaaaaaab',color_signature=[101,112,120],width=100,height=100)
        self.assertTrue(is_near_duplicate(left,right))
        right.color_signature=[230,240,250]
        self.assertFalse(is_near_duplicate(left,right))
        right.perceptual_hash='0000000000000000'
        self.assertFalse(is_near_duplicate(left,right))

    @patch('portal.cloudinary_medallion.pipeline.promote_to_gold')
    @patch('portal.cloudinary_medallion.pipeline.promote_to_silver',return_value={'url':'silver','bytes':80})
    @patch('portal.cloudinary_medallion.pipeline.upload_to_bronze',return_value={'url':'bronze','bytes':100,'resource_type':'image'})
    def test_medallion_defers_gold_until_review(self, _bronze,_silver,gold):
        from .cloudinary_medallion.pipeline import run_medallion_pipeline
        result=run_medallion_pipeline('file','public')
        self.assertEqual(result['urls'],{'bronze':'bronze','silver':'silver','gold':''})
        gold.assert_not_called()

    @patch('portal.vision_engine.chat')
    def test_model_failover_and_structured_french_facets(self, chat):
        import requests
        from .vision_engine import analyze_image
        error=requests.HTTPError('busy');error.response=type('Response',(),{'status_code':503})()
        chat.side_effect=[error,json.dumps({'language':'fr','title':'Assiette de légumes','description':'Une assiette de légumes sur une table.','tags':['légumes','assiette'],'objects':['assiette'],'colors':['green'],'visual_types':['photographie de produit']})]
        result=analyze_image('https://example.com/photo.jpg')
        self.assertEqual(result['colors'],['vert'])
        self.assertEqual(len(result['attempts']),2)
        self.assertIn('vert',result['tags'])

    @patch('portal.vision_engine.chat')
    def test_nonfrench_description_gets_translated(self, chat):
        from .vision_engine import analyze_image
        chat.side_effect=[json.dumps({'language':'en','title':'A bowl','description':'A bowl of vegetables on a table','tags':['vegetables']}),json.dumps({'language':'fr','title':'Un bol','description':'Un bol de légumes posé sur une table.','tags':['légumes','bol']})]
        result=analyze_image('https://example.com/photo.jpg')
        self.assertEqual(result['language'],'fr')
        self.assertIn('translation_model',result)

    def test_new_validation_can_override_an_older_removed_tag(self):
        from .models import TagFeedback, TagCorrection
        from .tag_learning import apply_corrections
        TagFeedback.objects.create(asset=self.asset,action='remove',tag='poulet',reason='ancienne correction',author='admin')
        TagCorrection.objects.create(asset=self.asset,before=[],after=['poulet'],author='admin')
        self.assertIn('poulet',apply_corrections(self.asset,[])[0])


    def test_unpublished_assets_are_hidden_from_regular_user_apis(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse('portal:api_assets_db')).json()['count'],0)
        response=self.client.get(reverse('portal:api_asset_detail',args=[self.asset.public_id]))
        self.assertEqual(response.status_code,404)
