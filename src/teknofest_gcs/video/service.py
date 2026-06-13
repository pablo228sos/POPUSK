from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtGui import QImage

from teknofest_gcs.ai.processor import AiProcessor

try:
    import cv2
except ImportError:  # pragma: no cover - optional dependency at runtime
    cv2 = None


class VideoWorker(QThread):
    frame_ready = pyqtSignal(QImage)
    status_message = pyqtSignal(str)
    detections_updated = pyqtSignal(int)

    def __init__(self, source: str, output_dir: str, ai_processor: AiProcessor) -> None:
        super().__init__()
        self.source = source
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.ai_processor = ai_processor
        self._running = True
        self._recording = False
        self._writer = None
        self._last_frame = None

    def stop(self) -> None:
        self._running = False

    def set_source(self, source: str) -> None:
        self.source = source

    def start_recording(self) -> None:
        self._recording = True

    def stop_recording(self) -> None:
        self._recording = False
        if self._writer is not None:
            self._writer.release()
            self._writer = None

    def take_screenshot(self) -> str | None:
        if cv2 is None or self._last_frame is None:
            return None
        path = self.output_dir / f"screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        cv2.imwrite(str(path), self._last_frame)
        return str(path)

    def run(self) -> None:  # pragma: no cover - Qt thread
        if cv2 is None:
            self.status_message.emit("opencv-python is not installed")
            return
        capture = cv2.VideoCapture(self._resolve_source())
        if not capture.isOpened():
            self.status_message.emit(f"Video source unavailable: {self.source or '0'}")
            return

        self.status_message.emit("Video stream started")
        while self._running:
            ok, frame = capture.read()
            if not ok:
                continue
            processed, detections = self.ai_processor.process(frame)
            self._last_frame = processed
            self.detections_updated.emit(detections)
            self._write_frame_if_needed(processed)
            image = self._to_qimage(processed)
            self.frame_ready.emit(image)

        capture.release()
        self.stop_recording()
        self.status_message.emit("Video stream stopped")

    def _resolve_source(self):
        if not self.source:
            return 0
        if self.source.isdigit():
            return int(self.source)
        return self.source

    def _write_frame_if_needed(self, frame) -> None:
        if not self._recording or cv2 is None:
            return
        if self._writer is None:
            path = self.output_dir / f"recording_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
            h, w = frame.shape[:2]
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            self._writer = cv2.VideoWriter(str(path), fourcc, 20.0, (w, h))
            self.status_message.emit(f"Recording to {path}")
        self._writer.write(frame)

    @staticmethod
    def _to_qimage(frame) -> QImage:
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        return QImage(rgb.data, w, h, ch * w, QImage.Format.Format_RGB888).copy()
