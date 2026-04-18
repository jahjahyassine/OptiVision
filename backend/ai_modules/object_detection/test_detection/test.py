import cv2
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))

from ai_modules.object_detection.detector import ObstacleDetector

def test_image(image_path: str):
    frame = cv2.imread(image_path)
    if frame is None:
        print(f"❌ Impossible de charger l'image : {image_path}")
        sys.exit(1)

    print(f"✅ Image chargée : {frame.shape[1]}x{frame.shape[0]} px")

    detector = ObstacleDetector()
    detections = detector.detect(frame)

    print(f"\n🔍 {len(detections)} objet(s) détecté(s) :\n")
    for i, det in enumerate(detections):
        print(f"  [{i+1}] {det['label']}")
        print(f"       Confiance   : {det['confidence']:.2f}")
        print(f"       BBox        : {[round(v) for v in det['bbox']]}")
        print(f"       Distance    : {det['distance_est']}")
        print()

    for det in detections:
        x1, y1, x2, y2 = [int(v) for v in det['bbox']]
        label = f"{det['label']} ({det['distance_est']})"
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
        cv2.putText(frame, label, (x1, y1 - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

    output_path = "result.jpg"
    cv2.imwrite(output_path, frame)
    print(f"💾 Image annotée sauvegardée : {output_path}")

    cv2.imshow("Detection", frame)
    cv2.waitKey(0)
    cv2.destroyAllWindows()

if __name__ == "__main__":
    test_image(r"C:\Users\uaser\Desktop\Cavour (@cavour_co) • Instagram photos and videos.jpg")