import cv2
import numpy as np
from core.frame_queue import FrameQueue
from services.inference_service import InferenceService

class FrameService:
    def __init__(self):
        self.queue = FrameQueue(maxsize=5) # Défini par le rapport [cite : 107, 188]
        self.inference_service = InferenceService()

    async def process_incoming_frame(self, raw_data: bytes):
        # Étape 3 : Décodage JPEG en tableau NumPy [cite : 187]
        frame = cv2.imdecode(np.frombuffer(raw_data, np.uint8), cv2.IMREAD_COLOR)
        
        if frame is not None:
            # Étape 4 : Placement dans la file d'attente (gestion des images obsolètes) [cite : 188]
            await self.queue.put_nowait(frame)
            
            # Déclenchement asynchrone du traitement
            return await self.inference_service.run_parallel_inference(frame)
        return None