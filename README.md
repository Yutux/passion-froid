# PassionFroid DAM Django

Cette base convertit la maquette HTML initiale en projet Django.

## Lancer le projet

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

## Tags IA BLIP

La page `/import/` peut maintenant generer des tags IA pour chaque image de la liste via le modele Hugging Face `Salesforce/blip-image-captioning-base`.

Variables d'environnement optionnelles :

```powershell
HUGGINGFACE_API_TOKEN=...
HUGGINGFACE_BLIP_MODEL=Salesforce/blip-image-captioning-base
HUGGINGFACE_API_TIMEOUT=45
```

Le token Hugging Face doit etre un token `fine-grained` avec la permission `Make calls to Inference Providers`.

Pour regenerer les tags visuels BLIP sur les assets deja presents :

```powershell
python manage.py regenerate_ai_tags --only-fallback
```

## Pages disponibles

- `/connexion/`
- `/recherche/`
- `/import/`
- `/admin/`
- `/django-admin/`

Les anciennes URLs `01_login.html`, `02_search.html`, `03_upload.html` et `04_admin.html` sont redirigées vers les nouvelles routes Django.
