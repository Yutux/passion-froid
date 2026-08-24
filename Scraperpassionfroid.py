"""
PassionFroid — Scraper complet
Récupère TOUS les produits de toutes les catégories
et génère un CSV prêt pour Cloudinary.
+ Télécharge les vidéos de la chaîne YouTube et du site.

Installation :
    pip install requests beautifulsoup4 yt-dlp playwright
    playwright install chromium

Usage :
    python scrape_passionfroid.py
"""

import requests
from bs4 import BeautifulSoup
import csv
import json
import re
import time
import os
import hashlib
import urllib.parse
from datetime import datetime
from pathlib import Path

try:
    import yt_dlp
    YT_DLP_AVAILABLE = True
except ImportError:
    YT_DLP_AVAILABLE = False
    print("[INFO] yt-dlp non installé — pip install yt-dlp")

try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    print("[INFO] Playwright non installé — pip install playwright && playwright install chromium")

# ══════════════════════════════════════════════════════════════
# SYSTÈME DE CACHE — évite de retélécharger ce qui existe déjà
# ══════════════════════════════════════════════════════════════

CACHE_FILE = "passionfroid_cache.json"   # fichier qui mémorise les URLs déjà téléchargées


def charger_cache() -> dict:
    """Charge le cache depuis le fichier JSON. Retourne un dict vide si absent."""
    if Path(CACHE_FILE).exists():
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                cache = json.load(f)
            print(f"  📋  Cache chargé : {len(cache)} fichier(s) déjà téléchargé(s)")
            return cache
        except Exception:
            return {}
    return {}


def sauvegarder_cache(cache: dict):
    """Sauvegarde le cache sur disque."""
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def url_en_id(url: str) -> str:
    """Transforme une URL en identifiant unique (MD5 court)."""
    return hashlib.md5(url.encode()).hexdigest()


def deja_telecharge(url: str, cache: dict) -> bool:
    """
    Retourne True si l'URL a déjà été téléchargée ET que le fichier existe encore.
    Si le fichier a été supprimé manuellement, on remet à False dans le cache.
    """
    cle = url_en_id(url)
    if cle not in cache:
        return False
    chemin = Path(cache[cle]["chemin"])
    if not chemin.exists():
        # Fichier supprimé → on efface l'entrée du cache
        del cache[cle]
        return False
    return True


def marquer_telecharge(url: str, chemin_local: str, cache: dict, type_media: str = "image"):
    """Enregistre un téléchargement réussi dans le cache."""
    cle = url_en_id(url)
    cache[cle] = {
        "url":        url,
        "chemin":     str(chemin_local),
        "type":       type_media,
        "date":       datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    sauvegarder_cache(cache)


# Cache global partagé par toutes les fonctions
CACHE = charger_cache()

BASE_URL = "https://www.passionfroid.fr"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://www.passionfroid.fr/",
}

