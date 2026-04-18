from ultralytics import YOLO

class ObstacleDetector:
    def __init__(self):
        self.model = YOLO("ai_modules/object_detection/models/yolov8n.pt")

    def detect(self, frame):
        results = self.model(frame, conf=0.45, imgsz=416, verbose=False)

        detections = []

        for r in results[0].boxes:
            x1, y1, x2, y2 = r.xyxy[0].tolist()

            detections.append({
                "label": self.model.names[int(r.cls)],
                "confidence": float(r.conf),
                "bbox": [x1, y1, x2, y2],
                "distance_est": self._estimate_distance(y2 - y1)
            })

        return detections

    def _estimate_distance(self, h):
        if h > 300:
            return "very_close"
        elif h > 150:
            return "close"
        elif h > 70:
            return "medium"
        return "far"