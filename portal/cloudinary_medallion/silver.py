import cloudinary
import cloudinary.uploader
import cloudinary.utils


def promote_to_silver(public_id: str, resource_type: str = "image", max_size: int = 800, extra_options: dict = None) -> dict:
    """
    COUCHE SILVER — Nettoyage & normalisation.
    Applique les transformations de base :
      - Redimensionnement à max_size px (largeur/hauteur max, sans crop agressif)
      - Qualité automatique
      - Format optimal (WebP/AVIF selon navigateur)
      - Suppression des métadonnées EXIF/GPS (images uniquement)
      - Correction d'orientation automatique (images uniquement)

    Args:
        public_id     : L'identifiant de l'asset dans bronze/ (sans préfixe)
        resource_type : "image" ou "video" — doit correspondre à celui utilisé en bronze
        max_size      : Largeur/hauteur max en px (défaut 800, "crop": "limit" ne rogne rien)
        extra_options : Options Cloudinary supplémentaires

    Returns:
        dict avec layer, public_id, url, format, width, height, bytes, created_at, resource_type
    """
    transformation = [
        {"width": max_size, "height": max_size, "crop": "limit"},  # Redimensionnement réel
        {"quality": "auto"},          # Qualité optimale automatique
        {"fetch_format": "auto"},     # Format optimal : WebP, AVIF...
    ]
    if resource_type == "image":
        # strip_profile / angle exif n'ont pas de sens sur une vidéo
        transformation += [
            {"flags": "strip_profile"},   # Supprime métadonnées EXIF/GPS
            {"angle": "exif"},            # Corrige l'orientation EXIF
        ]

    # URL source depuis bronze avec transformations de normalisation
    bronze_url, _ = cloudinary.utils.cloudinary_url(
        f"bronze/{public_id}",
        resource_type=resource_type,
        transformation=transformation,
        secure=True,
    )

    options = {
        "folder": "silver",
        "public_id": public_id,
        "resource_type": resource_type,
        "overwrite": True,
        "invalidate": True,
        "tags": ["silver", "normalized"],
        "context": {
            "layer": "silver",
            "source": f"bronze/{public_id}",
        },
    }
    if extra_options:
        options.update(extra_options)

    result = cloudinary.uploader.upload(bronze_url, **options)

    return {
        "layer": "silver",
        "public_id": result["public_id"],
        "url": result["secure_url"],
        "format": result.get("format", ""),
        "width": result.get("width"),
        "height": result.get("height"),
        "bytes": result.get("bytes", 0),
        "created_at": result.get("created_at", ""),
        "resource_type": result.get("resource_type", resource_type),
    }