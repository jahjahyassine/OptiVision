import cv2
import numpy as np

class ImagePreprocessor:
    def sharpen(self, frame):
        """
        Améliore la netteté de l'image (Image sharpening) comme exigé par le cahier des charges.
        """
        # Création d'un filtre (kernel) pour accentuer les contours des lettres
        kernel = np.array([[0, -1, 0],
                           [-1, 5,-1],
                           [0, -1, 0]])
        
        # Application du filtre avec OpenCV
        sharpened_frame = cv2.filter2D(frame, -1, kernel)
        
        # Conversion en noir et blanc (niveaux de gris) pour faciliter le travail de l'OCR
        gray_frame = cv2.cvtColor(sharpened_frame, cv2.COLOR_BGR2GRAY)
        
        return gray_frame