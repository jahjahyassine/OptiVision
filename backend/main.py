from fastapi import FastAPI, WebSocket, UploadFile, File
import uvicorn
from contextlib import asynccontextmanager
import asyncio # <-- NOUVEAU : Requis pour lancer des tâches en arrière-plan

# Importation des composants du système
from core.config import Config
from core.worker_pool import WorkerPool
from services.frame_service import FrameService

# <-- NOUVEAU : Importation du gestionnaire audio
from audio.audio_output_handler.priority_queue import AudioOutputHandler 

# Gestion du cycle de vie pour initialiser les ressources lourdes
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Initialisation de l'Audio
    app.state.audio_handler = AudioOutputHandler()
    
    # 2. Démarrage de la boucle audio en arrière-plan (sans bloquer le serveur)
    audio_task = asyncio.create_task(app.state.audio_handler.run_loop())
    
    # 3. Initialisation du pool de workers et du service d'images
    app.state.worker_pool = WorkerPool()
    
    # ASTUCE : Vous pouvez passer l'audio_handler au FrameService ici 
    # pour que les IA puissent lui envoyer des messages !
    app.state.frame_service = FrameService() 
    
    print("Système AI Assistive Vision : Prêt et à l'écoute !")
    yield # Le serveur tourne ici...
    
    # Nettoyage à la fermeture du serveur
    app.state.worker_pool.shutdown()
    audio_task.cancel() # On arrête proprement la boucle audio

# Création de l'application FastAPI 
app = FastAPI(title="AI Assistive Vision API", lifespan=lifespan)

# 1. Point d'entrée WebSocket pour le streaming vidéo (Équipe B & C) 
@app.websocket("/stream")
async def websocket_stream(websocket: WebSocket):
    await websocket.accept()
    print("Caméra ESP32 connectée via WebSocket")
    
    try:
        while True:
            # Réception des données binaires de la caméra
            data = await websocket.receive_bytes()
            
            # Envoi au service de traitement d'images
            await app.state.frame_service.process_incoming_frame(data)
            
            # EXEMPLE DE TEST : Si vous voulez tester la voix manuellement :
            # await app.state.audio_handler.speak("Image reçue", priority=5)

    except Exception as e:
        print(f"Déconnexion ou erreur : {e}")
    finally:
        await websocket.close()

# 2. API REST pour l'enrôlement des nouveaux visages (Équipe B) 
@app.post("/api/faces/enroll")
async def enroll_face(name: str, file: UploadFile = File(...)):
    # Logique pour ajouter un visage à la base de données
    return {"status": "success", "message": f"Visage de {name} enregistré avec succès"}

if __name__ == "__main__":
    # Lancement du serveur sur le port configuré
    uvicorn.run(app, host="0.0.0.0", port=Config.WS_PORT)