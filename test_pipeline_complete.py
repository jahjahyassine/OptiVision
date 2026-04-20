#!/usr/bin/env python3
"""
Quick integration test for OptiVision pipeline.
Tests: inference service → decision engine → audio queue.

Usage:
    python test_pipeline.py [image_path]

Example:
    python test_pipeline.py dataset/test_faces/Messi/messi.png
"""

import sys
from pathlib import Path
import logging

PROJECT_ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s"
)
logger = logging.getLogger(__name__)

def test_pipeline(image_path: str):
    """Test the complete inference → decision → audio pipeline."""
    
    print("\n" + "="*70)
    print("OptiVision Pipeline Integration Test")
    print("="*70)
    
    # 1. Load image
    print(f"\n1. Loading image: {image_path}")
    try:
        import cv2
        import numpy as np
        frame = cv2.imread(image_path)
        if frame is None:
            print(f"   ✗ Failed to load image")
            return
        print(f"   ✓ Image loaded: {frame.shape}")
    except Exception as exc:
        print(f"   ✗ Error: {exc}")
        return
    
    # 2. Build inference service
    print("\n2. Building InferenceService...")
    try:
        from backend.services.inference_service import build_inference_service
        inference_service = build_inference_service()
        print("   ✓ InferenceService created")
    except Exception as exc:
        print(f"   ✗ Error: {exc}")
        import traceback
        traceback.print_exc()
        return
    
    # 3. Run inference
    print("\n3. Running inference (150ms timeout)...")
    try:
        raw_result = inference_service.process_frame(frame, camera_id="test")
        print(f"   ✓ Inference complete")
        print(f"      - Faces detected: {len(raw_result.get('faces', []))}")
        print(f"      - Objects detected: {len(raw_result.get('objects', []))}")
        print(f"      - OCR items: {len(raw_result.get('ocr', []))}")
        print(f"      - Latency: {raw_result.get('latency_ms', 0):.1f}ms")
    except Exception as exc:
        print(f"   ✗ Error: {exc}")
        import traceback
        traceback.print_exc()
        return
    
    # 4. Run decision engine
    print("\n4. Running DecisionEngine...")
    try:
        from backend.fusion_engine.decision_engine import DecisionEngine
        decision_engine = DecisionEngine()
        decision = decision_engine.decide(raw_result)
        print(f"   ✓ Decision generated")
        print(f"      - Priority: {decision['priority_score']} ({decision['priority_name']})")
        print(f"      - Alert: {decision['alert_text']}")
        print(f"      - Critical: {decision['is_critical']}")
        print(f"      - Confidence: {decision['confidence']:.3f}")
    except Exception as exc:
        print(f"   ✗ Error: {exc}")
        import traceback
        traceback.print_exc()
        return
    
    # 5. Test audio queue (without speaking)
    print("\n5. Testing AudioPriorityQueue (enqueue only, no audio)...")
    try:
        from backend.fusion_engine.state_manager import StateManager
        from backend.audio.audio_factory import build_audio_priority_queue
        
        state_manager = StateManager()
        audio_queue = build_audio_priority_queue(state_manager=state_manager)
        print("   ✓ AudioPriorityQueue created")
        
        # Enqueue decision (but don't start the worker to avoid audio device)
        audio_queue.enqueue(decision)
        print(f"   ✓ Decision enqueued to audio queue")
        print(f"      - Queue size: {audio_queue.qsize}")
    except Exception as exc:
        print(f"   ✗ Error: {exc}")
        import traceback
        traceback.print_exc()
        return
    
    # 6. Test dashboard manager
    print("\n6. Testing DashboardManager...")
    try:
        from backend.communication.dashboard_manager import DashboardManager
        dashboard_mgr = DashboardManager()
        print(f"   ✓ DashboardManager created")
        print(f"   ✓ Would broadcast inference to {dashboard_mgr.client_count} clients")
        print(f"   ✓ Would broadcast decision to {dashboard_mgr.client_count} clients")
    except Exception as exc:
        print(f"   ✗ Error: {exc}")
        import traceback
        traceback.print_exc()
        return
    
    # 7. Summary
    print("\n" + "="*70)
    print("✅ Pipeline Test Complete!")
    print("="*70)
    print("\nPipeline flow verified:")
    print(f"  Image → InferenceService → {len(raw_result.get('faces', []))} faces")
    print(f"                            → {len(raw_result.get('objects', []))} objects")
    print(f"  ↓")
    print(f"  DecisionEngine → priority {decision['priority_score']}: '{decision['alert_text']}'")
    print(f"  ↓")
    print(f"  AudioQueue → (ready for TTS)")
    print(f"  ↓")
    print(f"  DashboardManager → (would broadcast to browser clients)")
    print("\nAll components working correctly!")
    print()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_pipeline.py <image_path>")
        print("Example: python test_pipeline.py dataset/test_faces/Messi/messi.png")
        sys.exit(1)
    
    image_path = sys.argv[1]
    if not Path(image_path).exists():
        print(f"Error: Image not found: {image_path}")
        sys.exit(1)
    
    test_pipeline(image_path)
