import cv2
import asyncio
import os
import sys

# --- CONFIGURATION DU CHEMIN RACINE ---
# On remonte d'un niveau pour être à la racine de 'OptiVision'
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(CURRENT_DIR)

try:
    # ATTENTION : On importe 'ObstacleDetector' car c'est le nom dans ton fichier
    from ai_modules.object_detection.detector import ObstacleDetector
    from ai_modules.ocr.reader import EasyOCRReader
    from ai_modules.face_recognition.recognizer import FaceRecognizer
    print("✅ Tous les modules IA sont chargés, y compris le détecteur d'obstacles.")
except ImportError as e:
    print(f"❌ Erreur d'importation : {e}")
    print("Vérifiez que le fichier se nomme bien detector.py et contient la classe ObstacleDetector.")
    sys.exit(1)

async def test_full_analysis(image_path):
    print(f"\n--- ANALYSE DE L'IMAGE : {os.path.basename(image_path)} ---")
    
    frame = cv2.imread(image_path)
    if frame is None:
        print("❌ Image introuvable.")
        return

    # 1. Initialisation des moteurs
    # Note : Vérifie que le dossier 'models' existe dans ai_modules/object_detection/
    detector = ObstacleDetector() 
    face_rec = FaceRecognizer()
    ocr = EasyOCRReader(use_gpu=False)

    # 2. Détection d'obstacles (YOLOv8)
    print("\n[1/3] Détection d'objets...")
    obstacles = detector.detect(frame)
    for obs in obstacles:
        label = obs['label']
        dist = obs['distance_est']
        conf = obs['confidence']
        print(f"   📦 {label.upper()} détecté | Distance : {dist} | Confiance : {conf:.2f}")
        
        # Dessin des boîtes sur l'image
        x1, y1, x2, y2 = map(int, obs['bbox'])
        color = (0, 0, 255) if dist == 'very_close' else (0, 255, 0)
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        cv2.putText(frame, f"{label} ({dist})", (x1, y1-10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

    # 3. Reconnaissance Faciale
   # Remplace la partie [2/3] par ceci :
    print("\n[2/3] Recherche de visages...")
    try:
        faces = face_rec.recognize(frame)
        if faces:
            for f in faces:
                print(f"   👤 DEBUG : Visage trouvé ! Nom: {f.get('name')}, Confiance: {f.get('confidence')}")
        else:
            print("   👤 INFO : Aucun visage n'a été détecté par DeepFace sur cette image.")
    except Exception as e:
        print(f"   ❌ Erreur DeepFace : {e}")

    # 4. OCR
    print("\n[3/3] Lecture de texte...")
    text = ocr.read_text(frame)
    if text:
        print(f"   📝 Texte lu : {text}")

    # 5. Affichage du résultat
    cv2.imshow("OptiVision V2 - Analyse Complete", frame)
    print("\nAppuyez sur une touche pour fermer la fenêtre.")
    cv2.waitKey(0)
    cv2.destroyAllWindows()

if __name__ == "__main__":
    # Remplace par ton chemin d'image
    image_cible = r"C:\Users\uaser\Desktop\man2.png"
    
    if os.path.exists(image_cible):
        asyncio.run(test_full_analysis(image_cible))
    else:
        print(f"❌ Fichier inexistant : {image_cible}")