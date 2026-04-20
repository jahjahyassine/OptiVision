import os
from ultralytics import YOLO

class ObstacleDetector:
    def __init__(self, model_path='models/yolov8n.pt', conf=0.45):
        """
        Initialise le détecteur d'obstacles.
        :param model_path: Chemin vers les poids du modèle (relatif à ce fichier).
        :param conf: Seuil de confiance minimum (45% par défaut).
        """
        # Construit le chemin absolu vers le dossier 'models/' pour éviter les erreurs
        current_dir = os.path.dirname(os.path.abspath(__file__))
        full_model_path = os.path.join(current_dir, model_path)
        
        print(f"Chargement du modèle YOLOv8 depuis : {full_model_path}")
        
        # Chargement du modèle
        self.model = YOLO(full_model_path)
        self.conf = conf

    def detect(self, frame) -> list[dict]:
        """
        Analyse une image et retourne les objets détectés avec leur distance estimée.
        """
        # Inférence YOLO (verbose=False évite de polluer la console à chaque frame)
        results = self.model(frame, conf=self.conf, verbose=False)
        detections = []
        
        # Parcours de toutes les boîtes (objets) trouvées dans l'image
        for r in results[0].boxes:
            # Récupération des coordonnées de la boîte : [x_min, y_min, x_max, y_max]
            x1, y1, x2, y2 = r.xyxy[0].tolist()
            
            obj = {
                'label': self.model.names[int(r.cls)], # Nom de l'objet (ex: 'person', 'car')
                'confidence': float(r.conf),           # Pourcentage de certitude
                'bbox': [x1, y1, x2, y2],              # Position dans l'image
                'distance_est': self._estimate_distance(y2 - y1) # Calcul de la distance
            }
            detections.append(obj)
            
        return detections

    def _estimate_distance(self, bbox_height_px) -> str:
        """
        Estime grossièrement la distance en se basant sur la hauteur de l'objet en pixels.
        Plus un objet prend de la place en hauteur, plus il est proche.
        """
        if bbox_height_px > 300: 
            return 'very_close'  # Très proche (Danger)
        if bbox_height_px > 150: 
            return 'close'       # Proche (Attention)
        if bbox_height_px > 70: 
            return 'medium'      # Distance moyenne
        return 'far'             # Loin