# ── Toutes les catégories à scraper ───────────────────────────
CATEGORIES = [
    # (slug_url, label)
    ("nouveautes",                              "Nouveautés"),
    ("cocktail",                                "Cocktail"),
    ("cocktail/pret-emploi-sale",               "Cocktail — Prêt à l'emploi salé"),
    ("cocktail/pret-creer-sale",                "Cocktail — Prêt à créer salé"),
    ("cocktail/pret-emploi-sucre",              "Cocktail — Prêt à l'emploi sucré"),
    ("cocktail/pret-creer-sucre",               "Cocktail — Prêt à créer sucré"),
    ("charcuterie",                             "Charcuterie"),
    ("charcuterie/jambon-et-epaule",            "Charcuterie — Jambon et épaule"),
    ("charcuterie/pate-et-terrine",             "Charcuterie — Pâté et terrine"),
    ("charcuterie/produit-sale-fume-et-seche",  "Charcuterie — Produit salé fumé séché"),
    ("charcuterie/saucisson",                   "Charcuterie — Saucisson"),
    ("charcuterie/saucisse-andouillette-boudin","Charcuterie — Saucisse andouillette boudin"),
    ("charcuterie/aide-culinaire-charcutiere",  "Charcuterie — Aide culinaire"),
    ("charcuterie/autres-specialites-charcutieres","Charcuterie — Autres spécialités"),
    ("charcuterie/charcuterie-tranchee",        "Charcuterie — Tranchée"),
    ("charcuterie/charcuterie-volaille",        "Charcuterie — Volaille"),
    ("entree",                                  "Entrée"),
    ("entree/foie-gras",                        "Entrée — Foie gras"),
    ("entree/saumon-fume",                      "Entrée — Saumon fumé"),
    ("entree/salade-antipasti-et-tartare",      "Entrée — Salade antipasti tartare"),
    ("entree/terrine",                          "Entrée — Terrine"),
    ("entree/entree-mer",                       "Entrée — De la mer"),
    ("entree/snack-chaud",                      "Entrée — Snack chaud"),
    ("entree/feuillete",                        "Entrée — Feuilleté"),
    ("entree/quiche-et-tarte",                  "Entrée — Quiche et tarte"),
    ("entree/pizza",                            "Entrée — Pizza"),
    ("entree/crepe-et-galette",                 "Entrée — Crêpe et galette"),
    ("entree/entree-ethnique",                  "Entrée — Ethnique"),
    ("crustace-et-mollusque",                   "Crustacé et mollusque"),
    ("crustace-et-mollusque/noix-saint-jacques","Crustacé — Noix de saint-jacques"),
    ("crustace-et-mollusque/homard-et-langouste","Crustacé — Homard et langouste"),
    ("crustace-et-mollusque/crevette-et-ecrevisse","Crustacé — Crevette et écrevisse"),
    ("crustace-et-mollusque/cephalopode",       "Crustacé — Céphalopode"),
    ("crustace-et-mollusque/autre-crustace-mollusque-et-coquillage","Crustacé — Autres"),
    ("poisson",                                 "Poisson"),
    ("poisson/poisson-et-filet-entier",         "Poisson — Entier et filet"),
    ("poisson/decoupe-calibree",                "Poisson — Découpe calibrée"),
    ("poisson/portion-nature-enrobe-et-pane",   "Poisson — Portion nature enrobé pané"),
    ("poisson/brochette",                       "Poisson — Brochette"),
    ("poisson/recette-marine",                  "Poisson — Recette marine"),
    ("viande",                                  "Viande"),
    ("viande/boeuf",                            "Viande — Bœuf"),
    ("viande/veau",                             "Viande — Veau"),
    ("viande/porc",                             "Viande — Porc"),
    ("viande/agneau-mouton",                    "Viande — Agneau mouton"),
    ("viande/abats",                            "Viande — Abats"),
    ("viande/autres-especes-viande",            "Viande — Autres espèces"),
    ("viande/viande-cuite",                     "Viande — Cuite"),
    ("viande/viande-elaboree",                  "Viande — Élaborée"),
    ("volaille",                                "Volaille"),
    ("volaille/poulet",                         "Volaille — Poulet"),
    ("volaille/dinde-dindonneau",               "Volaille — Dinde"),
    ("volaille/lapin",                          "Volaille — Lapin"),
    ("volaille/canard-canette-oie",             "Volaille — Canard canette oie"),
    ("volaille/coq-poule-coquelet",             "Volaille — Coq poule coquelet"),
    ("volaille/pintade",                        "Volaille — Pintade"),
    ("volaille/caille-pigeon",                  "Volaille — Caille pigeon"),
    ("volaille/autres-especes-volaille",        "Volaille — Autres espèces"),
    ("volaille/produit-confitfume",             "Volaille — Confit fumé"),
    ("volaille/volaille-elaboree",              "Volaille — Élaborée"),
    ("plat-cuisine",                            "Plat cuisiné"),
    ("plat-cuisine/plat-cuisine-individuel",    "Plat cuisiné — Individuel"),
    ("plat-cuisine/plat-cuisine-multiportion",  "Plat cuisiné — Multiportion"),
    ("plat-cuisine/plat-complet",               "Plat cuisiné — Complet"),
    ("plat-cuisine/pate-farcie",                "Plat cuisiné — Pâte farcie"),
    ("plat-cuisine/legume-farci",               "Plat cuisiné — Légume farci"),
    ("plat-cuisine/panes",                      "Plat cuisiné — Panés"),
    ("plat-cuisine/quenelle",                   "Plat cuisiné — Quenelle"),
    ("plat-cuisine/sauce",                      "Plat cuisiné — Sauce"),
    ("plat-cuisine/alternatives-vegetales",     "Plat cuisiné — Alternatives végétales"),
    ("garniture",                               "Garniture"),
    ("garniture/monolegume",                    "Garniture — Monolégume"),
    ("garniture/melange-legume",                "Garniture — Mélange de légume"),
    ("garniture/poelee",                        "Garniture — Poêlée"),
    ("garniture/garniture-elaboree",            "Garniture — Élaborée"),
    ("garniture/puree",                         "Garniture — Purée"),
    ("garniture/frite-et-specialite-pomme-terre","Garniture — Frite et pomme de terre"),
    ("garniture/pate-nature",                   "Garniture — Pâte nature"),
    ("garniture/champignon",                    "Garniture — Champignon"),
    ("garniture/herbe-et-condiment",            "Garniture — Herbe et condiment"),
    ("base-pate",                               "À base de pâte"),
    ("base-pate/base-pate",                     "À base de pâte — Base"),
    ("base-pate/viennoiserie",                  "À base de pâte — Viennoiserie"),
    ("base-pate/pain",                          "À base de pâte — Pain"),
    ("base-pate/sandwich",                      "À base de pâte — Sandwich"),
    ("produit-laitier",                         "Produit laitier"),
    ("produit-laitier/fromage-coupe",           "Produit laitier — Fromage à la coupe"),
    ("produit-laitier/fromage-portion",         "Produit laitier — Fromage portion"),
    ("produit-laitier/fromage-ingredient",      "Produit laitier — Fromage ingrédient"),
    ("produit-laitier/fromage-blanc-et-specialite-laitiere","Produit laitier — Fromage blanc"),
    ("produit-laitier/yaourt",                  "Produit laitier — Yaourt"),
    ("produit-laitier/dessert-individuel-lacte-fruite","Produit laitier — Dessert individuel"),
    ("produit-laitier/dessert-multiportion-lacte","Produit laitier — Dessert multiportion"),
    ("produit-laitier/corps-gras-et-creme",     "Produit laitier — Corps gras et crème"),
    ("produit-laitier/oeufs-et-ovoproduits",    "Produit laitier — Œufs et ovoproduits"),
    ("produit-laitier/lait",                    "Produit laitier — Lait"),
    ("produit-laitier/alternatives-vegetales",  "Produit laitier — Alternatives végétales"),
    ("dessert",                                 "Dessert"),
    ("dessert/individuel-patissier",            "Dessert — Individuel pâtissier"),
    ("dessert/tartelette",                      "Dessert — Tartelette"),
    ("dessert/individuel",                      "Dessert — Individuel"),
    ("dessert/beignet",                         "Dessert — Beignet"),
    ("dessert/pate-choux",                      "Dessert — Pâte à choux"),
    ("dessert/crepe-et-gaufre",                 "Dessert — Crêpe et gaufre"),
    ("dessert/tarte-entiere",                   "Dessert — Tarte entière"),
    ("dessert/tarte-predecoupee",               "Dessert — Tarte prédécoupée"),
    ("dessert/gateau",                          "Dessert — Gâteau"),
    ("dessert/bande",                           "Dessert — Bande"),
    ("dessert/cadre",                           "Dessert — Cadre"),
    ("dessert/fruit",                           "Dessert — Fruit"),
    ("glace",                                   "Glace"),
    ("glace/glace-individuelle",                "Glace — Individuelle"),
    ("glace/specialite-glacee-partager",        "Glace — Spécialité à partager"),
    ("glace/glace-vrac",                        "Glace — Vrac"),
    ("evenements/paques",                       "Pâques"),
    ("evenements/veggie",                       "Veggie"),
    ("evenements/bio",                          "Bio"),
    ("evenements/bonengage",                    "Bon&Engagé"),
    ("evenements/100-ma-region",                "100% Ma Région"),
    ("evenements/italie",                       "Italie"),
    ("evenements/produits-egalim-et-assimiles", "EGALIM"),
    ("evenements/petits-grammages",             "Petits grammages"),
    ("evenements/bleu-blanc-coeur",             "Bleu-Blanc-Cœur"),
]

