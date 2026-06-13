import unittest
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from teknofest_gcs.api.client import ApiError, build_telemetry_payload, gps_clock_payload, parse_server_time
from teknofest_gcs.core.models import GeoPoint, TargetInfo, TelemetryData


class ApiPayloadTests(unittest.TestCase):
    def test_payload_contains_expected_fields(self) -> None:
        now = datetime(2026, 4, 22, 10, 11, 12, 130000, tzinfo=timezone.utc)
        telemetry = TelemetryData(
            position=GeoPoint(41.1, 29.2, 120),
            ground_speed_mps=24.5,
            heading_deg=180,
            pitch_deg=5,
            roll_deg=-2,
            battery_percent=76,
            autonomous=True,
            timestamp=now,
        )
        payload = build_telemetry_payload(19, telemetry, now)
        self.assertEqual(payload["takim_numarasi"], 19)
        self.assertEqual(payload["iha_batarya"], 76)
        self.assertEqual(payload["gps_saati"]["milisaniye"], 130)

    def test_invalid_heading_rejected(self) -> None:
        telemetry = TelemetryData(position=GeoPoint(41.1, 29.2), heading_deg=420)
        with self.assertRaises(ApiError):
            build_telemetry_payload(1, telemetry, datetime.now(timezone.utc))

    def test_locked_target_requires_non_zero_dimensions(self) -> None:
        telemetry = TelemetryData(
            position=GeoPoint(41.1, 29.2),
            heading_deg=90,
            target=TargetInfo(locked=True),
        )
        with self.assertRaises(ApiError):
            build_telemetry_payload(1, telemetry, datetime.now(timezone.utc))

    def test_parse_server_time(self) -> None:
        parsed = parse_server_time(
            {"sunucusaati": {"gun": 22, "saat": 14, "dakika": 20, "saniye": 5, "milisaniye": 250}}
        )
        self.assertEqual(parsed.day, 22)
        self.assertEqual(parsed.hour, 14)
        self.assertEqual(parsed.minute, 20)

    def test_gps_clock_payload(self) -> None:
        payload = gps_clock_payload(datetime(2026, 4, 22, 14, 20, 5, 250000, tzinfo=timezone.utc))
        self.assertEqual(payload, {"saat": 14, "dakika": 20, "saniye": 5, "milisaniye": 250})


if __name__ == "__main__":
    unittest.main()
