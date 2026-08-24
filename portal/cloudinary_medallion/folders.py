import cloudinary.api

MEDALLION_FOLDERS = ["bronze", "silver", "gold"]


def create_medallion_folders():
    """
    Crée les 3 dossiers Medallion sur Cloudinary.
    Équivalent des 3 buckets MinIO : bronze/, silver/, gold/
    Retourne un dict avec le statut de chaque dossier.
    """
    results = {}

    for folder in MEDALLION_FOLDERS:
        try:
            cloudinary.api.create_folder(folder)
            results[folder] = {"status": "created", "message": f'Dossier "{folder}" créé avec succès'}
        except cloudinary.exceptions.Error as e:
            err = getattr(e, "args", [{}])
            http_code = err[0].get("http_code") if err else None
            if http_code == 409:
                results[folder] = {"status": "exists", "message": f'Dossier "{folder}" existe déjà'}
            else:
                results[folder] = {"status": "error", "message": str(e)}

    return results


def list_medallion_folders():
    """
    Liste les dossiers racine Cloudinary.
    Retourne la liste des dossiers existants.
    """
    try:
        response = cloudinary.api.root_folders()
        return [f["name"] for f in response.get("folders", [])]
    except cloudinary.exceptions.Error as e:
        return {"error": str(e)}
