import os
import cloudinary.uploader

from .helpers import sanitize_context_value


def upload_to_bronze(file, public_id: str, extra_options: dict = None) -> dict:
    """
    COUCHE BRONZE — Upload brut.
    Aucune transformation appliquée : conservation de l'original.
    Équivalent du bucket "bronze" dans MinIO.

    Args:
        file       : Fichier Django (InMemoryUploadedFile) ou chemin local ou URL
        public_id  : Identifiant unique de l'asset (sans extension)
        extra_options : Options Cloudinary supplémentaires

    Returns:
        dict avec layer, public_id, url, format, width, height, bytes, created_at, resource_type
    """
    options = {
        "folder": "bronze",
        "public_id": public_id,
        "resource_type": "auto",  # image, video ou raw détecté automatiquement
        "overwrite": True,
        "invalidate": True,
        "tags": ["bronze", "raw"],
        "context": {
            "layer": "bronze",
            "original_name": sanitize_context_value(getattr(file, "name", str(file))),
        },
    }
    if extra_options:
        options.update(extra_options)

    result = cloudinary.uploader.upload(file, **options)

    return {
        "layer": "bronze",
        "public_id": result["public_id"],
        "url": result["secure_url"],
        "format": result.get("format", ""),
        "width": result.get("width"),
        "height": result.get("height"),
        "bytes": result.get("bytes", 0),
        "created_at": result.get("created_at", ""),
        "resource_type": result.get("resource_type", "image"),
    }