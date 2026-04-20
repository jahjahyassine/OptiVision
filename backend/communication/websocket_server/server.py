import asyncio
import cv2
import numpy as np
from fastapi import WebSocket, WebSocketDisconnect

async def camera_stream(websocket: WebSocket, frame_service):
    """
    Gère la connexion WebSocket en continu avec la caméra ESP32.
    """
    # Accepte la connexion entrante de la caméra
    await websocket.accept()
    print("Succès : Caméra ESP32 connectée au flux en direct !")
    
    try:
        # Boucle infinie pour écouter en permanence
        while True:
            # 1. On attend et on reçoit le paquet de données (l'image) envoyé par la caméra
            data = await websocket.receive_bytes()
            
            # 2. On transmet immédiatement ces données au FrameService pour le décodage
            # L'utilisation de 'await' garantit que l'on ne perd pas le fil d'exécution
            await frame_service.process_incoming_frame(data)
            
    except WebSocketDisconnect:
        print("Alerte : La caméra ESP32 s'est déconnectée.")
    except Exception as e:
        print(f"Erreur de communication WebSocket : {e}")