import json
import os
import numpy as np

class EmbeddingDB:
    def __init__(self, db_path="database/face_embeddings/embeddings.json"):
        self.db_path = db_path
        self.known_faces = self._load_db()

    def _load_db(self):
        if not os.path.exists(self.db_path):
            return {}
        with open(self.db_path, 'r') as f:
            data = json.load(f)
            # Convertir les listes en tableaux NumPy pour les calculs rapides
            for face_id in data:
                data[face_id]['embedding'] = np.array(data[face_id]['embedding'])
            return data

    def add_face(self, name, embedding):
        face_id = str(len(self.known_faces) + 1)
        # On sauvegarde en liste pour le JSON, mais on garde en NumPy pour le moteur
        self.known_faces[face_id] = {"name": name, "embedding": embedding}
        
        # Sauvegarde sur le disque
        save_data = {fid: {"name": d["name"], "embedding": d["embedding"].tolist()} 
                     for fid, d in self.known_faces.items()}
        with open(self.db_path, 'w') as f:
            json.dump(save_data, f)
        print(f"Visage de {name} ajouté à la base.")