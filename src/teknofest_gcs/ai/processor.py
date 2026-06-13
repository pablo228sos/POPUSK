from __future__ import annotations

import numpy as np

try:
    import cv2
except ImportError:  # pragma: no cover - optional dependency at runtime
    cv2 = None


class AiProcessor:
    def __init__(self, enabled: bool = False, annotate_frames: bool = True) -> None:
        self.enabled = enabled
        self.annotate_frames = annotate_frames

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled

    def process(self, frame: np.ndarray) -> tuple[np.ndarray, int]:
        if not self.enabled or cv2 is None:
            return frame, 0

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(blurred, 70, 160)
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        annotated = frame.copy()
        detections = 0
        for contour in contours[:10]:
            x, y, w, h = cv2.boundingRect(contour)
            area = w * h
            if area < 500:
                continue
            detections += 1
            if self.annotate_frames:
                cv2.rectangle(annotated, (x, y), (x + w, y + h), (0, 220, 255), 2)

        if self.annotate_frames:
            cv2.putText(
                annotated,
                f"AI {'ON' if self.enabled else 'OFF'} | targets: {detections}",
                (16, 28),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (30, 250, 160),
                2,
                cv2.LINE_AA,
            )
        return annotated, detections