# Pages du site qui contiennent potentiellement des vidéos embarquées
PAGES_VIDEOS_SITE = [
    "https://www.passionfroid.fr/",
    "https://www.passionfroid.fr/supports",
    "https://www.passionfroid.fr/produits/nouveautes",
    "https://www.passionfroid.fr/produits/evenements/veggie",
    "https://www.passionfroid.fr/produits/evenements/bonengage",
    "https://www.passionfroid.fr/produits/evenements/bio",
]

# Chaîne YouTube officielle
YOUTUBE_CHANNEL = "https://www.youtube.com/@POMONA_PassionFroid/videos"
YOUTUBE_SHORTS = "https://www.youtube.com/@POMONA_PassionFroid/shorts"
YOUTUBE_MAX_VIDEOS = 50   # ← mettre None pour tout télécharger

DOSSIER_VIDEOS = "medias_passionfroid/videos"


# ══════════════════════════════════════════════════════════════
# PARTIE 1 — SCRAPING PRODUITS (code original de l'équipe)
# ══════════════════════════════════════════════════════════════

def get_page(url, session):
    """Récupère le HTML d'une URL avec retry."""
    for attempt in range(3):
        try:
            r = session.get(url, headers=HEADERS, timeout=20)
            if r.status_code == 200:
                return r.text
            print(f"    ⚠ HTTP {r.status_code}")
            time.sleep(2)
        except Exception as e:
            print(f"    ❌ Tentative {attempt+1}/3 : {e}")
            time.sleep(3)
    return None


