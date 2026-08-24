import re
import unicodedata

import cloudinary
import cloudinary.api
import cloudinary.uploader


def sanitize_context_value(valeur: str, max_len: int = 200) -> str:
    """
    Nettoie une valeur avant de l'envoyer dans le context/tags Cloudinary.
    Supprime accents, emojis et caractères non-ASCII qui font planter
    l'upload avec 'Invalid encoding in context'.
    """
    valeur = unicodedata.normalize("NFKD", str(valeur))
    valeur = valeur.encode("ascii", "ignore").decode("ascii")
    valeur = re.sub(r"[^\x20-\x7E]", "", valeur)
    return valeur.strip()[:max_len]


def get_asset_info(layer: str, public_id: str) -> dict:
    """Obtenir les infos d'un asset dans une couche."""
    return cloudinary.api.resource(f"{layer}/{public_id}")


def delete_asset(layer: str, public_id: str) -> dict:
    """Supprimer un asset dans une couche spécifique."""
    return cloudinary.uploader.destroy(f"{layer}/{public_id}")


def delete_from_all_layers(public_id: str) -> dict:
    """Supprimer un asset dans les 3 couches Bronze + Silver + Gold."""
    results = {}
    for layer in ["bronze", "silver", "gold"]:
        try:
            results[layer] = cloudinary.uploader.destroy(f"{layer}/{public_id}")
        except cloudinary.exceptions.Error as e:
            results[layer] = {"error": str(e)}
    return results


def list_layer_assets(layer: str) -> list:
    """Lister tous les assets d'une couche."""
    res = cloudinary.api.resources(
        type="upload",
        prefix=f"{layer}/",
        max_results=500,
    )
    return res.get("resources", [])


def get_signed_gold_url(public_id: str, expires_in: int = 3600) -> str:
    """
    Générer une URL signée (expirable) pour un asset Gold.

    Args:
        public_id  : ID de l'asset dans gold/
        expires_in : Durée de validité en secondes (défaut 1h)
    """
    import time
    expires_at = int(time.time()) + expires_in
    return cloudinary.CloudinaryImage(f"gold/{public_id}").build_url(
        sign_url=True,
        expires_at=expires_at,
        secure=True,
    )


def compare_layers(public_id: str) -> dict:
    """Comparer les tailles et formats entre les 3 couches."""
    result = {"public_id": public_id}
    for layer in ["bronze", "silver", "gold"]:
        try:
            info = cloudinary.api.resource(f"{layer}/{public_id}")
            result[layer] = {"bytes": info["bytes"], "format": info["format"]}
        except cloudinary.exceptions.Error:
            result[layer] = None

    bronze_bytes = result.get("bronze", {}) or {}
    gold_bytes = result.get("gold", {}) or {}
    if bronze_bytes.get("bytes") and gold_bytes.get("bytes"):
        savings = (1 - gold_bytes["bytes"] / bronze_bytes["bytes"]) * 100
        result["savings"] = f"{round(savings, 1)}%"
    else:
        result["savings"] = None

    return result