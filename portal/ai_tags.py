import json
import re
import unicodedata
from dataclasses import dataclass
from urllib.parse import urlparse

from django.conf import settings


DEFAULT_MODEL_ID = "Salesforce/blip-image-captioning-base"
DEFAULT_TIMEOUT = 45

STOPWORDS = {
    "a", "an", "and", "au", "aux", "avec", "background", "black", "close",
    "de", "des", "dish", "du", "en", "et", "food", "for", "fresh", "from",
    "image", "in", "is", "isolated", "la", "le", "les", "meal", "of", "on",
    "photo", "plate", "queue", "queues", "sur", "table", "the", "to", "up",
    "une", "un", "white", "with", "petits", "grammages", "packshot", "product",
    "products", "egalim", "passionfroid",
}

TOKEN_TAG_MAP = {
    "appetizer": "Entree",
    "avocado": "Avocat",
    "asc": "ASC",
    "beef": "Boeuf",
    "beetroot": "Betterave",
    "bio": "Bio",
    "broccoli": "Brocoli",
    "bread": "Pain",
    "burger": "Burger",
    "cake": "Gateau",
    "carrot": "Carotte",
    "chocolate": "Chocolat",
    "cheddar": "Cheddar",
    "cheese": "Fromage",
    "chicken": "Poulet",
    "chips": "Chips",
    "corn": "Mais",
    "cocktail": "Cocktail",
    "cod": "Cabillaud",
    "cookie": "Biscuit",
    "crepe": "Crepe",
    "crevette": "Crevettes",
    "crevettes": "Crevettes",
    "cream": "Creme",
    "cucumber": "Concombre",
    "dessert": "Dessert",
    "drink": "Boisson",
    "egg": "Oeuf",
    "emmental": "Emmental",
    "fries": "Frites",
    "fish": "Poisson",
    "flan": "Flan",
    "fromage": "Fromage",
    "frozen": "Surgele",
    "goat": "Chevre",
    "gratin": "Gratin",
    "green": "Vert",
    "ham": "Jambon",
    "ice": "Glace",
    "lemon": "Citron",
    "legume": "Legumes",
    "legumes": "Legumes",
    "lettuce": "Salade",
    "mango": "Mangue",
    "meat": "Viande",
    "milk": "Lait",
    "msc": "MSC",
    "omelette": "Omelette",
    "organic": "Bio",
    "pain": "Pain",
    "pastry": "Patisserie",
    "pasta": "Pates",
    "pepper": "Poivron",
    "poisson": "Poisson",
    "pistache": "Pistache",
    "pistachio": "Pistache",
    "pizza": "Pizza",
    "pork": "Porc",
    "potato": "Pomme de terre",
    "prawn": "Crevettes",
    "prawns": "Crevettes",
    "rice": "Riz",
    "salad": "Salade",
    "salmon": "Saumon",
    "sandwich": "Sandwich",
    "sausage": "Saucisson",
    "seafood": "Fruits de mer",
    "shrimp": "Crevettes",
    "soup": "Soupe",
    "starter": "Entree",
    "sweet": "Sucre",
    "tomato": "Tomate",
    "turkey": "Dinde",
    "veau": "Veau",
    "veal": "Veau",
    "viande": "Viande",
    "vegetable": "Legumes",
    "vegetables": "Legumes",
    "volaille": "Volaille",
}

PHRASE_TAG_MAP = {
    "fruits de mer": "Fruits de mer",
    "goat cheese": "Chevre",
    "green vegetables": "Legumes",
    "ice cream": "Glace",
    "sea food": "Fruits de mer",
    "smoked salmon": "Saumon",
}

ACRONYM_TAGS = {"asc": "ASC", "bio": "Bio", "igp": "IGP", "msc": "MSC", "vbf": "VBF", "vpf": "VPF"}


class TaggingError(Exception):
    """Raised when Hugging Face tagging fails."""


@dataclass
class TaggingResult:
    caption: str
    tags: list[str]
    source: str


