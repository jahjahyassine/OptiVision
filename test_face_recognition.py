import os
import cv2
import csv
from datetime import datetime
from collections import defaultdict
from backend.ai_modules.face_recognition.recognizer import FaceRecognizer

# ─── Paths ────────────────────────────────────────────────────────────────────
DATASET_DIR = "dataset/test_faces"
REPORT_DIR  = "reports/face_recognition"
os.makedirs(REPORT_DIR, exist_ok=True)

# ─── Init ─────────────────────────────────────────────────────────────────────
recognizer   = FaceRecognizer()
results_data = []
total        = 0
correct      = 0

per_person   = defaultdict(lambda: {"total": 0, "correct": 0, "errors": []})

# ─── Helpers ──────────────────────────────────────────────────────────────────
def print_separator(char="─", width=60):
    print(char * width)

def print_section(title):
    print_separator()
    print(f"  {title}")
    print_separator()

# ─── Evaluation Loop ──────────────────────────────────────────────────────────
print_section("FACE RECOGNITION EVALUATION STARTED")
print(f"  Dataset : {DATASET_DIR}")
print(f"  Time    : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print_separator()

for person_name in sorted(os.listdir(DATASET_DIR)):
    person_path = os.path.join(DATASET_DIR, person_name)
    if not os.path.isdir(person_path):
        continue

    images = [f for f in os.listdir(person_path)
              if cv2.imread(os.path.join(person_path, f)) is not None]

    print(f"\n  Person : {person_name}  ({len(images)} images)")
    print_separator("·")

    for img_name in images:
        img_path = os.path.join(person_path, img_name)
        frame    = cv2.imread(img_path)

        # ── Run recognition ──────────────────────────────────────────────────
        faces          = recognizer.process(frame)
        num_faces      = len(faces)
        predicted_name = faces[0]["name"] if num_faces > 0 else "NoFace"
        confidence     = faces[0].get("confidence", None) if num_faces > 0 else None

        is_correct = predicted_name == person_name
        total     += 1
        if is_correct:
            correct += 1

        per_person[person_name]["total"]  += 1
        per_person[person_name]["correct"] += int(is_correct)
        if not is_correct:
            per_person[person_name]["errors"].append(img_name)

        # ── Row for CSV ──────────────────────────────────────────────────────
        results_data.append({
            "image"       : img_path,
            "actual"      : person_name,
            "predicted"   : predicted_name,
            "confidence"  : f"{confidence:.4f}" if confidence is not None else "N/A",
            "faces_found" : num_faces,
            "correct"     : is_correct,
        })

        # ── Per-image console line ───────────────────────────────────────────
        status     = "✓" if is_correct else "✗"
        conf_str   = f"  conf={confidence:.2f}" if confidence is not None else ""
        face_str   = f"  faces={num_faces}"
        print(f"  [{status}]  {img_name:<30}  "
              f"predicted: {predicted_name:<20}{conf_str}{face_str}")

    # ── Per-person mini-summary ───────────────────────────────────────────────
    p       = per_person[person_name]
    p_acc   = (p["correct"] / p["total"]) * 100 if p["total"] > 0 else 0
    print(f"\n       Sub-accuracy for {person_name}: "
          f"{p['correct']}/{p['total']}  →  {p_acc:.1f}%")
    if p["errors"]:
        print(f"       Failed images : {', '.join(p['errors'])}")

# ─── Save CSV Report ──────────────────────────────────────────────────────────
timestamp   = datetime.now().strftime("%Y%m%d_%H%M%S")
report_path = os.path.join(REPORT_DIR, f"report_{timestamp}.csv")

with open(report_path, mode="w", newline="") as f:
    fieldnames = ["image", "actual", "predicted", "confidence",
                  "faces_found", "correct"]
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(results_data)

# ─── Final Summary ────────────────────────────────────────────────────────────
accuracy = (correct / total) * 100 if total > 0 else 0

print_section("GLOBAL SUMMARY")
print(f"  Total images tested : {total}")
print(f"  Correct predictions : {correct}")
print(f"  Wrong  predictions  : {total - correct}")
print(f"  Overall accuracy    : {accuracy:.2f}%")
print_separator()

print("\n  Per-person breakdown:")
print_separator("·")
print(f"  {'Person':<25} {'Correct':>8} {'Total':>7} {'Accuracy':>10}")
print_separator("·")
for person, stats in sorted(per_person.items()):
    p_acc = (stats["correct"] / stats["total"]) * 100 if stats["total"] > 0 else 0
    bar   = "█" * int(p_acc / 5)   # simple 20-char bar
    print(f"  {person:<25} {stats['correct']:>8} {stats['total']:>7} "
          f"  {p_acc:>6.1f}%  {bar}")

print_separator()
print(f"  Report saved to: {report_path}")
print_separator()