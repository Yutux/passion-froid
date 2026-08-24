import time

from .bronze import upload_to_bronze
from .silver import promote_to_silver
from .gold import promote_to_gold


def run_medallion_pipeline(
    file,
    public_id: str,
    silver_max_size: int = 800,
    gold_width: int = 1200,
    gold_quality: int = 85,
) -> dict:
    """
    Pipeline Medallion complet : Bronze → Silver → Gold.

    Args:
        file        : Fichier Django, chemin local ou URL
        public_id   : Identifiant unique de l'asset
        silver_max_size : Largeur/hauteur max pour la couche Silver (défaut 800)
        gold_width  : Largeur max pour la couche Gold (défaut 1200)
        gold_quality: Qualité pour la couche Gold (défaut 85)

    Returns:
        dict avec urls (bronze, silver, gold), stats et métadonnées
    """
    start = time.time()

    # ── Étape 1 : Bronze (upload brut) ──────────────────────
    bronze = upload_to_bronze(file, public_id)
    resource_type = bronze["resource_type"]

    # ── Étape 2 : Silver (normalisation) ────────────────────
    silver = promote_to_silver(public_id, resource_type=resource_type, max_size=silver_max_size)

    # ── Étape 3 : Gold (production finale) ──────────────────
    gold = promote_to_gold(public_id, resource_type=resource_type, width=gold_width, quality=gold_quality)

    duration = round(time.time() - start, 2)
    savings = round((1 - gold["bytes"] / bronze["bytes"]) * 100, 1) if bronze["bytes"] else 0

    return {
        "public_id": public_id,
        "duration": f"{duration}s",
        "savings": f"{savings}%",
        "urls": {
            "bronze": bronze["url"],
            "silver": silver["url"],
            "gold": gold["url"],
        },
        "layers": {
            "bronze": bronze,
            "silver": silver,
            "gold": gold,
        },
    }