def generate_ai_metadata_for_asset(asset, allow_fallback: bool = True) -> TaggingResult:
    if asset.type_fichier != "image":
        raise TaggingError("Seules les images peuvent etre analysees.")

    fallback = build_metadata_fallback_for_asset(asset)
    token = getattr(settings, "HUGGINGFACE_API_TOKEN", "")
    if not token and allow_fallback and fallback.tags:
        return fallback

    try:
        asset = _ensure_vision_ready_asset(asset)
        image_url = asset.url_gold or asset.url_silver or asset.url_bronze or asset.url_image_source
        if not image_url:
            raise TaggingError("Aucune URL image exploitable n'est disponible pour cet asset.")
        caption = _generate_caption(image_url)
        tags = build_tags_for_asset(asset, caption)
        return TaggingResult(
            caption=caption,
            tags=tags,
            source=f"huggingface:{_get_model_id()}",
        )
    except TaggingError:
        if allow_fallback and fallback.tags:
            return fallback
        raise


def build_metadata_fallback_for_asset(asset) -> TaggingResult:
    metadata_text = " ".join(
        value for value in [
            getattr(asset, "categorie", "") or "",
            getattr(asset, "nom_produit", "") or "",
            getattr(asset, "nom_fichier", "") or "",
        ] if value
    )
    tags = _extract_tags_from_text(metadata_text)

    for original in [getattr(asset, "categorie", "") or "", getattr(asset, "nom_produit", "") or ""]:
        if original and not _looks_like_noise_text(original):
            tags.extend(_extract_acronyms(original))

    if not tags:
        category = (getattr(asset, "categorie", "") or "").strip()
        if category and not _looks_like_noise_text(category):
            tags.append(_pretty_tag(category))

    tags = _dedupe_tags(tags, max_tags=6)
    if not tags:
        tags = ["Image"]
    caption = ""
    return TaggingResult(
        caption=caption,
        tags=tags,
        source="metadata-fallback",
    )


def build_tags_for_asset(asset, caption: str, max_tags: int = 6) -> list[str]:
    tags = []

    if caption and _is_informative_caption(caption):
        tags.extend(_extract_tags_from_text(caption))

    for original in [getattr(asset, "nom_produit", "") or "", getattr(asset, "categorie", "") or ""]:
        if original and not _looks_like_noise_text(original):
            tags.extend(_extract_acronyms(original))

    if len(tags) < max_tags:
        category = (getattr(asset, "categorie", "") or "").strip()
        if category and not _looks_like_noise_text(category):
            tags.append(_pretty_tag(category))

    if len(tags) < max_tags:
        product_name = (getattr(asset, "nom_produit", "") or "").strip()
        if product_name and not _looks_like_noise_text(product_name):
            tags.extend(_extract_tags_from_text(product_name))

    return _dedupe_tags(tags, max_tags=max_tags)


def _extract_tags_from_text(text: str) -> list[str]:
    normalized = _normalize_text(text)
    if not normalized:
        return []

    tags = []
    for phrase, tag in PHRASE_TAG_MAP.items():
        if phrase in normalized:
            tags.append(tag)

    for token in re.findall(r"[a-z0-9-]+", normalized):
        if _is_noise_token(token):
            continue
        mapped = TOKEN_TAG_MAP.get(token)
        if mapped:
            tags.append(mapped)
            continue
        pretty = _pretty_tag(token)
        if pretty:
            tags.append(pretty)

    return tags


def _dedupe_tags(tags: list[str], max_tags: int = 6) -> list[str]:
    deduped = []
    seen = set()
    for tag in tags:
        cleaned = (tag or "").strip()
        if not cleaned:
            continue
        key = _normalize_text(cleaned)
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(cleaned)
        if len(deduped) >= max_tags:
            break
    return deduped


def _ensure_vision_ready_asset(asset):
    candidate_urls = [
        getattr(asset, "url_gold", "") or "",
        getattr(asset, "url_silver", "") or "",
        getattr(asset, "url_bronze", "") or "",
        getattr(asset, "url_image_source", "") or "",
    ]
    current_url = next((url for url in candidate_urls if url), "")
    if not current_url:
        return asset

    if _is_cloudinary_url(current_url):
        return asset

    source_url = getattr(asset, "url_image_source", "") or current_url
    if not source_url:
        return asset

    try:
        from .cloudinary_medallion import configure_cloudinary, run_medallion_pipeline

        configure_cloudinary()
        result = run_medallion_pipeline(
            source_url,
            asset.public_id,
            gold_width=settings.CLOUDINARY_GOLD_WIDTH,
            gold_quality=settings.CLOUDINARY_GOLD_QUALITY,
        )

        bronze_info = result["layers"]["bronze"]
        gold_info = result["layers"]["gold"]
        asset.url_bronze = result["urls"]["bronze"]
        asset.url_silver = result["urls"]["silver"]
        asset.url_gold = result["urls"]["gold"]
        asset.format = bronze_info.get("format", "") or asset.format
        asset.width = bronze_info.get("width") or asset.width
        asset.height = bronze_info.get("height") or asset.height
        asset.taille_bronze = bronze_info.get("bytes") or asset.taille_bronze
        asset.taille_gold = gold_info.get("bytes") or asset.taille_gold
        asset.couche_actuelle = "gold"
        asset.pipeline_complet = True
        asset.save(
            update_fields=[
                "url_bronze",
                "url_silver",
                "url_gold",
                "format",
                "width",
                "height",
                "taille_bronze",
                "taille_gold",
                "couche_actuelle",
                "pipeline_complet",
                "modifie_le",
            ]
        )
    except Exception as exc:
        raise TaggingError(f"Impossible de preparer une copie Cloudinary pour l'analyse: {exc}") from exc

    return asset


