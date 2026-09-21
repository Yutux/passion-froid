from django.urls import path
from . import views

app_name = 'portal'

urlpatterns = [
    path('api/learning/status/', views.api_learning_status, name='api_learning_status'),
    path('api/assets/<path:public_id>/tag-feedback/', views.api_tag_feedback, name='api_tag_feedback'),
    path('api/search/', views.api_semantic_search, name='api_semantic_search'),
    path('admin/apprentissage/', views.admin_dashboard_view, {'section': 'learning'}, name='ai_learning'),
    path('admin/tags/', views.admin_dashboard_view, {'section': 'tags'}, name='tags'),
    path('admin/medias/', views.admin_dashboard_view, {'section': 'assets'}, name='admin_assets'),
    path('admin/archives/', views.admin_dashboard_view, {'section': 'archives'}, name='archives'),
    path('api/tags/', views.api_tags, name='api_tags'),
    path('api/tags/<int:tag_id>/', views.api_tags, name='api_tag'),

    # ── Pages de la maquette ───────────────────────────────────
    path('', views.redirect_to, {'target_name': 'portal:login'}, name='home'),
    path('connexion/',  views.login_view,                                      name='login'),
    path('inscription/', views.signup_view,                                     name='signup'),
    path('deconnexion/', views.logout_view,                                    name='logout'),
    path('recherche/',  views.search_view, {'template_name': '02_search.html'}, name='search'),
    path('import/',     views.upload_view,                                       name='upload'),
    path('admin/',      views.admin_dashboard_view,                             name='admin_dashboard'),

    # ── Redirections legacy ────────────────────────────────────
    path('index.html',      views.redirect_to, {'target_name': 'portal:login'},           name='legacy_index'),
    path('01_login.html',   views.redirect_to, {'target_name': 'portal:login'},           name='legacy_login'),
    path('02_search.html',  views.redirect_to, {'target_name': 'portal:search'},          name='legacy_search'),
    path('03_upload.html',  views.redirect_to, {'target_name': 'portal:upload'},          name='legacy_upload'),
    path('04_admin.html',   views.redirect_to, {'target_name': 'portal:admin_dashboard'}, name='legacy_admin_dashboard'),

    # ── API Cloudinary Medallion ───────────────────────────────
    path('api/cloudinary/setup/',                views.api_setup_folders,  name='api_setup'),
    path('api/passionfroid/sync/',               views.api_run_passionfroid_sync, name='api_passionfroid_sync'),
    path('api/passionfroid/sync/status/',        views.api_passionfroid_sync_status, name='api_passionfroid_sync_status'),
    path('api/cloudinary/assets/',               views.api_list_assets,    name='api_assets_cloud'),
    path('api/cloudinary/compare/<str:public_id>/', views.api_compare_asset, name='api_compare'),
    path('api/assets/',                          views.api_assets_db,      name='api_assets_db'),
    path('api/auth/firebase-login/',             views.api_firebase_login, name='api_firebase_login'),
    path('api/auth/firebase-signup/',            views.api_firebase_signup, name='api_firebase_signup'),
    path('api/search-feedback/',                 views.api_search_feedback, name='api_search_feedback'),
    path('api/assets/generate-tags/',            views.api_generate_tags,  name='api_generate_tags'),
    path('api/assets/duplicates/',               views.api_duplicate_assets, name='api_duplicate_assets'),
    path('api/assets/duplicates/delete/',        views.api_delete_duplicates, name='api_delete_duplicates'),
    path('api/assets/save-draft/',               views.api_save_asset_draft, name='api_save_asset_draft'),
    path('api/assets/<str:public_id>/validate-tags/', views.api_validate_asset_tags, name='api_validate_asset_tags'),
    path('api/speech-to-text/',                  views.api_speech_to_text, name='api_speech_to_text'),
    path('api/assets/<str:public_id>/',          views.api_asset_detail,   name='api_asset_detail'),
]
