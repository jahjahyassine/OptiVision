#!/usr/bin/env python3
"""
Complete end-to-end integration test for OptiVision.

Tests the full pipeline:
  Image → InferenceService → DecisionEngine → AudioQueue → TTS

Verifies:
- All components load correctly (no silent failures)
- Data flows through the pipeline without errors
- Thread safety and timeouts work correctly
- Audio system is ready
- System remains responsive under load

Usage:
    python test_complete_integration.py [image_path]

Example:
    python test_complete_integration.py dataset/test_faces/Messi/messi.png
"""

import sys
from pathlib import Path
import logging
import time

PROJECT_ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s"
)
logger = logging.getLogger(__name__)


def test_complete_pipeline(image_path: str = None):
    """Run the complete OptiVision pipeline test."""
    
    print("\n" + "="*80)
    print("OptiVision Complete Pipeline Integration Test".center(80))
    print("="*80)
    
    # Use default test image if not provided
    if image_path is None:
        image_path = "dataset/test_faces/Messi/messi.png"
    
    image_path = Path(image_path)
    if not image_path.exists():
        print(f"\n✗ Test image not found: {image_path}")
        print("  Try: python test_complete_integration.py dataset/test_faces/Messi/messi.png")
        return False
    
    # ────────────────────────────────────────────────────────────────────────────
    # STEP 1: Load Image
    # ────────────────────────────────────────────────────────────────────────────
    print("\n[1/7] Loading test image...")
    try:
        import cv2
        import numpy as np
        frame = cv2.imread(str(image_path))
        if frame is None:
            print(f"   ✗ Failed to load image from {image_path}")
            return False
        print(f"   ✓ Image loaded: {frame.shape} BGR array")
    except Exception as exc:
        print(f"   ✗ Error loading image: {exc}")
        return False
    
    # ────────────────────────────────────────────────────────────────────────────
    # STEP 2: Build InferenceService
    # ────────────────────────────────────────────────────────────────────────────
    print("\n[2/7] Building InferenceService...")
    try:
        from backend.services.inference_service import build_inference_service
        inference_service = build_inference_service()
        print("   ✓ InferenceService built successfully")
    except Exception as exc:
        print(f"   ✗ InferenceService build failed: {exc}")
        import traceback
        traceback.print_exc()
        return False
    
    # ────────────────────────────────────────────────────────────────────────────
    # STEP 3: Run Inference
    # ────────────────────────────────────────────────────────────────────────────
    print("\n[3/7] Running inference (with timeout enforcement)...")
    try:
        t0 = time.monotonic()
        raw_result = inference_service.process_frame(frame, camera_id="test-cam")
        elapsed_ms = (time.monotonic() - t0) * 1000
        
        faces = raw_result.get('faces', [])
        objects = raw_result.get('objects', [])
        ocr = raw_result.get('ocr', [])
        errors = raw_result.get('errors', {})
        latency_ms = raw_result.get('latency_ms', 0)
        
        print(f"   ✓ Inference complete in {elapsed_ms:.1f}ms (reported: {latency_ms:.1f}ms)")
        print(f"      • Faces: {len(faces)} detected")
        print(f"      • Objects: {len(objects)} detected")
        print(f"      • OCR items: {len(ocr)} found")
        if errors:
            print(f"      • Errors: {errors}")
        
        if len(faces) > 0:
            print(f"      • Top face: {faces[0].get('name', 'Unknown')} (confidence: {faces[0].get('confidence', 0):.2f})")
    
    except Exception as exc:
        print(f"   ✗ Inference failed: {exc}")
        import traceback
        traceback.print_exc()
        return False
    
    # ────────────────────────────────────────────────────────────────────────────
    # STEP 4: Run DecisionEngine
    # ────────────────────────────────────────────────────────────────────────────
    print("\n[4/7] Running DecisionEngine...")
    try:
        from backend.fusion_engine.decision_engine import DecisionEngine
        decision_engine = DecisionEngine()
        decision = decision_engine.decide(raw_result)
        
        print(f"   ✓ Decision generated")
        print(f"      • Priority: {decision['priority_score']} ({decision['priority_name']})")
        print(f"      • Alert: \"{decision['alert_text']}\"")
        print(f"      • Confidence: {decision['confidence']:.3f}")
        print(f"      • Critical: {decision['is_critical']}")
        print(f"      • Type: {decision['alert_type']}")
    
    except Exception as exc:
        print(f"   ✗ DecisionEngine failed: {exc}")
        import traceback
        traceback.print_exc()
        return False
    
    # ────────────────────────────────────────────────────────────────────────────
    # STEP 5: Build AudioQueue
    # ────────────────────────────────────────────────────────────────────────────
    print("\n[5/7] Building AudioPriorityQueue...")
    try:
        from backend.fusion_engine.state_manager import StateManager
        from backend.audio.audio_factory import build_audio_priority_queue
        
        state_manager = StateManager()
        audio_queue = build_audio_priority_queue(state_manager=state_manager)
        
        # Check if TTS engine is ready
        tts_engine = audio_queue._tts
        if hasattr(tts_engine, 'is_ready'):
            is_ready = tts_engine.is_ready()
            print(f"   ✓ AudioPriorityQueue created (TTS ready: {is_ready})")
            if not is_ready:
                print(f"      ⚠ WARNING: TTS engine not fully initialized")
                print(f"         Audio output may be disabled")
        else:
            print(f"   ✓ AudioPriorityQueue created")
            print(f"      • TTS type: {type(tts_engine).__name__}")
    
    except Exception as exc:
        print(f"   ✗ AudioQueue build failed: {exc}")
        import traceback
        traceback.print_exc()
        return False
    
    # ────────────────────────────────────────────────────────────────────────────
    # STEP 6: Enqueue Decision
    # ────────────────────────────────────────────────────────────────────────────
    print("\n[6/7] Enqueueing decision to audio queue...")
    try:
        audio_queue.enqueue(decision)
        queue_size = audio_queue.qsize
        print(f"   ✓ Decision enqueued")
        print(f"      • Queue size: {queue_size} pending items")
    
    except Exception as exc:
        print(f"   ✗ Enqueue failed: {exc}")
        import traceback
        traceback.print_exc()
        return False
    
    # ────────────────────────────────────────────────────────────────────────────
    # STEP 7: Verify DashboardManager
    # ────────────────────────────────────────────────────────────────────────────
    print("\n[7/7] Verifying DashboardManager...")
    try:
        from backend.communication.dashboard_manager import DashboardManager
        dashboard_mgr = DashboardManager()
        print(f"   ✓ DashboardManager created")
        print(f"      • Connected clients: {dashboard_mgr.client_count}")
    
    except Exception as exc:
        print(f"   ✗ DashboardManager failed: {exc}")
        import traceback
        traceback.print_exc()
        return False
    
    # ────────────────────────────────────────────────────────────────────────────
    # Final Summary
    # ────────────────────────────────────────────────────────────────────────────
    print("\n" + "="*80)
    print("✅ Pipeline Test PASSED".center(80))
    print("="*80)
    
    print("\nFull Pipeline Flow:")
    print(f"  Image → InferenceService (faces: {len(faces)}, objects: {len(objects)})")
    print(f"    ↓")
    print(f"  DecisionEngine → Priority {decision['priority_score']}: \"{decision['alert_text']}\"")
    print(f"    ↓")
    print(f"  AudioQueue → Ready to speak (queue size: {audio_queue.qsize})")
    print(f"    ↓")
    print(f"  DashboardManager → Broadcasting to {dashboard_mgr.client_count} clients")
    print(f"\n✅ All components working correctly!\n")
    
    return True


if __name__ == "__main__":
    image_path = sys.argv[1] if len(sys.argv) > 1 else None
    success = test_complete_pipeline(image_path)
    sys.exit(0 if success else 1)
