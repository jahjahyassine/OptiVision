import cv2
import numpy as np

def correct_contrast(frame):
    lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    l = clahe.apply(l)
    return cv2.cvtColor(cv2.merge((l, a, b)), cv2.COLOR_LAB2BGR)

def sharpen(gray):
    kernel = np.array([[0, -1, 0],
                       [-1, 5, -1],
                       [0, -1, 0]])
    return cv2.filter2D(gray, -1, kernel)

def extract_color_regions(frame):
    """
    Extrait les zones par couleur typique des panneaux :
    jaune, rouge, blanc, bleu — retourne une liste de crops.
    """
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    crops = []

    color_ranges = {
        "jaune": [(20, 80, 80),  (35, 255, 255)],
        "rouge": [(0, 120, 70),  (10, 255, 255)],
        "blanc": [(0, 0, 180),   (180, 40, 255)],
        "bleu":  [(100, 80, 50), (130, 255, 255)],
    }

    for color, (lower, upper) in color_ranges.items():
        mask = cv2.inRange(hsv, np.array(lower), np.array(upper))
        # Dilation pour reconstituer les zones
        mask = cv2.dilate(mask, np.ones((15, 15), np.uint8), iterations=2)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL,
                                        cv2.CHAIN_APPROX_SIMPLE)
        for cnt in contours:
            x, y, w, h = cv2.boundingRect(cnt)
            # Ignorer les zones trop petites
            if w < 30 or h < 15:
                continue
            crop = frame[y:y+h, x:x+w]
            crops.append(crop)

    return crops

def preprocess_frame(frame):
    frame = correct_contrast(frame)
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    gray = sharpen(gray)
    return gray

def get_scales(frame):
    scales = []
    for scale in [1.0, 1.5, 2.0]:
        h, w = frame.shape[:2]
        resized = cv2.resize(frame, (int(w * scale), int(h * scale)),
                             interpolation=cv2.INTER_CUBIC)
        scales.append(resized)
    return scales