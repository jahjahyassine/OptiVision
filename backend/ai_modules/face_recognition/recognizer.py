from deepface import DeepFace
import cv2
import os

class FaceRecognizer:
    def __init__(self):
        # Dossier où tu rangeras les photos (ex: database/user_profiles/Paul.jpg)
        self.db_path = "database/user_profiles"
        if not os.path.exists(self.db_path):
            os.makedirs(self.db_path)
        print("Moteur de reconnaissance DeepFace prêt.")

    def recognize(self, frame):
        try:
            # On cherche si un visage de la photo correspond à un fichier dans le dossier
            # model_name="Facenet" est un bon compromis vitesse/précision
            results = DeepFace.find(img_path=frame, 
                                    db_path=self.db_path, 
                                    model_name="Facenet",
                                    enforce_detection=False, 
                                    silent=True)
            
            final_results = []
            if len(results) > 0 and not results[0].empty:
                # On récupère le nom du fichier (ex: Paul.jpg -> Paul)
                path = results[0]['identity'][0]
                name = os.path.basename(path).split('.')[0]
                final_results.append({"name": name, "confidence": 0.9})
            
            return final_results
        except Exception as e:
            return []