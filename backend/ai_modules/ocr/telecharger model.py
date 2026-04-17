import easyocr
reader = easyocr.Reader(['fr', 'en'], gpu=False)
print("OCR prêt")