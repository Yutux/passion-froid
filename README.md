# PassionFroid — Studio médias

Application Django avec un style commun pour le dashboard, l’atelier IA, le référentiel
de tags, l’import, la recherche, la connexion et l’inscription.

## Démarrer

Créer l’environnement, installer les dépendances et copier la configuration :

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.venv\Scripts\python.exe -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

Reporter la clé générée dans `DJANGO_SECRET_KEY` du fichier `.env`, puis renseigner
vos accès Cloudinary, Firebase et Hugging Face. `.env`, les comptes de service,
les bases locales et les sauvegardes sont exclus de Git. En production, définir
`DJANGO_DEBUG=false` et `DJANGO_ALLOWED_HOSTS` avec les domaines autorisés.

```powershell
.venv\Scripts\python.exe manage.py migrate
.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8001 --noreload
```

Le serveur de développement démarre automatiquement le worker IA. Il reste actif tant
que l’application tourne. En déploiement WSGI/ASGI, lancer séparément et superviser :

```powershell
python manage.py run_ai_worker
```

La file `AnalysisJob` est persistante : un redémarrage ne perd pas les tâches. Le worker
repère toutes les 30 secondes les images sans analyse ou avec des tags de métadonnées,
traite en priorité les imports récents, réserve une tâche par image et reprend les tâches
interrompues après expiration du bail. Les échecs sont retentés avec un délai croissant,
jusqu’à une heure. Les brouillons humains, médias validés et archives sont protégés.
`AI_WORKER_ENABLED=false` désactive le worker intégré au serveur de développement.

## Pages et rôles

- `/connexion/`, `/inscription/` : authentification ; les nouvelles inscriptions ont le rôle utilisateur.
- `/recherche/` : accessible aux utilisateurs connectés ; uniquement les médias validés et publiés en Gold.
- `/admin/`, `/admin/apprentissage/`, `/admin/tags/`, `/admin/medias/`, `/admin/archives/`, `/import/` : administration.
- `/deconnexion/` : POST avec CSRF ; ferme la session Django, puis la session Firebase du navigateur.

Les tokens Firebase sont vérifiés cryptographiquement, même en mode DEBUG. Les droits
admin proviennent des droits locaux ou des custom claims vérifiés, jamais du formulaire.
Les pages privées ne sont pas mises en cache HTTP.

## Architecture Medallion

1. **Bronze** : original conservé dans Cloudinary.
2. **Silver** : normalisation, orientation, dimensions et suppression des métadonnées inutiles.
   Les modèles distants analysent cette version ; les propositions restent privées.
3. **Gold** : promotion et publication après validation humaine, avec les métadonnées corrigées.

Les anciennes ressources Gold peuvent rester stockées, mais ne sont pas exposées par
la recherche après une remise à zéro. Si une URL Cloudinary est devenue inaccessible,
le worker reconstruit Bronze/Silver depuis `fichier_source` lorsque l’original existe.
Sinon, l’atelier demande de réimporter l’image ; aucun tag n’est inventé.

Configuration : `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY`, `CLOUDINARY_API_SECRET`.

## IA distante et français

Aucun modèle neuronal n’est chargé sur l’ordinateur exécutant Django.

- **Salesforce/blip-image-captioning-large** : description d’image distante. Sa fiche indique
  l’absence d’Inference Provider public ; renseigner `HUGGINGFACE_BLIP_ENDPOINT` avec un
  endpoint Hugging Face dédié qui sert ce modèle. Le système signale son indisponibilité
  et utilise les modèles visuels ci-dessous en attendant.
- **facebook/detr-resnet-50** : détection d’objets distante avec seuil de score. Un endpoint
  dédié peut être fourni via `HUGGINGFACE_OBJECT_ENDPOINT`.
- **Qwen2.5-VL-72B / OVHcloud**, **Qwen3-VL-30B / Novita**, **Gemma 3 27B / DeepInfra**,
  **Qwen3-VL-8B / Featherless** : description et facettes en français, avec repli automatique.
  La disponibilité et les crédits restent ceux des fournisseurs Hugging Face.
