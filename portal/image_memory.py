"""Non-neural fingerprints for exact and near-duplicate images; no local AI inference."""
from io import BytesIO
from PIL import Image, ImageOps, UnidentifiedImageError
import requests


def fingerprint(file):
    try:
        image = ImageOps.exif_transpose(Image.open(file)).convert('RGB')
        small = image.resize((9, 8)).convert('L')
        pixels = list(small.getdata())
        bits = [pixels[y*9+x] > pixels[y*9+x+1] for y in range(8) for x in range(8)]
        value = sum(int(bit) << i for i,bit in enumerate(bits))
        color = image.resize((1,1)).getpixel((0,0))
        return f'{value:016x}', list(color)
    except (OSError, ValueError, UnidentifiedImageError):
        return '', []


def ensure_fingerprint(asset):
    if asset.perceptual_hash or asset.type_fichier != 'image':
        return
    url = asset.url_silver or asset.url_bronze or asset.url_image_source
    if not url:
        return
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        if len(response.content) > 20 * 1024 * 1024:
            return
        digest, color = fingerprint(BytesIO(response.content))
        if digest:
            type(asset).objects.filter(pk=asset.pk).update(perceptual_hash=digest, color_signature=color)
            asset.perceptual_hash, asset.color_signature = digest, color
    except requests.RequestException:
        pass


def is_near_duplicate(left, right):
    if not left.perceptual_hash or not right.perceptual_hash or len(left.color_signature)!=3 or len(right.color_signature)!=3:
        return False
    try:
        first, second = int(left.perceptual_hash,16), int(right.perceptual_hash,16)
    except ValueError:
        return False
    # Flat/blank images have unreliable hashes and must not transfer corrections.
    if not 8 <= first.bit_count() <= 56 or not 8 <= second.bit_count() <= 56:
        return False
    if (first^second).bit_count() > 4:
        return False
    if any(abs(a-b)>18 for a,b in zip(left.color_signature,right.color_signature)):
        return False
    if left.width and left.height and right.width and right.height:
        if abs(left.width/left.height-right.width/right.height) > .08:
            return False
    return True
