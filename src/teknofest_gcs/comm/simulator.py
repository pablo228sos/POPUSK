from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import cos, pi, sin

from teknofest_gcs.core.models import GeoPoint, TelemetryData


@dataclass(slots=True)
class TelemetrySimulator:
    center: GeoPoint
    radius_deg: float = 0.003
    angular_speed: float = 0.035
    phase: float = 0.0

    def next(self) -> TelemetryData:
        self.phase = (self.phase + self.angular_speed) % (2 * pi)
        lat = self.center.lat + sin(self.phase) * self.radius_deg
        lon = self.center.lon + cos(self.phase) * self.radius_deg
        altitude = 110 + sin(self.phase * 2) * 20
        heading = (self.phase * 180 / pi + 90) % 360
        return TelemetryData(
            position=GeoPoint(lat=lat, lon=lon, altitude_m=altitude),
            ground_speed_mps=28 + abs(sin(self.phase * 1.5)) * 10,
            air_speed_mps=31 + abs(cos(self.phase * 1.25)) * 9,
            heading_deg=heading,
            pitch_deg=sin(self.phase) * 12,
            roll_deg=cos(self.phase) * 18,
            yaw_deg=heading,
            battery_percent=max(20, 100 - int(self.phase * 3)),
            battery_voltage=15.8 - self.phase / (2 * pi),
            mode="GUIDED",
            armed=True,
            autonomous=True,
            source="simulation",
            timestamp=datetime.now(timezone.utc),
        )
