import os
import cv2
import csv
from datetime import datetime
from backend.ai_modules.face_recognition.recognizer import FaceRecognizer

# Paths
DATASET_DIR = "dataset/test_faces"
REPORT_DIR = "reports"

os.makedirs(REPORT_DIR, exist_ok=True)

# Init recognizer
recognizer = FaceRecognizer()

results_data = []

total = 0
correct = 0

# Loop over people
for person_name in os.listdir(DATASET_DIR):
    person_path = os.path.join(DATASET_DIR, person_name)

    if not os.path.isdir(person_path):
        continue

    for img_name in os.listdir(person_path):
        img_path = os.path.join(person_path, img_name)

        frame = cv2.imread(img_path)
        if frame is None:
            continue

        faces = recognizer.process(frame)

        predicted_name = "NoFace"

        if len(faces) > 0:
            predicted_name = faces[0]["name"]

        is_correct = predicted_name == person_name

        total += 1
        if is_correct:
            correct += 1

        results_data.append({
            "image": img_path,
            "actual": person_name,
            "predicted": predicted_name,
            "correct": is_correct
        })

        print(f"{img_name} | actual: {person_name} | predicted: {predicted_name}")

# Save report
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
report_path = os.path.join(REPORT_DIR, f"report_{timestamp}.csv")

with open(report_path, mode="w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=["image", "actual", "predicted", "correct"])
    writer.writeheader()
    writer.writerows(results_data)

# Summary
accuracy = (correct / total) * 100 if total > 0 else 0

print("\n=== SUMMARY ===")
print(f"Total: {total}")
print(f"Correct: {correct}")
print(f"Accuracy: {accuracy:.2f}%")
print(f"Report saved to: {report_path}")