- **Qwen3-8B** : réparation linguistique des réponses non françaises.
- **multilingual-e5-large** : recherche sémantique sur les descriptions et tags validés.
- **Whisper large v3** : dictée de recherche lorsque le navigateur ne propose pas la reconnaissance vocale.

Variables principales :

```dotenv
HUGGINGFACE_API_TOKEN=...
HUGGINGFACE_BLIP_ENDPOINT=
HUGGINGFACE_OBJECT_ENDPOINT=
HUGGINGFACE_VISION_INSTRUCT_MODELS=Qwen/Qwen2.5-VL-72B-Instruct:ovhcloud,Qwen/Qwen3-VL-30B-A3B-Instruct:novita,google/gemma-3-27b-it:deepinfra,Qwen/Qwen3-VL-8B-Instruct:featherless-ai
HUGGINGFACE_TRANSLATION_MODEL=Qwen/Qwen3-8B:nscale
HUGGINGFACE_SEARCH_MODEL=intfloat/multilingual-e5-large
HUGGINGFACE_SEARCH_ENABLED=true
```

Les modèles doivent retourner un JSON vérifié : titre, description, tags, objets,
personnes/activités visibles, types de lieux, couleurs, concepts, type de visuel, texte
lisible et logos. Les catégories absentes restent vides. Le modèle principal vérifie les
indices BLIP/DETR ; les détections auxiliaires ne sont pas ajoutées aveuglément.

Sources : [BLIP](https://huggingface.co/Salesforce/blip-image-captioning-large),
[DETR](https://huggingface.co/facebook/detr-resnet-50),
[Qwen3-VL](https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct),
[Gemma 3](https://huggingface.co/google/gemma-3-27b-it),
[API de routage](https://huggingface.co/docs/inference-providers/tasks/chat-completion).

## Mémoire supervisée et Firebase

Chaque ajout, suppression ou remplacement de tag demande une raison. `TagFeedback`
conserve l’action, le tag, l’auteur, la raison et l’image. Une validation conserve aussi
l’ensemble avant/après dans `TagCorrection`. La décision la plus récente prévaut.

La mémoire s’applique au même média, à la même référence produit, et aux quasi-doublons
visuels. Ces derniers sont reconnus par une empreinte perceptuelle, la couleur moyenne
et le rapport largeur/hauteur ; les images uniformes sont exclues. Ce traitement léger
est une empreinte d’image, pas une inférence IA locale. Des images de scènes différentes
ne sont pas assimilées automatiquement sur la seule présence d’un objet commun.

Les événements sont synchronisés vers `tag_feedback` et `training_validations` via une
file `FirebaseOutbox` persistante et prioritaire. En cas de panne réseau, ils restent en
attente puis sont renvoyés avec des identifiants stables. L’atelier affiche les tâches et
synchronisations en attente. La mémoire est supervisée ; les poids des modèles ne sont
pas réentraînés automatiquement.

Configuration Firebase : `FIREBASE_PROJECT_ID`, `FIREBASE_CREDENTIALS_PATH` et,
optionnellement, `FIREBASE_DATABASE_URL` pour le repli Realtime Database.

## Recherche et remise à zéro

La recherche combine mots-clés français, filtres et proximité sémantique. Les vecteurs
sont calculés après validation. Si l’inférence est indisponible, les mots-clés restent
fonctionnels et l’interface l’indique. Réindexation possible :

```powershell
python manage.py index_semantic_search --limit 100
```

Pour repartir de zéro, arrêter le worker puis lancer :

```powershell
python manage.py reset_training --apply
```

Cette commande sauvegarde SQLite dans `backups/`, dépublie tous les médias, vide leurs
anciennes propositions et archive les anciennes corrections (sans supprimer l’audit).
La recherche reste vide jusqu’aux nouvelles validations. Les originaux sont conservés.

## Vérification

```powershell
python manage.py test portal
python manage.py check
python manage.py makemigrations --check --dry-run
node --check portal/static/portal/studio.js
node --check portal/static/portal/catalogue.js
node --check portal/static/portal/upload.js
```

`python -m artifacts.check_ui` vérifie les pages sur ordinateur/mobile, les erreurs
JavaScript, la sélection de fichiers et l’absence de recouvrement du formulaire par
une image portrait très haute. Les captures de ce test utilisent une image synthétique.
