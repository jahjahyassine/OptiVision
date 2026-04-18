"""
enroll.py
=========
Face enrollment CLI — aware of the project's dataset/faces/ folder structure.

Usage examples
--------------

  # Enroll from a single image
  python -m ai_modules.face_recognition.enroll \\
      --name "Ronaldo" --relationship "celebrity" --image dataset/faces/Ronaldo/image.png

  # Enroll from multiple images
  python -m ai_modules.face_recognition.enroll \\
      --name "Ronaldo" \\
      --images dataset/faces/Ronaldo/image.png \\
               dataset/faces/Ronaldo/image2.png \\
               dataset/faces/Ronaldo/image3.png

  # ★ Auto-enroll from a dataset folder (uses folder name as person name)
  python -m ai_modules.face_recognition.enroll \\
      --dataset-person dataset/faces/Ronaldo

  # ★ Auto-enroll EVERY person under dataset/faces/ at once
  python -m ai_modules.face_recognition.enroll --dataset-all

  # Live webcam enrollment
  python -m ai_modules.face_recognition.enroll \\
      --name "Ahmed" --relationship "family" --webcam --captures 5

  # List enrolled persons
  python -m ai_modules.face_recognition.enroll --list

  # Delete a person
  python -m ai_modules.face_recognition.enroll --delete "Ronaldo"

Run from project root or from inside backend/:
  cd backend && python -m ai_modules.face_recognition.enroll --dataset-all
"""

import argparse
import logging
import sys
import time
from pathlib import Path

import cv2

# ── path setup ───────────────────────────────────────────────────────────────
# Supports running as:
#   python -m ai_modules.face_recognition.enroll   (from inside backend/)
#   python backend/ai_modules/face_recognition/enroll.py  (from project root)
_THIS_DIR    = Path(__file__).resolve().parent          # face_recognition/
_BACKEND_DIR = _THIS_DIR.parents[1]                     # backend/
_PROJECT_ROOT = _THIS_DIR.parents[2]                    # project-root/
_DATASET_FACES_DIR = _PROJECT_ROOT / "dataset" / "faces"

