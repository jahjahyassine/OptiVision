"""
test_image.py
=============
Sends one or more image files to the OptiVision WebSocket server,
simulating an ESP32-CAM frame with the correct 0xAV binary header.

Usage
-----
    # server must be running first:
    uvicorn backend.main:app --host 0.0.0.0 --port 8000

    # send a single image once:
    python test_image.py photo.jpg

    # send multiple images in sequence:
    python test_image.py img1.jpg img2.png img3.jpeg

    # loop the same image N times (stress-test the pipeline):
    python test_image.py photo.jpg --repeat 10 --delay 0.5

    # resize to 640x480 before sending (matches ESP32 resolution):
    python test_image.py photo.jpg --resize

Dependencies
------------
    pip install opencv-python websockets
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import struct
import time
from pathlib import Path

import cv2

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("image-test")

# ── 0xAV frame header — must match ESP32-CAM / ConnectionManager expectations ─
#   Bytes 0–1 : magic  0x41 0x56  ('A', 'V')
#   Bytes 2–3 : frame sequence  (uint16 little-endian)
#   Bytes 4–7 : timestamp ms    (uint32 little-endian)
#   Bytes 8+  : JPEG payload
MAGIC = b"\x41\x56"

def build_packet(jpeg_bytes: bytes, seq: int) -> bytes:
    ts_ms = int(time.monotonic() * 1000) & 0xFFFFFFFF
    header = MAGIC + struct.pack("<HI", seq & 0xFFFF, ts_ms)
    return header + jpeg_bytes


def load_image_as_jpeg(path: Path, resize: bool) -> bytes | None:
    """Read any image format OpenCV supports and return JPEG bytes."""
    frame = cv2.imread(str(path))
    if frame is None:
        logger.error("Cannot read image: %s", path)
        return None

    if resize:
        frame = cv2.resize(frame, (640, 480), interpolation=cv2.INTER_AREA)
        logger.info("Resized to 640×480")

    h, w = frame.shape[:2]
    logger.info("Loaded %s  (%d×%d)", path.name, w, h)

    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        logger.error("JPEG encoding failed for %s", path)
        return None

    return buf.tobytes()


async def send_images(
    host: str,
    port: int,
    image_paths: list[Path],
    repeat: int,
    delay: float,
    resize: bool,
) -> None:
    try:
        import websockets  # type: ignore
    except ImportError:
        logger.error("websockets not installed — run: pip install websockets")
        return

    # Pre-load and encode all images before connecting
    frames: list[tuple[str, bytes]] = []
    for p in image_paths:
        jpeg = load_image_as_jpeg(p, resize)
        if jpeg is not None:
            frames.append((p.name, jpeg))

    if not frames:
        logger.error("No valid images to send.")
        return

    uri = f"ws://{host}:{port}/ws/image-test"
    logger.info("Connecting to %s …", uri)

    try:
        async with websockets.connect(uri, max_size=2**23) as ws:
            logger.info(
                "Connected — sending %d image(s) × %d repeat(s) with %.1fs delay.",
                len(frames), repeat, delay,
            )

            seq = 0
            for run in range(repeat):
                if repeat > 1:
                    logger.info("── Run %d/%d ──", run + 1, repeat)

                for name, jpeg_bytes in frames:
                    packet = build_packet(jpeg_bytes, seq)
                    seq += 1

                    await ws.send(packet)
                    logger.info(
                        "[seq=%d] Sent %-30s  (%d KB) — watch server for detections …",
                        seq, name, len(jpeg_bytes) // 1024,
                    )

                    if delay > 0:
                        await asyncio.sleep(delay)

            logger.info("All frames sent. Waiting 3 s for final audio to finish …")
            await asyncio.sleep(3)

    except OSError as exc:
        logger.error(
            "Could not connect to %s — is the server running?\n  %s", uri, exc
        )


def main() -> None:
    ap = argparse.ArgumentParser(description="OptiVision single-image test client")
    ap.add_argument(
        "images",
        nargs="+",
        type=Path,
        help="One or more image files to send (jpg, png, bmp, …)",
    )
    ap.add_argument("--host",   default="127.0.0.1", help="Server host (default: 127.0.0.1)")
    ap.add_argument("--port",   default=8000, type=int, help="Server port (default: 8000)")
    ap.add_argument("--repeat", default=1,    type=int, help="How many times to send the image(s) (default: 1)")
    ap.add_argument("--delay",  default=1.0,  type=float, help="Seconds between frames (default: 1.0)")
    ap.add_argument("--resize", action="store_true", help="Resize to 640×480 before sending")
    args = ap.parse_args()

    # Validate paths
    valid = []
    for p in args.images:
        if not p.exists():
            logger.error("File not found: %s", p)
        else:
            valid.append(p)

    if not valid:
        logger.error("No valid image paths provided.")
        return

    try:
        asyncio.run(
            send_images(args.host, args.port, valid, args.repeat, args.delay, args.resize)
        )
    except KeyboardInterrupt:
        logger.info("Stopped.")


if __name__ == "__main__":
    main()