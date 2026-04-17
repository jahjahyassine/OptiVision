import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

import cv2
from ai_modules.ocr.reader import process

frame = cv2.imread(r"C:\Users\uaser\Downloads\panauxsolde.jpg")

if frame is None:
    print("Erreur : image introuvable, vérifiez le chemin")
else:
    result = process(frame)
    print(result)