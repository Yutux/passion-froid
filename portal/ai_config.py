from dataclasses import dataclass

from django.conf import settings


VISION_PROMPT_VERSION = "vision_prompt_v1"

VISION_PROMPT = """
Analyse cette image avec une exigence maximale de précision.
Identifie uniquement ce qui est réellement visible ou raisonnablement déductible.
N'invente jamais une marque, une personne, un lieu, un produit, un texte, un logo ou un événement.
Retourne une analyse structurée en français avec titre, description, tags, catégories,
objets, personnes, logos, OCR, contexte et niveau de confiance.
"""


@dataclass(frozen=True)
class AIConfig:
    vision_model: str
    vision_instruct_model: str
    embedding_model: str
    ocr_model: str
    object_detection_model: str
    speech_model: str
    video_model: str
    prompt_version: str = VISION_PROMPT_VERSION


def get_ai_config() -> AIConfig:
    return AIConfig(
        vision_model=getattr(settings, "HUGGINGFACE_BLIP_MODEL", "Salesforce/blip-image-captioning-large"),
        vision_instruct_model=getattr(settings, "HUGGINGFACE_VISION_INSTRUCT_MODEL", "Qwen/Qwen2.5-VL-7B-Instruct"),
        embedding_model=getattr(settings, "HUGGINGFACE_EMBEDDING_MODEL", "sentence-transformers/clip-ViT-B-32-multilingual-v1"),
        ocr_model=getattr(settings, "HUGGINGFACE_OCR_MODEL", "microsoft/trocr-base-printed"),
        object_detection_model=getattr(settings, "HUGGINGFACE_OBJECT_DETECTION_MODEL", "facebook/detr-resnet-50"),
        speech_model=getattr(settings, "HUGGINGFACE_SPEECH_MODEL", "openai/whisper-large-v3"),
        video_model=getattr(settings, "HUGGINGFACE_VIDEO_MODEL", "MCG-NJU/videomae-base"),
    )
