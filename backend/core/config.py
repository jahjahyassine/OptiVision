"""
core/config.py
==============
Centralised runtime settings for OptiVision backend.

All values can be overridden via environment variables or a .env file placed
next to backend/main.py.  Pydantic-settings handles parsing and type coercion.

Usage:
    from backend.core.config import settings
    print(settings.FRAME_QUEUE_SIZE)
"""

from __future__ import annotations

import os
from pathlib import Path

# ── project root resolution ───────────────────────────────────────────────────
# __file__ = project-root/backend/core/config.py
_BACKEND_DIR  = Path(__file__).parents[1].resolve()
_PROJECT_ROOT = Path(__file__).parents[2].resolve()


try:
    from pydantic_settings import BaseSettings
    from pydantic import Field

    class Settings(BaseSettings):
        # Server
        HOST: str      = "0.0.0.0"
        PORT: int      = 8000
        LOG_LEVEL: str = "INFO"

        # WebSocket
        WS_MAX_CONNECTIONS: int    = 10
        WS_RECEIVE_TIMEOUT: float  = 30.0

        # Frame pipeline
        FRAME_QUEUE_SIZE: int  = 30
        N_WORKERS: int         = 2
        FRAME_MAX_WIDTH: int   = 640
        FRAME_MAX_HEIGHT: int  = 480

        # Inference timing (real-time control)
        INFERENCE_TIMEOUT_MS: int = 1500

        # Face Recognition
        FACE_MODEL: str                  = "buffalo_l"
        FACE_CTX_ID: int                 = 0
        FACE_SIMILARITY_THRESHOLD: float = 0.45
        FACE_MIN_SIZE_PX: int            = 40
        FACE_DB_PATH: str                = str(
            _PROJECT_ROOT / "database" / "face_embeddings" / "faces.db"
        )

        # Object Detection
        YOLO_MODEL_PATH: str    = str(
            _BACKEND_DIR / "ai_modules" / "object_detection" / "models" / "yolov8n.pt"
        )
        YOLO_CONFIDENCE: float  = 0.45
        YOLO_IMG_SIZE: int      = 416
        YOLO_DEVICE: str        = "cpu"

        # OCR
        OCR_LANGUAGES: list     = Field(default=["fr", "en"])
        OCR_GPU: bool           = False
        OCR_CONFIDENCE_THRESHOLD: float = 0.3

        # Depth Estimation
        DEPTH_ENABLED: bool  = True
        DEPTH_MODEL: str     = "MiDaS_small"
        DEPTH_DEVICE: str    = "cpu"

        # Decision Engine
        DECISION_CONFIDENCE_THRESHOLD: float = 0.5
        DECISION_IDENTITY_PRIORITY: bool     = True



        # Audio / TTS
        TTS_ENGINE: str             = "google"
        TTS_LANGUAGE: str           = "fr"
        TTS_RATE_LIMIT_SECS: float  = 3.0
        AUDIO_QUEUE_MAX: int        = 20

        class Config:
            env_file          = str(_BACKEND_DIR / ".env")
            env_file_encoding = "utf-8"
            case_sensitive    = False

except ImportError:
    import json
    from pathlib import Path

    # Load .env file if available
    try:
        from dotenv import load_dotenv
        _env_file = _BACKEND_DIR / ".env"
        if _env_file.exists():
            load_dotenv(_env_file)
            print(f"Loaded environment from {_env_file}")
    except ImportError:
        # dotenv not available — try manual .env parsing
        _env_file = _BACKEND_DIR / ".env"
        if _env_file.exists():
            try:
                with open(_env_file) as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            key, val = line.split("=", 1)
                            os.environ[key.strip()] = val.strip()
                print(f"Parsed environment from {_env_file}")
            except Exception as e:
                print(f"Warning: Could not parse .env file: {e}")

    class Settings:  # type: ignore[no-redef]
        HOST: str      = os.getenv("HOST", "0.0.0.0")
        PORT: int      = int(os.getenv("PORT", "8000"))
        LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

        WS_MAX_CONNECTIONS: int   = int(os.getenv("WS_MAX_CONNECTIONS", "10"))
        WS_RECEIVE_TIMEOUT: float = float(os.getenv("WS_RECEIVE_TIMEOUT", "30.0"))

        FRAME_QUEUE_SIZE: int = int(os.getenv("FRAME_QUEUE_SIZE", "30"))
        N_WORKERS: int        = int(os.getenv("N_WORKERS", "2"))
        FRAME_MAX_WIDTH: int  = int(os.getenv("FRAME_MAX_WIDTH", "640"))
        FRAME_MAX_HEIGHT: int = int(os.getenv("FRAME_MAX_HEIGHT", "480"))

        FACE_MODEL: str                  = os.getenv("FACE_MODEL", "buffalo_l")
        FACE_CTX_ID: int                 = int(os.getenv("FACE_CTX_ID", "0"))
        FACE_SIMILARITY_THRESHOLD: float = float(os.getenv("FACE_SIMILARITY_THRESHOLD", "0.45"))
        FACE_MIN_SIZE_PX: int            = int(os.getenv("FACE_MIN_SIZE_PX", "40"))
        FACE_DB_PATH: str                = os.getenv(
            "FACE_DB_PATH",
            str(_PROJECT_ROOT / "database" / "face_embeddings" / "faces.db"),
        )

        YOLO_MODEL_PATH: str   = os.getenv(
            "YOLO_MODEL_PATH",
            str(_BACKEND_DIR / "ai_modules" / "object_detection" / "models" / "yolov8n.pt"),
        )
        YOLO_CONFIDENCE: float = float(os.getenv("YOLO_CONFIDENCE", "0.45"))
        YOLO_IMG_SIZE: int     = int(os.getenv("YOLO_IMG_SIZE", "416"))
        YOLO_DEVICE: str       = os.getenv("YOLO_DEVICE", "cpu")

        OCR_LANGUAGES: list             = json.loads(os.getenv("OCR_LANGUAGES", '["fr","en"]'))
        OCR_GPU: bool                   = os.getenv("OCR_GPU", "false").lower() == "true"
        OCR_CONFIDENCE_THRESHOLD: float = float(os.getenv("OCR_CONFIDENCE_THRESHOLD", "0.3"))

        DEPTH_ENABLED: bool  = os.getenv("DEPTH_ENABLED", "true").lower() == "true"
        DEPTH_MODEL: str     = os.getenv("DEPTH_MODEL", "MiDaS_small")
        DEPTH_DEVICE: str    = os.getenv("DEPTH_DEVICE", "cpu")

        DECISION_CONFIDENCE_THRESHOLD: float = float(
            os.getenv("DECISION_CONFIDENCE_THRESHOLD", "0.5")
        )
        DECISION_IDENTITY_PRIORITY: bool = (
            os.getenv("DECISION_IDENTITY_PRIORITY", "true").lower() == "true"
        )

        TTS_ENGINE: str            = os.getenv("TTS_ENGINE", "google")
        TTS_LANGUAGE: str          = os.getenv("TTS_LANGUAGE", "fr")
        TTS_RATE_LIMIT_SECS: float = float(os.getenv("TTS_RATE_LIMIT_SECS", "3.0"))
        AUDIO_QUEUE_MAX: int       = int(os.getenv("AUDIO_QUEUE_MAX", "20"))

        INFERENCE_TIMEOUT_MS: int = int(os.getenv("INFERENCE_TIMEOUT_MS", "1500"))


settings = Settings()