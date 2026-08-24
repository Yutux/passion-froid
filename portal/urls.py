from django.urls import path
from . import views

app_name = 'portal'

urlpatterns = [
    # ── Pages de la maquette ───────────────────────────────────
    path('', views.redirect_to, {'target_name': 'portal:login'}, name='home'),
    path('connexion/',  views.page,        {'template_name': '01_login.html'},  name='login'),
    path('recherche/',  views.search_view, {'template_name': '02_search.html'}, name='search'),
    path('import/',     views.upload_view,                                       name='upload'),
    path('admin/',      views.page,        {'template_name': '04_admin.html'},  name='admin_dashboard'),

    # ── Redirections legacy ────────────────────────────────────
    path('index.html',      views.redirect_to, {'target_name': 'portal:login'},           name='legacy_index'),
    path('01_login.html',   views.redirect_to, {'target_name': 'portal:login'},           name='legacy_login'),
    path('02_search.html',  views.redirect_to, {'target_name': 'portal:search'},          name='legacy_search'),
    path('03_upload.html',  views.redirect_to, {'target_name': 'portal:upload'},          name='legacy_upload'),
    path('04_admin.html',   views.redirect_to, {'target_name': 'portal:admin_dashboard'}, name='legacy_admin_dashboard'),

    # ── API Cloudinary Medallion ───────────────────────────────
    path('api/cloudinary/setup/',                views.api_setup_folders,  name='api_setup'),
    path('api/cloudinary/assets/',               views.api_list_assets,    name='api_assets_cloud'),
    path('api/cloudinary/compare/<str:public_id>/', views.api_compare_asset, name='api_compare'),
    path('api/assets/',                          views.api_assets_db,      name='api_assets_db'),
    path('api/assets/generate-tags/',            views.api_generate_tags,  name='api_generate_tags'),
    path('api/assets/<str:public_id>/',          views.api_asset_detail,   name='api_asset_detail'),
]
