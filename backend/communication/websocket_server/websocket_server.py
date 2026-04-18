import asyncio
import cv2
import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from core.frame_queue import FrameQueue

app = FastAPI()

# Initialize a FrameQueue with a maxsize. 
# According to the blueprint, we drop the oldest frames if the queue is full 
# to maintain a latency of < 200ms[cite: 107, 187].
frame_queue = FrameQueue(maxsize=5)

@app.websocket("/stream")
async def camera_stream(websocket: WebSocket):
    """
    Handles the binary WebSocket stream from the ESP32-CAM[cite: 107].
    """
    await websocket.accept()
    print("ESP32-CAM Connected")
    
    try:
        while True:
            # 1. Receive binary data from the WebSocket [cite: 107]
            data = await websocket.receive_bytes()
            
            # 2. Decode JPEG binary to NumPy array (OpenCV format) [cite: 107, 187]
            # np.frombuffer converts raw bytes to a 1D array
            # cv2.imdecode turns that buffer into a usable BGR image array
            frame = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
            
            if frame is not None:
                # 3. Place frame into the async queue [cite: 107]
                # We use put_nowait or a custom 'put' that drops old frames
                # to ensure we don't build up a backlog (latency management)
                try:
                    frame_queue.put_nowait(frame)
                except asyncio.QueueFull:
                    # Drop the oldest frame to make room for the fresh one [cite: 188]
                    _ = frame_queue.get_nowait()
                    frame_queue.put_nowait(frame)
                
                # The worker pool (Team B) will pick up frames from this queue 
                # and send them to your AI modules[cite: 113, 151].
                
    except WebSocketDisconnect:
        print("ESP32-CAM Disconnected")
    except Exception as e:
        print(f"Error in ingestion stream: {e}")