def _generate_caption(image_input: str) -> str:
    from huggingface_hub import InferenceClient

    token = getattr(settings, "HUGGINGFACE_API_TOKEN", "")
    if not token:
        raise TaggingError("HUGGINGFACE_API_TOKEN manquant pour l'analyse visuelle.")

    try:
        client = InferenceClient(
            provider="hf-inference",
            api_key=token,
            timeout=_get_timeout(),
        )
        output = client.image_to_text(image_input, model=_get_model_id())
    except Exception as exc:
        message = _parse_error_message(str(exc)) or str(exc)
        raise TaggingError(message) from exc

    if isinstance(output, str):
        caption = output
    elif hasattr(output, "generated_text"):
        caption = output.generated_text
    elif isinstance(output, dict):
        caption = output.get("generated_text", "")
    else:
        caption = str(output)

    caption = (caption or "").strip()
    if not caption:
        raise TaggingError("La reponse Hugging Face ne contient pas de description exploitable.")
    return caption


def _parse_error_message(body: str) -> str | None:
    if not body:
        return None
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        if "api-inference.huggingface.co" in body and "no longer supported" in body:
            return "L'ancien endpoint Hugging Face n'est plus supporte."
        return body.strip() or None
    if isinstance(payload, dict):
        if payload.get("error"):
            return str(payload["error"])
        if payload.get("estimated_time"):
            return f"Le modele est en cours de chargement ({payload['estimated_time']}s estimees)."
    return None


def _extract_acronyms(value: str) -> list[str]:
    tags = []
    for token in re.findall(r"\b[A-Z]{2,4}\b", value):
        mapped = ACRONYM_TAGS.get(token.lower(), token)
        tags.append(mapped)
    return tags


def _pretty_tag(value: str) -> str:
    cleaned = _normalize_text(value).replace("-", " ").strip()
    if not cleaned:
        return ""
    if _looks_like_noise_text(cleaned):
        return ""
    if cleaned in ACRONYM_TAGS:
        return ACRONYM_TAGS[cleaned]
    return " ".join(part.capitalize() for part in cleaned.split())


def _normalize_text(value: str) -> str:
    without_accents = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9\s-]", " ", without_accents.lower()).strip()


def _is_informative_caption(value: str) -> bool:
    normalized = _normalize_text(value)
    if len(normalized.split()) < 2:
        return False
    return not _looks_like_noise_text(normalized)


def _looks_like_noise_text(value: str) -> bool:
    normalized = _normalize_text(value)
    if not normalized:
        return True

    tokens = [token for token in re.findall(r"[a-z0-9-]+", normalized) if token]
    if not tokens:
        return True

    significant = [token for token in tokens if not _is_noise_token(token)]
    return not significant


def _is_noise_token(token: str) -> bool:
    if not token or token in STOPWORDS:
        return True
    if token.isdigit():
        return True
    if re.fullmatch(r"[a-f0-9]{12,}", token):
        return True
    if re.fullmatch(r"[a-z]*[0-9][a-z0-9-]{8,}", token):
        return True
    if len(token) <= 2:
        return True
    return False


def _get_model_id() -> str:
    return getattr(settings, "HUGGINGFACE_BLIP_MODEL", DEFAULT_MODEL_ID)


def _get_timeout() -> int:
    return int(getattr(settings, "HUGGINGFACE_API_TIMEOUT", DEFAULT_TIMEOUT))


def _is_cloudinary_url(value: str) -> bool:
    try:
        parsed = urlparse(value or "")
    except ValueError:
        return False
    return parsed.netloc.endswith("res.cloudinary.com")
