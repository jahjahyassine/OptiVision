"""
core/main.py
============
Alternative entry point — runs uvicorn programmatically.

Usage (from project root):
    python -m backend.core.main

Or via the convenience script:
    python backend/core/main.py
"""
import sys
from pathlib import Path

# Ensure project root is on the path regardless of where this is invoked from
_PROJECT_ROOT = Path(__file__).parents[2].resolve()
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import uvicorn
from backend.core.config import settings


def main():
    uvicorn.run(
        "backend.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=False,
        log_level=settings.LOG_LEVEL.lower(),
        workers=1,          # single process — WorkerPool handles parallelism internally
    )


if __name__ == "__main__":
    main()