def parse_products_from_html(html, categorie_label):
    """Extrait tous les produits d'une page HTML."""
    soup = BeautifulSoup(html, "html.parser")
    products = []

    selectors = [
        "li.search-item",
        "article.product-card",
        "div.product-item",
        "li[class*='product']",
        "div[class*='product']",
    ]

    cards = []
    for sel in selectors:
        cards = soup.select(sel)
        if cards:
            break

    if not cards:
        links = soup.find_all("a", href=re.compile(r"/produits/[^/]+-0\d+$"))
        for link in links:
            cards.append(link.parent)

    for card in cards:
        a = card.find("a", href=re.compile(r"/produits/"))
        if not a:
            a = card if card.name == "a" else None
        if not a:
            continue

        href = a.get("href", "")
        if not href or "/produits/" not in href:
            continue

        ref_match = re.search(r"-0*(\d{4,7})$", href)
        if not ref_match:
            continue
        reference = ref_match.group(1)

        nom = ""
        for sel in ["h2", "h3", "h4", ".product-title", ".product-name",
                    "[class*='title']", "[class*='name']", "strong"]:
            el = card.find(sel)
            if el:
                txt = el.get_text(separator=" ", strip=True)
                txt = re.sub(r"\s+", " ", txt).strip()
                if txt and len(txt) > 3 and "PassionFroid" not in txt:
                    nom = txt
                    break

        if not nom:
            img = card.find("img")
            if img:
                alt = img.get("alt", "")
                nom = alt.replace("| Grossiste alimentaire | PassionFroid", "").strip()

        if not nom:
            continue

        url_image = ""
        img = card.find("img")
        if img:
            url_image = img.get("src") or img.get("data-src") or img.get("data-lazy-src") or ""
            if url_image.startswith("//"):
                url_image = "https:" + url_image
            elif url_image.startswith("/"):
                url_image = BASE_URL + url_image

        conservation = ""
        for el in card.find_all(text=True):
            t = el.strip()
            if t in ("Frais", "Surgelé", "Ambiant", "Frais/Surgelé"):
                conservation = t
                break

        marque = ""
        for sel in [".brand", ".marque", "[class*='brand']", "[class*='marque']"]:
            el = card.find(sel)
            if el:
                marque = el.get_text(strip=True)
                break
        if not marque:
            brand_img = card.find("img", src=re.compile(r"cdn\.api\.groupe-pomona"))
            if brand_img:
                marque = brand_img.get("alt", "")

        nouveaute = bool(
            card.find(string=re.compile(r"Nouveaut", re.I)) or
            card.find(class_=re.compile(r"new|nouveau", re.I))
        )

        labels = []
        for el in card.find_all(["span", "div", "img"], class_=re.compile(r"label|certif|bio|msc", re.I)):
            t = el.get_text(strip=True) or el.get("alt", "")
            if t and len(t) < 60:
                labels.append(t)
        labels_str = " | ".join(set(labels))

        cat_slug = re.sub(r"[^a-z0-9]", "_", categorie_label.lower())
        cat_slug = re.sub(r"_+", "_", cat_slug).strip("_")
        nom_slug = re.sub(r"[^a-z0-9]", "_", nom.lower()[:40])
        nom_slug = re.sub(r"_+", "_", nom_slug).strip("_")
        public_id = f"passionfroid_{cat_slug}_{reference}_{nom_slug}"

        products.append({
            "reference":       reference,
            "nom":             nom,
            "categorie":       categorie_label,
            "conservation":    conservation,
            "nouveaute":       "Oui" if nouveaute else "Non",
            "marque":          marque,
            "labels":          labels_str,
            "url_produit":     BASE_URL + href if href.startswith("/") else href,
            "url_image":       url_image,
            "image_statut":    "déjà téléchargée" if deja_telecharge(url_image, CACHE) else "à télécharger",
            "cloudinary_public_id":    public_id,
            "cloudinary_bronze":       f"bronze/{public_id}",
            "cloudinary_silver":       f"silver/{public_id}",
            "cloudinary_gold":         f"gold/{public_id}",
            "tags_cloudinary":         f"passionfroid,{cat_slug},{conservation.lower()}",
            "scraped_at":      datetime.now().strftime("%Y-%m-%d %H:%M"),
        })

    return products