for _p in [str(_BACKEND_DIR), str(_PROJECT_ROOT)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from ai_modules.face_recognition import FaceRecognizer   # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


# ──────────────────────────── enrollment helpers ─────────────────────────────

def enroll_dataset_person(
    recognizer: FaceRecognizer,
    person_dir: Path,
    relationship: str = "",
) -> None:
    """Enroll all images in a single person folder (folder name = person name)."""
    name = person_dir.name
    images = sorted(p for p in person_dir.iterdir() if p.suffix.lower() in _IMAGE_EXTS)

    if not images:
        print(f"  ⚠  No images found in {person_dir}")
        return

    count = recognizer.enroll_from_multiple_images(images, name=name, relationship=relationship)
    status = "✓" if count > 0 else "✗"
    print(f"  {status}  '{name}': {count}/{len(images)} embedding(s) stored.")


def enroll_all_dataset(recognizer: FaceRecognizer, dataset_dir: Path) -> None:
    """Walk dataset/faces/ and enroll every subfolder as a separate person."""
    if not dataset_dir.is_dir():
        print(f"✗  Dataset directory not found: {dataset_dir}")
        sys.exit(1)

    persons = sorted(d for d in dataset_dir.iterdir() if d.is_dir())
    if not persons:
        print(f"✗  No person folders found under {dataset_dir}")
        return

    print(f"\nEnrolling {len(persons)} person(s) from {dataset_dir}\n")
    for person_dir in persons:
        enroll_dataset_person(recognizer, person_dir)
    print(f"\nDone. Run --list to verify.")


def enroll_webcam(
    recognizer: FaceRecognizer,
    name: str,
    relationship: str,
    num_captures: int = 5,
    camera_id: int = 0,
) -> None:
    """Open webcam and auto-capture `num_captures` frames for enrollment."""
    cap = cv2.VideoCapture(camera_id)
    if not cap.isOpened():
        logger.error("Cannot open camera %d.", camera_id)
        return

    print(f"\nEnrolling '{name}' — look at the camera.")
    print(f"Will capture {num_captures} frames automatically. Press Q to abort.\n")

    captured = 0
    interval = 3.0 / num_captures
    last_capture_time = 0.0

    while captured < num_captures:
        ret, frame = cap.read()
        if not ret:
            break

        now = time.time()
        preview = frame.copy()

        # Progress bar overlay
        w = preview.shape[1]
        progress = int((captured / num_captures) * w)
        cv2.rectangle(preview, (0, preview.shape[0] - 12),
                      (progress, preview.shape[0]), (0, 200, 0), -1)
        cv2.putText(
            preview,
            f"Capturing {captured}/{num_captures}  |  {name}",
            (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2,
        )
        cv2.imshow("VisionAssist — Enrollment (Q to quit)", preview)

        if now - last_capture_time >= interval:
            ok = recognizer.enroll_from_frame(frame, name=name, relationship=relationship)
            if ok:
                captured += 1
                last_capture_time = now
                print(f"  ✓ Captured {captured}/{num_captures}")
            else:
                print("  ✗ No face detected — please face the camera.")

        if cv2.waitKey(1) & 0xFF in (ord("q"), ord("Q")):
            print("Enrollment aborted.")
            break

    cap.release()
    cv2.destroyAllWindows()
    print(
        f"\n✓ Enrolled {captured} embedding(s) for '{name}'."
        if captured > 0
        else f"\n✗ No embeddings stored for '{name}'."
    )


def list_enrolled(recognizer: FaceRecognizer) -> None:
    people = recognizer.list_enrolled()
    if not people:
        print("Database is empty — no persons enrolled yet.")
        return

    print(f"\n{'ID':>4}  {'Name':<25}  {'Relationship':<15}  Enrolled At")
    print("─" * 72)
    for p in people:
        print(
            f"{p['id']:>4}  {p['name']:<25}  {p.get('relationship',''):<15}"
            f"  {p['enrolled_at'][:19]}"
        )
    print(
        f"\nTotal: {recognizer.db.count()} embedding(s)"
        f" | {recognizer.db.person_count()} person(s)"
    )


# ──────────────────────────── main ───────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="VisionAssist — Face Enrollment CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # ── identity
    parser.add_argument("--name",         type=str)
    parser.add_argument("--relationship", type=str, default="")

    # ── source (mutually exclusive)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--image",          type=str,    help="Single image file")
    source.add_argument("--images",         nargs="+",   help="Multiple image files")
    source.add_argument("--webcam",         action="store_true")
    source.add_argument(
        "--dataset-person",
        type=str,
        metavar="DIR",
        help="Enroll all images in a person folder, e.g. dataset/faces/Ronaldo",
    )
    source.add_argument(
        "--dataset-all",
        action="store_true",
        help=f"Enroll every subfolder under {_DATASET_FACES_DIR}",
    )

    # ── webcam options
    parser.add_argument("--captures",  type=int, default=5)
    parser.add_argument("--camera-id", type=int, default=0)

    # ── db management
    parser.add_argument("--list",   action="store_true")
    parser.add_argument("--delete", type=str, metavar="NAME")

    # ── model
    parser.add_argument("--db",    type=str, default=None,
                        help="Override database path")
    parser.add_argument("--model", type=str, default="buffalo_l",
                        choices=["buffalo_l", "buffalo_sc"])
    parser.add_argument("--cpu",   action="store_true", help="Force CPU mode")

    args = parser.parse_args()

    # ── load model
    print(f"Loading InsightFace model '{args.model}' …")
    kwargs = dict(model_name=args.model, ctx_id=-1 if args.cpu else 0)
    if args.db:
        kwargs["db_path"] = args.db
    recognizer = FaceRecognizer(**kwargs)

    # ── dispatch
    if args.list:
        list_enrolled(recognizer)
        return

    if args.delete:
        n = recognizer.remove_person(args.delete)
        print(f"Deleted {n} embedding(s) for '{args.delete}'.")
        return

    if args.dataset_all:
        enroll_all_dataset(recognizer, _DATASET_FACES_DIR)
        return

    if args.dataset_person:
        enroll_dataset_person(recognizer, Path(args.dataset_person), args.relationship)
        return

    # remaining modes require --name
    if not args.name:
        parser.error("--name is required for image/webcam enrollment.")

    if args.webcam:
        enroll_webcam(
            recognizer,
            name=args.name,
            relationship=args.relationship,
            num_captures=args.captures,
            camera_id=args.camera_id,
        )

    elif args.images:
        n = recognizer.enroll_from_multiple_images(
            args.images, name=args.name, relationship=args.relationship
        )
        print(f"✓ Stored {n}/{len(args.images)} embeddings for '{args.name}'.")

    elif args.image:
        ok = recognizer.enroll_from_image_path(
            args.image, name=args.name, relationship=args.relationship
        )
        print(
            f"✓ Enrolled '{args.name}'." if ok
            else f"✗ No face detected in {args.image}."
        )
        if not ok:
            sys.exit(1)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()