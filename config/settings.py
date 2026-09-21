"""
Django settings for config project.
"""

from pathlib import Path
import os
from dotenv import load_dotenv
from django.core.management.utils import get_random_secret_key

# Charger les variables d'environnement depuis .env
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

DEBUG = os.environ.get('DJANGO_DEBUG', 'true').lower() == 'true'
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', '')
if not SECRET_KEY:
    if not DEBUG:
        raise RuntimeError('DJANGO_SECRET_KEY doit être configurée en production.')
    SECRET_KEY = get_random_secret_key()

ALLOWED_HOSTS = [host.strip() for host in os.environ.get(
    'DJANGO_ALLOWED_HOSTS', '127.0.0.1,localhost,testserver'
).split(',') if host.strip()]

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'portal.apps.PortalConfig',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'portal.middleware.PrivatePageCacheMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'fr-fr'
TIME_ZONE = 'Europe/Paris'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
LOGIN_URL = 'portal:login'
LOGIN_REDIRECT_URL = 'portal:search'
LOGOUT_REDIRECT_URL = 'portal:login'

# ── Cloudinary Medallion ────────────────────────────────────────
CLOUDINARY_CLOUD_NAME = os.environ.get('CLOUDINARY_CLOUD_NAME', '')
CLOUDINARY_API_KEY    = os.environ.get('CLOUDINARY_API_KEY', '')
CLOUDINARY_API_SECRET = os.environ.get('CLOUDINARY_API_SECRET', '')

# Tailles Gold par défaut
CLOUDINARY_GOLD_WIDTH   = 1200
CLOUDINARY_GOLD_QUALITY = 85
CLOUDINARY_SILVER_MAX_SIZE = 800
PASSIONFROID_AUTO_SYNC_ON_STARTUP = os.environ.get('PASSIONFROID_AUTO_SYNC_ON_STARTUP', 'true').lower() == 'true'
PASSIONFROID_AUTO_SYNC_SKIP_AI = os.environ.get('PASSIONFROID_AUTO_SYNC_SKIP_AI', 'false').lower() == 'true'
# Hugging Face IA tags
HUGGINGFACE_API_TOKEN = os.environ.get('HUGGINGFACE_API_TOKEN', '')
HUGGINGFACE_BLIP_MODEL = os.environ.get('HUGGINGFACE_BLIP_MODEL', 'Salesforce/blip-image-captioning-large')
HUGGINGFACE_VISION_INSTRUCT_MODEL = os.environ.get('HUGGINGFACE_VISION_INSTRUCT_MODEL', 'Qwen/Qwen2.5-VL-7B-Instruct')
HUGGINGFACE_VISION_INSTRUCT_MODELS = os.environ.get('HUGGINGFACE_VISION_INSTRUCT_MODELS', '')
HUGGINGFACE_SPEECH_MODEL = os.environ.get('HUGGINGFACE_SPEECH_MODEL', 'openai/whisper-large-v3')
HUGGINGFACE_EMBEDDING_MODEL = os.environ.get('HUGGINGFACE_EMBEDDING_MODEL', 'sentence-transformers/clip-ViT-B-32-multilingual-v1')
HUGGINGFACE_OCR_MODEL = os.environ.get('HUGGINGFACE_OCR_MODEL', 'microsoft/trocr-base-printed')
HUGGINGFACE_OBJECT_DETECTION_MODEL = os.environ.get('HUGGINGFACE_OBJECT_DETECTION_MODEL', 'facebook/detr-resnet-50')
HUGGINGFACE_VIDEO_MODEL = os.environ.get('HUGGINGFACE_VIDEO_MODEL', 'MCG-NJU/videomae-base')
HUGGINGFACE_API_TIMEOUT = int(os.environ.get('HUGGINGFACE_API_TIMEOUT', '45'))

# Firebase / Firestore (optionnel en local)
FIREBASE_PROJECT_ID = os.environ.get('FIREBASE_PROJECT_ID', '')
FIREBASE_MEDIA_COLLECTION = os.environ.get('FIREBASE_MEDIA_COLLECTION', 'media_assets')
FIREBASE_API_KEY = os.environ.get('FIREBASE_API_KEY', '')
FIREBASE_AUTH_DOMAIN = os.environ.get('FIREBASE_AUTH_DOMAIN', '')
FIREBASE_STORAGE_BUCKET = os.environ.get('FIREBASE_STORAGE_BUCKET', '')
FIREBASE_MESSAGING_SENDER_ID = os.environ.get('FIREBASE_MESSAGING_SENDER_ID', '')
FIREBASE_APP_ID = os.environ.get('FIREBASE_APP_ID', '')
FIREBASE_MEASUREMENT_ID = os.environ.get('FIREBASE_MEASUREMENT_ID', '')
FIREBASE_DATABASE_URL = os.environ.get('FIREBASE_DATABASE_URL', '')
FIREBASE_CREDENTIALS_PATH = os.environ.get('FIREBASE_CREDENTIALS_PATH', '')
if FIREBASE_CREDENTIALS_PATH and not Path(FIREBASE_CREDENTIALS_PATH).is_absolute():
    FIREBASE_CREDENTIALS_PATH = str(BASE_DIR / FIREBASE_CREDENTIALS_PATH)

# Select a provider that actually serves the configured vision-language model.
HUGGINGFACE_VISION_PROVIDER = os.environ.get("HUGGINGFACE_VISION_PROVIDER", "auto")

# French descriptions and multilingual semantic retrieval (separate from image CLIP).
HUGGINGFACE_SEARCH_MODEL = os.environ.get('HUGGINGFACE_SEARCH_MODEL', 'intfloat/multilingual-e5-large')
HUGGINGFACE_TRANSLATION_MODEL = os.environ.get('HUGGINGFACE_TRANSLATION_MODEL', 'Qwen/Qwen3-8B:nscale')
HUGGINGFACE_SEARCH_ENABLED = os.environ.get('HUGGINGFACE_SEARCH_ENABLED', 'true').lower() == 'true'

AI_WORKER_ENABLED = os.environ.get('AI_WORKER_ENABLED', 'true').lower() == 'true'
HUGGINGFACE_BLIP_ENDPOINT = os.environ.get('HUGGINGFACE_BLIP_ENDPOINT', '')
HUGGINGFACE_OBJECT_ENDPOINT = os.environ.get('HUGGINGFACE_OBJECT_ENDPOINT', '')
