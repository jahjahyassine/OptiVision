#!/usr/bin/env python3
"""
Quick startup verification for OptiVision.
Tests import chain and basic initialization.

Run: python verify_system.py
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

print("=" * 70)
print("OptiVision System Verification")
print("=" * 70)

# Test imports
print("\n1. Testing imports...")
try:
    from backend.core.config import settings
    print("   ✓ Config loaded")
    
    from backend.core.frame_queue import FrameQueue
    print("   ✓ FrameQueue imported")
    
    from backend.core.worker_pool import WorkerPool
    print("   ✓ WorkerPool imported")
    
    from backend.communication.websocket_server.websocket_server import ConnectionManager
    print("   ✓ ConnectionManager imported")
    
    from backend.communication.dashboard_manager import DashboardManager
    print("   ✓ DashboardManager imported")
    
    from backend.services.inference_service import build_inference_service
    print("   ✓ InferenceService imported")
    
    from backend.fusion_engine.decision_engine import DecisionEngine
    print("   ✓ DecisionEngine imported")
    
    from backend.fusion_engine.state_manager import StateManager
    print("   ✓ StateManager imported")
    
    from backend.audio.audio_factory import build_audio_priority_queue, build_tts_engine
    print("   ✓ Audio factory imported")
    
except Exception as exc:
    print(f"   ✗ Import failed: {exc}")
    sys.exit(1)

# Test instantiation
print("\n2. Testing basic instantiation...")
try:
    fq = FrameQueue(maxsize=10)
    print("   ✓ FrameQueue created")
    
    dm = DashboardManager()
    print("   ✓ DashboardManager created")
    
    de = DecisionEngine()
    print("   ✓ DecisionEngine created")
    
    sm = StateManager()
    print("   ✓ StateManager created")
    
    tts_engine = build_tts_engine()
    print(f"   ✓ TTS engine created ({type(tts_engine).__name__})")
    
    audio_queue = build_audio_priority_queue(state_manager=sm)
    print("   ✓ AudioPriorityQueue created")
    
except Exception as exc:
    print(f"   ✗ Instantiation failed: {exc}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test FastAPI app import
print("\n3. Testing FastAPI app...")
try:
    from backend.main import app
    print("   ✓ FastAPI app imported")
    print(f"   ✓ App title: {app.title}")
    print(f"   ✓ App version: {app.version}")
except Exception as exc:
    print(f"   ✗ FastAPI app failed: {exc}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\n" + "=" * 70)
print("✅ All checks passed! System is ready to run.")
print("=" * 70)
print("\nStart with:")
print("  uvicorn backend.main:app --host 0.0.0.0 --port 8000")
print("\nOr:")
print("  python backend/core/main.py")
print()
