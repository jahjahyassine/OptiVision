import time

class StateManager:
    def __init__(self):
        """
        Initialise l'état actuel de ce que voient les lunettes.
        """
        self.current_context = {
            "objects": [],     # Liste des objets détectés (YOLO)
            "faces": [],       # Liste des visages reconnus (DeepFace)
            "texts": [],       # Texte extrait (OCR)
            "depth": None,     # Données de profondeur (à venir)
            "last_update": 0   # Timestamp pour la gestion du temps
        }
        
        # Historique pour éviter de répéter 10 fois la même chose
        self.history = {
            "last_spoken_text": "",
            "last_spoken_face": "",
            "detection_time": {}
        }

    def update(self, objects=None, faces=None, texts=None, depth=None):
        """
        Met à jour la mémoire vive du système avec les dernières analyses.
        """
        self.current_context["objects"] = objects if objects is not None else []
        self.current_context["faces"] = faces if faces is not None else []
        
        # Formatage du texte pour le moteur de décision
        if isinstance(texts, str):
            # Si le reader renvoie juste un string, on le transforme en dictionnaire
            self.current_context["texts"] = [{"text": texts}] if texts.strip() else []
        else:
            self.current_context["texts"] = texts if texts is not None else []

        self.current_context["depth"] = depth
        self.current_context["last_update"] = time.time()

    def get_context(self):
        """
        Retourne l'état actuel pour que le DecisionEngine puisse trancher.
        """
        return self.current_context

    def clean_old_data(self, timeout=5):
        """
        Efface les détections trop vieilles (si l'image n'est plus à jour).
        """
        if time.time() - self.current_context["last_update"] > timeout:
            self.current_context["objects"] = []
            self.current_context["faces"] = []
            self.current_context["texts"] = []

SceneContext = StateManager()