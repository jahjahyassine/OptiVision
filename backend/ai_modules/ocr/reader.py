import easyocr
from ai_modules.ocr.preprocessor import ImagePreprocessor

class EasyOCRReader:

    def __init__(self, use_gpu=True):
        """
        Initialise le modèle EasyOCR.
        """
        print("Chargement du modèle EasyOCR en cours...")
        # On charge les langues français ('fr') et anglais ('en')
        self.reader = easyocr.Reader(['fr', 'en'], gpu=use_gpu)
        self.preprocessor = ImagePreprocessor()

    def read_text(self, frame) -> str:
        """
        Interface requise par le pipeline : prend une image et retourne le texte trouvé.
        """
        # Étape 1 : Améliorer la netteté de l'image avec le preprocessor
        processed_frame = self.preprocessor.sharpen(frame)
        
        # Étape 2 : Lire le texte (detail=0 retourne uniquement le texte, pas les coordonnées)
        results = self.reader.readtext(processed_frame, detail=0)
        
        # Étape 3 : Concaténer les mots trouvés pour former une phrase lisible
        if results:
            ocr_text = " ".join(results)
            return ocr_text
        
        return "" # Retourne vide si aucun texte n'est trouvé