import easyocr
import re
from ai_modules.ocr.preprocessor import (preprocess_frame,
                                          get_scales,
                                          extract_color_regions)

_reader = None

def get_reader():
    global _reader
    if _reader is None:
        _reader = easyocr.Reader(['fr', 'en'], gpu=False)
    return _reader

def is_useful(text: str) -> bool:
    text = text.strip()
    if len(text) < 2:
        return False
    if re.fullmatch(r'[^\w\s]+', text):
        return False
    return True

def read_image(image, reader, seen: dict, threshold=0.3):
    """Lit une image et met à jour le dict seen."""
    try:
        results = reader.readtext(image, detail=1,
                                  paragraph=False,
                                  width_ths=0.7,
                                  contrast_ths=0.1)
        for (_, text, confidence) in results:
            cleaned = text.strip()
            if confidence > threshold and is_useful(cleaned):
                if cleaned not in seen or seen[cleaned] < confidence:
                    seen[cleaned] = confidence
    except Exception:
        pass

def process(frame) -> dict:
    reader = get_reader()
    seen = {}

    # Lecture multi-échelle sur la frame complète
    for scaled in get_scales(frame):
        preprocessed = preprocess_frame(scaled)
        read_image(preprocessed, reader, seen)

    # Lecture sur les crops couleur (panneaux jaunes, rouges, etc.)
    crops = extract_color_regions(frame)
    for crop in crops:
        # Agrandir le crop pour l'OCR
        h, w = crop.shape[:2]
        crop_resized = cv2.resize(crop, (w * 2, h * 2),
                                  interpolation=cv2.INTER_CUBIC)
        preprocessed_crop = preprocess_frame(crop_resized)
        read_image(preprocessed_crop, reader, seen, threshold=0.25)

    # Trier par confiance décroissante
    sorted_texts = sorted(seen.items(), key=lambda x: x[1], reverse=True)
    details = [{"text": t, "confidence": round(c, 2)} for t, c in sorted_texts]

    return {
        "ocr_text": " | ".join([d["text"] for d in details]),
        "details": details
    }

import cv2