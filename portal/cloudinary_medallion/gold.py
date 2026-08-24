import cloudinary
import cloudinary.uploader
import cloudinary.utils


def promote_to_gold(
    public_id: str,
    resource_type: str = "image",
    width: int = 1200,
    height: int = None,
    crop: str = "limit",
    quality: int = 85,
    extra_options: dict = None,
) -> dict:
    """
    COUCHE GOLD — Production finale.
    Applique les transformations finales pour la livraison CDN :
      - Redimensionnement intelligent
      - Qualité maîtrisée
      - Résolution écran automatique (DPR Retina, images uniquement)
      - Légère netteté finale (images uniquement)

    Args:
        public_id     : L'identifiant de l'asset dans silver/
        resource_type : "image" ou "video" — doit correspondre à celui utilisé en silver
        width         : Largeur max (défaut 1200px)
        height        : Hauteur max (optionnel)
        crop          : Mode de crop (défaut 'limit')
        quality       : Qualité 1-100 (défaut 85)
        extra_options : Options Cloudinary supplémentaires

    Returns:
        dict avec layer, public_id, url, format, width, height, bytes, created_at, resource_type
    """
    resize = {"width": width, "crop": crop}
    if height:
        resize["height"] = height

    transformation = [
        {"quality": quality},
        {"fetch_format": "auto"},
        resize,
    ]
    if resource_type == "image":
        # dpr (résolution écran) et sharpen n'ont pas de sens sur une vidéo
        transformation += [
            {"dpr": "auto"},
            {"effect": "sharpen:50"},
        ]

    silver_url, _ = cloudinary.utils.cloudinary_url(
        f"silver/{public_id}",
        resource_type=resource_type,
        transformation=transformation,
        secure=True,
    )

    options = {
        "folder": "gold",
        "public_id": public_id,
        "resource_type": resource_type,
        "overwrite": True,
        "invalidate": True,
        "tags": ["gold", "production", "ready"],
        "context": {
            "layer": "gold",
            "source": f"silver/{public_id}",
        },
    }
    if extra_options:
        options.update(extra_options)

    result = cloudinary.uploader.upload(silver_url, **options)

    return {
        "layer": "gold",
        "public_id": result["public_id"],
        "url": result["secure_url"],
        "format": result.get("format", ""),
        "width": result.get("width"),
        "height": result.get("height"),
        "bytes": result.get("bytes", 0),
        "created_at": result.get("created_at", ""),
        "resource_type": result.get("resource_type", resource_type),
    }