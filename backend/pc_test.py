import cv2
import asyncio
import os
import sys
import time

# --- CORRECTION DES IMPORTS ---
# On ajoute le chemin de la racine au système pour que Python trouve 'ai_modules', etc.
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Désactiver les logs inutiles de TensorFlow pour y voir clair
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'

try:
    from ai_modules.ocr.reader import EasyOCRReader
    from ai_modules.face_recognition.recognizer import FaceRecognizer
    from fusion_engine.state_manager import StateManager
    from fusion_engine.decision_engine import DecisionEngine
    from audio.audio_output_handler.priority_queue import AudioOutputHandler
    print("✅ Tous les modules ont été importés avec succès.")
except ImportError as e:
    print(f"❌ Erreur d'importation : {e}")
    print("\nVérifiez que vous avez bien des fichiers __init__.py vides dans chaque dossier.")
    sys.exit(1)

async def run_pc_vision():
    # Initialisation des composants
    # Note: On passe use_gpu=False si tu n'as pas configuré CUDA
    ocr_engine = EasyOCRReader(use_gpu=False)
    face_engine = FaceRecognizer()
    state_manager = StateManager()
    decision_engine = DecisionEngine()
    audio_handler = AudioOutputHandler()

    # Lancement de la boucle audio en arrière-plan
    asyncio.create_task(audio_handler.run_loop())

    cap = cv2.VideoCapture(0) # 0 = Webcam du PC
    
    if not cap.isOpened():
        print("Erreur : Impossible d'ouvrir la webcam.")
        return

    print("\n--- TEST OPTIVISION V2 DÉMARRÉ ---")
    print("Appuyez sur 'q' pour quitter.")

    frame_count = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break

        # Analyse toutes les 30 frames pour ne pas surcharger le CPU
        if frame_count % 30 == 0:
            # 1. Analyse IA
            found_text = ocr_engine.read_text(frame)
            found_faces = face_engine.recognize(frame)

            # 2. Mise à jour du cerveau (StateManager)
            state_manager.update(faces=found_faces, texts=found_text)

            # 3. Prise de décision
            message = decision_engine.decide(state_manager.get_context())

            # 4. Action Audio
            if message:
                print(f"[IA DECISION] : {message}")
                await audio_handler.speak(message, priority=3)

        # Affichage écran
        cv2.imshow("OptiVision V2 - Test Caméra PC", frame)

        frame_count += 1
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    asyncio.run(run_pc_vision())