def get_total_pages(html):
    soup = BeautifulSoup(html, "html.parser")
    last_page = 1
    for a in soup.find_all("a", href=re.compile(r"page=")):
        m = re.search(r"page=(\d+)", a.get("href", ""))
        if m:
            last_page = max(last_page, int(m.group(1)))
    for el in soup.find_all(string=re.compile(r"\d+\s+produits? trouv")):
        m = re.search(r"(\d+)", el)
        if m:
            total = int(m.group(1))
            last_page = max(last_page, (total + 23) // 24)
            break
    return last_page


def scrape_all():
    session = requests.Session()
    session.headers.update(HEADERS)

    all_products = {}
    total_pages_scraped = 0
    errors = []

    print("=" * 60)
    print("  PassionFroid — Scraping complet")
    print(f"  {len(CATEGORIES)} catégories à traiter")
    print("=" * 60)

    for idx, (slug, label) in enumerate(CATEGORIES, 1):
        url_base = f"{BASE_URL}/produits/{slug}"
        print(f"\n[{idx:03d}/{len(CATEGORIES)}] {label}")
        print(f"  URL : {url_base}")

        html = get_page(url_base, session)
        if not html:
            errors.append(url_base)
            continue

        n_pages = get_total_pages(html)
        print(f"  → {n_pages} page(s) détectée(s)")

        prods = parse_products_from_html(html, label)
        for p in prods:
            all_products[p["reference"]] = p
        total_pages_scraped += 1
        print(f"  Page 1 : {len(prods)} produits — Total : {len(all_products)}")

        for page in range(2, n_pages + 1):
            url_page = f"{url_base}?page={page}"
            html = get_page(url_page, session)
            if not html:
                break
            prods = parse_products_from_html(html, label)
            new = 0
            for p in prods:
                if p["reference"] not in all_products:
                    all_products[p["reference"]] = p
                    new += 1
            total_pages_scraped += 1
            print(f"  Page {page} : {len(prods)} produits (+{new} nouveaux) — Total : {len(all_products)}")
            time.sleep(0.6)

        time.sleep(0.8)

    products = list(all_products.values())
    deja_en_cache = sum(1 for p in products if p.get("image_statut") == "déjà téléchargée")
    print(f"\n{'=' * 60}")
    print(f"  ✅ TOTAL : {len(products)} produits uniques")
    print(f"  📋 Images déjà en cache : {deja_en_cache}")
    print(f"  📥 Images à télécharger : {len(products) - deja_en_cache}")
    print(f"  📄 Pages scrapées : {total_pages_scraped}")
    print(f"  ❌ Erreurs : {len(errors)}")
    print("=" * 60)
    return products


def export_csv(products, filename="passionfroid_complet.csv"):
    fieldnames = [
        "reference", "nom", "categorie", "conservation", "nouveaute",
        "marque", "labels", "url_produit", "url_image", "image_statut",
        "cloudinary_public_id", "cloudinary_bronze", "cloudinary_silver", "cloudinary_gold",
        "tags_cloudinary", "scraped_at",
    ]
    with open(filename, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(products)
    print(f"\n💾 CSV exporté : {filename} ({len(products)} lignes)")


def export_json(products, filename="passionfroid_complet.json"):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(products, f, ensure_ascii=False, indent=2)
    print(f"💾 JSON exporté : {filename}")


# ══════════════════════════════════════════════════════════════
# PARTIE 1b — TÉLÉCHARGEMENT DES IMAGES PRODUITS
# ══════════════════════════════════════════════════════════════

DOSSIER_IMAGES = "medias_passionfroid/images"


def hash_fichier(chemin: Path) -> str:
    """Calcule le MD5 du contenu d'un fichier (détecte les vrais doublons)."""
    h = hashlib.md5()
    with open(chemin, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def supprimer_doublons(dossier: Path) -> int:
    """
    Parcourt le dossier, calcule le MD5 de chaque image,
    et supprime les fichiers dont le contenu est identique.
    Retourne le nombre de doublons supprimés.
    """
    print(f"\n🔍  Recherche de doublons dans {dossier}…")
    vus = {}        # md5 → premier fichier rencontré
    supprimes = 0

    fichiers = sorted(dossier.rglob("*"))
    fichiers = [f for f in fichiers if f.is_file()]

    for f in fichiers:
        try:
            md5 = hash_fichier(f)
            if md5 in vus:
                print(f"  🗑️   Doublon supprimé : {f.name}  (= {vus[md5].name})")
                f.unlink()
                supprimes += 1
            else:
                vus[md5] = f
        except Exception as e:
            print(f"  ⚠️   {f.name} : {e}")

    print(f"  ✅  {supprimes} doublon(s) supprimé(s), {len(vus)} image(s) unique(s) conservée(s)")
    return supprimes


def telecharger_images(products: list, dossier: str = DOSSIER_IMAGES,
                       session: requests.Session = None):
    """
    Télécharge toutes les images produits dans le dossier local.
    - Ignore les images déjà en cache (URL connue)
    - Ignore les fichiers déjà présents sur le disque (même nom)
    - Après téléchargement, supprime les doublons par contenu (MD5)
    """
    img_dir = Path(dossier)
    img_dir.mkdir(parents=True, exist_ok=True)

    if session is None:
        session = requests.Session()
        session.headers.update(HEADERS)

    total     = len(products)
    telecharge = 0
    ignore_cache  = 0
    ignore_disque = 0
    erreurs   = 0

    print(f"\n{'=' * 60}")
    print(f"  Téléchargement des images ({total} produits)")
    print("=" * 60)

    for i, prod in enumerate(products, 1):
        url = prod.get("url_image", "").strip()
        ref = prod.get("reference", "inconnu")

        if not url:
            continue

        # ── Vérification 1 : déjà dans le cache (URL connue) ──
        if deja_telecharge(url, CACHE):
            ignore_cache += 1
            continue

        # ── Nom du fichier : référence + extension ──
        ext = Path(urllib.parse.urlparse(url).path).suffix.lower() or ".jpg"
        nom = f"{ref}{ext}"
        dest = img_dir / nom

        # ── Vérification 2 : fichier déjà sur le disque ───────
        if dest.exists():
            marquer_telecharge(url, dest, CACHE, "image")
            ignore_disque += 1
            continue

        # ── Téléchargement ────────────────────────────────────
        try:
            resp = session.get(url, stream=True, timeout=20)
            resp.raise_for_status()

            with open(dest, "wb") as f:
                for chunk in resp.iter_content(8192):
                    f.write(chunk)

            marquer_telecharge(url, dest, CACHE, "image")
            telecharge += 1

            # Affichage progression toutes les 50 images
            if telecharge % 50 == 0 or i == total:
                print(f"  [{i:04d}/{total}] ✅  {telecharge} téléchargée(s) | "
                      f"⏭️  {ignore_cache + ignore_disque} ignorée(s) | "
                      f"❌ {erreurs} erreur(s)")

            time.sleep(0.3)

        except Exception as e:
            erreurs += 1
            print(f"  ❌  [{ref}] {e}")

    print(f"\n{'=' * 60}")
    print(f"  ✅  Téléchargées   : {telecharge}")
    print(f"  ⏭️   Cache (connues) : {ignore_cache}")
    print(f"  ⏭️   Disque (déjà là): {ignore_disque}")
    print(f"  ❌  Erreurs        : {erreurs}")
    print("=" * 60)

    # ── Suppression des doublons par contenu ──────────────────
    supprimer_doublons(img_dir)

    return telecharge


# ══════════════════════════════════════════════════════════════
# PARTIE 2 — SCRAPING VIDÉOS (nouveau)
# ══════════════════════════════════════════════════════════════

def collecter_liens_video_site(pages: list) -> set:
    """
    Utilise Playwright pour charger chaque page en JS et collecter
    tous les liens vers des vidéos (iframes YouTube/Vimeo, <video>,
    URLs vidéo dans les scripts).
    Retourne un ensemble d'URLs.
    """
    if not PLAYWRIGHT_AVAILABLE:
        print("  ⚠️  Playwright non disponible, vidéos site ignorées.")
        return set()

    liens = set()
    EMBED_DOMAINS = ("youtube.com", "youtu.be", "vimeo.com", "dailymotion.com")
    VIDEO_EXT = (".mp4", ".webm", ".m4v", ".ogg")

    def on_response(response):
        url = response.url
        ct  = response.headers.get("content-type", "")
        # Vidéo chargée directement via le réseau
        if "video" in ct or any(url.lower().endswith(e) for e in VIDEO_EXT):
            if not re.search(r'\.(ts|m4s)(\?|$)', url):   # ignore les segments HLS
                liens.add(url)
                print(f"    📡  Réseau vidéo : {url[:80]}")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_context(
            user_agent=HEADERS["User-Agent"],
            viewport={"width": 1920, "height": 1080},
        ).new_page()

        page.on("response", on_response)

        for url in pages:
            print(f"\n  🌐  Analyse de {url}")
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(3000)

                # Scroll complet pour tout déclencher
                h, pos = page.evaluate("document.body.scrollHeight"), 0
                while pos < h:
                    page.evaluate(f"window.scrollTo(0, {pos})")
                    page.wait_for_timeout(300)
                    pos += 800
                    h = page.evaluate("document.body.scrollHeight")

                html = page.content()
                soup = BeautifulSoup(html, "html.parser")

                # iframes YouTube / Vimeo
                for tag in soup.find_all("iframe", src=True):
                    src = tag["src"].strip()
                    if any(d in src for d in EMBED_DOMAINS):
                        full = src if src.startswith("http") else "https:" + src
                        liens.add(full)
                        print(f"    📺  iframe : {full[:80]}")

                # <video src>
                for tag in soup.find_all(["video", "source"]):
                    src = (tag.get("src") or tag.get("data-src", "")).strip()
                    if src and any(src.lower().endswith(e) for e in VIDEO_EXT):
                        full = src if src.startswith("http") else BASE_URL + src
                        liens.add(full)
                        print(f"    🎬  <video> : {full[:80]}")

                # URLs vidéo cachées dans les balises <script>
                for script in soup.find_all("script"):
                    if script.string:
                        for m in re.finditer(
                            r'https?://[^\s"\'<>]+\.(?:mp4|webm|m3u8|m4v)[^\s"\'<>]*',
                            script.string
                        ):
                            liens.add(m.group(0))
                            print(f"    🎬  Script JS : {m.group(0)[:80]}")

            except Exception as e:
                print(f"    ❌  {e}")

        browser.close()

    print(f"\n  → {len(liens)} lien(s) vidéo trouvé(s) sur le site")
    return liens


def telecharger_videos_site(liens: set, dossier: Path):
    """Télécharge les vidéos du site via yt-dlp, en sautant celles déjà téléchargées."""
    if not liens:
        print("  Aucune vidéo site à télécharger.")
        return
    if not YT_DLP_AVAILABLE:
        print("  ⚠️  yt-dlp requis — pip install yt-dlp")
        return

    dest = dossier / "site"
    dest.mkdir(parents=True, exist_ok=True)

    deja, a_telecharger = 0, 0
    for url in liens:
        if deja_telecharge(url, CACHE):
            print(f"  ⏭️   Déjà téléchargé : {url[:70]}")
            deja += 1
            continue

        a_telecharger += 1
        print(f"  ⬇️   {url[:80]}")

        # On capture le nom du fichier généré par yt-dlp
        fichiers_avant = set(dest.iterdir())
        opts = {
            "outtmpl":             str(dest / "%(title)s.%(ext)s"),
            "merge_output_format": "mp4",
            "quiet":               True,
            "no_warnings":         True,
            "ignoreerrors":        True,
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
            # Trouve le(s) nouveau(x) fichier(s) créé(s)
            nouveaux = set(dest.iterdir()) - fichiers_avant
            for f in nouveaux:
                marquer_telecharge(url, f, CACHE, "video_site")
            print(f"  ✅  OK")
        except Exception as e:
            print(f"  ❌  {e}")
        time.sleep(1)

    print(f"\n  📊  Vidéos site : {a_telecharger} téléchargée(s), {deja} ignorée(s) (déjà présente(s))")


def telecharger_chaine_youtube(dossier: Path, url: str = None, max_videos: int = 50):
    """Télécharge les vidéos de la chaîne YouTube, en sautant celles déjà téléchargées."""
    if not YT_DLP_AVAILABLE:
        print("  ⚠️  yt-dlp requis — pip install yt-dlp")
        return

    dest = dossier / "youtube"
    dest.mkdir(parents=True, exist_ok=True)
    print(f"\n  📺  Chaîne YouTube : {YOUTUBE_CHANNEL}")
    print(f"  Limite : {max_videos if max_videos else 'toutes'} vidéo(s)")

    # Récupère d'abord la liste des vidéos sans télécharger
    url = url or YOUTUBE_CHANNEL
    opts_info = {
            "quiet":        True,
            "no_warnings":  True,
            "extract_flat": "in_playlist",
            "playlistend":  max_videos,
        }

    try:
        with yt_dlp.YoutubeDL(opts_info) as ydl:
            info = ydl.extract_info(url, download=False)
        entrees = info.get("entries", []) if info else []
    except Exception as e:
            print(f"  ❌  Impossible de lister les vidéos : {e}")
            return

    deja, a_telecharger = 0, 0

    for entree in entrees:
        if not entree:
            continue
        url_video = entree.get("url") or f"https://www.youtube.com/watch?v={entree.get('id', '')}"

        if deja_telecharge(url_video, CACHE):
            print(f"  ⏭️   Déjà téléchargé : {entree.get('title', url_video)[:60]}")
            deja += 1
            continue

        a_telecharger += 1
        print(f"  ⬇️   {entree.get('title', url_video)[:70]}")

        fichiers_avant = set(dest.iterdir())
        opts_dl = {
            "outtmpl":             str(dest / "%(upload_date)s_%(title)s.%(ext)s"),
           "format": "best[height<=1080]/best",
            "merge_output_format": "mp4",
            "ignoreerrors":        True,
            "quiet":               True,
            "no_warnings":         True,
        }
        try:
            with yt_dlp.YoutubeDL(opts_dl) as ydl:
                ydl.download([url_video])
            nouveaux = set(dest.iterdir()) - fichiers_avant
            for f in nouveaux:
                marquer_telecharge(url_video, f, CACHE, "video_youtube")
            print(f"  ✅  OK")
        except Exception as e:
            print(f"  ❌  {e}")

    print(f"\n  📊  YouTube : {a_telecharger} téléchargée(s), {deja} ignorée(s) (déjà présente(s))")


def scrape_videos():
    """Lance le scraping complet des vidéos."""
    vid_dir = Path(DOSSIER_VIDEOS)
    vid_dir.mkdir(parents=True, exist_ok=True)

    print("\n" + "=" * 60)
    print("  PassionFroid — Scraping vidéos")
    print("=" * 60)

    # ── Étape 1 : vidéos embarquées sur les pages du site ─────
    print("\n📌  ÉTAPE 1 — Vidéos embarquées sur le site")
    liens = collecter_liens_video_site(PAGES_VIDEOS_SITE)
    telecharger_videos_site(liens, vid_dir)

    # ── Étape 2 : chaîne YouTube officielle ───────────────────
    print("\n📌  ÉTAPE 2 — Chaîne YouTube officielle")
    telecharger_chaine_youtube(vid_dir, url=YOUTUBE_CHANNEL, max_videos=YOUTUBE_MAX_VIDEOS)
    telecharger_chaine_youtube(vid_dir, url=YOUTUBE_SHORTS,  max_videos=YOUTUBE_MAX_VIDEOS)
    # ── Résumé ────────────────────────────────────────────────
    n_site    = len(list((vid_dir / "site").iterdir()))    if (vid_dir / "site").exists()    else 0
    n_youtube = len(list((vid_dir / "youtube").iterdir())) if (vid_dir / "youtube").exists() else 0
    print(f"\n✅  Vidéos terminées → {vid_dir.resolve()}")
    print(f"   📁 site/    : {n_site} fichier(s)")
    print(f"   📁 youtube/ : {n_youtube} fichier(s)")


# ══════════════════════════════════════════════════════════════
# MAIN — choisir ce que tu veux lancer
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":

    # ── Décommente ce que tu veux exécuter ────────────────────

    # 1. Scraper les produits + télécharger les images + CSV/JSON
    products = scrape_all()
    export_csv(products)
    export_json(products)
    telecharger_images(products)    # ← télécharge + dédoublonne automatiquement

    # 2. Scraper les vidéos (YouTube + site)
    scrape_videos()

    # 3. Tout faire d'un coup
    # products = scrape_all()
    # export_csv(products)
    # export_json(products)
    # telecharger_images(products)
    # scrape_videos()