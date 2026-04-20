import asyncio
from ai_modules.object_detection.detector import ObstacleDetector
from ai_modules.face_recognition.recognizer import FaceNetRecognizer
from ai_modules.ocr.reader import EasyOCRReader
from ai_modules.depth_estimation.depth_estimator import MiDaS_Estimator

class InferenceService:
    def __init__(self):
        # Initialisation des modèles définis dans la stack technique [cite : 213]
        self.obstacle_detector = ObstacleDetector()
        self.face_recognizer = FaceNetRecognizer()
        self.ocr_reader = EasyOCRReader()
        self.depth_estimator = MiDaS_Estimator()

    async def run_parallel_inference(self, frame):
        # Étape 5 & 6 : Exécution parallèle avec un timeout de 150ms [cite : 186, 188]
        try:
            tasks = [
                self.obstacle_detector.detect(frame),
                self.face_recognizer.recognize(frame),
                self.ocr_reader.read_text(frame),
                self.depth_estimator.estimate(frame)
            ]
            
            # Attente de tous les modules simultanément [cite : 188]
            results = await asyncio.wait_for(asyncio.gather(*tasks), timeout=0.15)
            
            return {
                "obstacles": results[0],
                "faces": results[1],
                "ocr_text": results[2],
                "depth_map": results[3]
            }
        except asyncio.TimeoutError:
            # Gestion du timeout pour maintenir la réactivité [cite : 186]
            print("Inference timeout: Returning partial or empty results")
            return None