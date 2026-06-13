from __future__ import annotations

import csv
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from teknofest_gcs.config.settings import LoggingSettings
from teknofest_gcs.core.models import TelemetryData


class LogService:
    def __init__(self, settings: LoggingSettings) -> None:
        self.output_dir = Path(settings.output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.telemetry_path = self.output_dir / settings.telemetry_csv
        self.events_path = self.output_dir / settings.events_jsonl
        self._telemetry_initialized = self.telemetry_path.exists()

    def log_event(self, event_type: str, message: str, **context: Any) -> None:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "message": message,
            "context": context,
        }
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def log_telemetry(self, telemetry: TelemetryData) -> None:
        row = {
            "timestamp": telemetry.timestamp.isoformat(),
            "lat": telemetry.position.lat,
            "lon": telemetry.position.lon,
            "altitude_m": telemetry.position.altitude_m,
            "ground_speed_mps": telemetry.ground_speed_mps,
            "air_speed_mps": telemetry.air_speed_mps,
            "heading_deg": telemetry.heading_deg,
            "pitch_deg": telemetry.pitch_deg,
            "roll_deg": telemetry.roll_deg,
            "yaw_deg": telemetry.yaw_deg,
            "battery_percent": telemetry.battery_percent,
            "battery_voltage": telemetry.battery_voltage,
            "mode": telemetry.mode,
            "armed": telemetry.armed,
            "autonomous": telemetry.autonomous,
            "source": telemetry.source,
            "target": json.dumps(asdict(telemetry.target), ensure_ascii=False),
        }
        with self.telemetry_path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(row.keys()))
            if not self._telemetry_initialized:
                writer.writeheader()
                self._telemetry_initialized = True
            writer.writerow(row)
