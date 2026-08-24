import json
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from .ai_tags import TaggingError, TaggingResult, build_tags_for_asset
from .models import MediaAsset


class PortalRoutesTests(TestCase):
    def test_main_pages_are_available(self):
        pages = [
            ('portal:login', '01_login.html'),
            ('portal:search', '02_search.html'),
            ('portal:upload', '03_upload.html'),
            ('portal:admin_dashboard', '04_admin.html'),
        ]

        for route_name, template_name in pages:
            with self.subTest(route_name=route_name):
                response = self.client.get(reverse(route_name))
                self.assertEqual(response.status_code, 200)
                self.assertTemplateUsed(response, template_name)

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
                self.assertRedirects(response, target)

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
        self.assertEqual(asset.ai_tags, ['Poisson', 'MSC', 'Crevettes'])
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
            statut='en_cours',
            ai_tags=['Poisson', 'MSC', 'Saumon'],
            ai_caption='salmon on a plate',
            ai_tag_source='metadata-fallback',
        )

        response = self.client.get(reverse('portal:api_asset_detail', args=[asset.public_id]))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['public_id'], asset.public_id)
        self.assertEqual(payload['ai_tags'], ['Poisson', 'MSC', 'Saumon'])
        self.assertEqual(payload['ai_caption'], 'salmon on a plate')


class AITagRulesTests(TestCase):
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
        self.assertEqual(result.source, 'huggingface:Salesforce/blip-image-captioning-base')
        self.assertIn('Crevettes', result.tags)
        self.assertIn('Citron', result.tags)
