from fastapi import FastAPI, WebSocket
import uvicorn
from contextlib import asynccontextmanager

# Importation des modules du dossier 'core' et 'services'
from core.config import Config
from core.worker_pool import WorkerPool
from services.frame_service import FrameService
from communication.websocket_server import camera_stream

# Initialisation du pool de threads (pour exécuter l'IA en parallèle sans bloquer)
worker_pool = WorkerPool()
frame_service = FrameService()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Démarrage : Initialisation des ressources
    print("Démarrage du système AI Assistive Vision...")
    yield
    # Arrêt : Nettoyage du pool de workers
    print("Arrêt du système...")
    worker_pool.shutdown()

# Création de l'application FastAPI avec la gestion du cycle de vie
app = FastAPI(
    title="AI Assistive Vision System API",
    version="1.0",
    lifespan=lifespan
)

# 1. Point d'entrée WebSocket pour le flux vidéo de l'ESP32-CAM [cite: 106, 107, 210]
@app.websocket('/stream')
async def websocket_endpoint(ws: WebSocket):
    # On délègue la gestion du flux à la fonction définie dans websocket_server.py
    await camera_stream(ws, frame_service)

# 2. Point d'entrée REST API pour l'enrôlement des visages (Team B) 
@app.post('/api/faces/enroll')
async def enroll_face(name: str, image_file: bytes):
    """
    Route définie dans le cahier des charges pour ajouter une nouvelle personne 
    à la base de données de reconnaissance faciale.
    """
    # Logique d'ajout via le module face_recognition
    return {"status": "success", "message": f"Visage de {name} enregistré."}

# Lancement du serveur uvicorn 
if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=Config.WS_PORT, reload=True)