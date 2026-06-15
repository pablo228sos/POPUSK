from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(slots=True)
class AppSettings:
    title: str = "Teknofest GCS"
    team_id: int = 1
    simulation: bool = True


@dataclass(slots=True)
class MapSettings:
    tile_url: str = "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
    attribution: str = "&copy; OpenStreetMap contributors"
    cache_path: str = ".cache/qtwebengine"
    center_lat: float = 39.925533
    center_lon: float = 32.866287
    zoom: int = 13
    competition_boundary_points: list[dict[str, float]] = field(default_factory=list)


@dataclass(slots=True)
class ConnectionSettings:
    transport: str = "simulation"
    serial_port: str = "COM3"
    baud_rate: int = 57600
    udp_endpoint: str = "udp:127.0.0.1:14550"
    heartbeat_timeout_sec: float = 3.0


@dataclass(slots=True)
class TeknofestApiSettings:
    enabled: bool = False
    base_url: str = "http://127.0.0.1:5000"
    username: str = ""
    password: str = ""
    session_file: str = ".runtime/teknofest_session.json"
    time_sync_period_sec: int = 10
    telemetry_period_sec: int = 1


@dataclass(slots=True)
class VideoSettings:
    source: str = ""
    output_dir: str = ".runtime/video"


@dataclass(slots=True)
class AiSettings:
    enabled: bool = False
    annotate_frames: bool = True
    onboard_companion: str = "Raspberry Pi + Hailo"
    follow_distance_m: float = 2.0


@dataclass(slots=True)
class LoggingSettings:
    output_dir: str = ".runtime/logs"
    telemetry_csv: str = "telemetry.csv"
    events_jsonl: str = "events.jsonl"


@dataclass(slots=True)
class SafetySettings:
    defense_action: str = "RTL"
    auto_reroute: bool = True
    mission_zone_required: bool = True
    fence_action: str = "RTL"
    fence_margin_m: float = 50.0
    manual_mode_limit: int = 3
    minimum_autonomous_ratio: float = 0.75


@dataclass(slots=True)
class AircraftSettings:
    autopilot: str = "ArduPlane"
    controller_board: str = "Matek H743-Wing"
    aircraft_name: str = "VTOL Talister"
    vehicle_class: str = "quadplane"
    vtol_type: str = "tailsitter"
    cruise_altitude_m: float = 120.0
    mission_takeoff_alt_m: float = 35.0
    mission_landing_alt_m: float = 0.0
    cruise_speed_mps: float = 24.0
    qguided_mode_enabled: bool = True
    qrtl_mode: int = 1
    mass_kg: float = 2.0
    max_thrust_n: float = 68.7
    drag_coefficient: float = 0.15
    frontal_area_m2: float = 0.05


@dataclass(slots=True)
class Settings:
    app: AppSettings
    map: MapSettings
    connection: ConnectionSettings
    teknofest_api: TeknofestApiSettings
    video: VideoSettings
    ai: AiSettings
    logging: LoggingSettings
    safety: SafetySettings
    aircraft: AircraftSettings

    @classmethod
    def default(cls) -> "Settings":
        return cls(
            app=AppSettings(),
            map=MapSettings(),
            connection=ConnectionSettings(),
            teknofest_api=TeknofestApiSettings(),
            video=VideoSettings(),
            ai=AiSettings(),
            logging=LoggingSettings(),
            safety=SafetySettings(),
            aircraft=AircraftSettings(),
        )

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "Settings":
        defaults = cls.default()
        return cls(
            app=AppSettings(**_merge(asdict(defaults.app), data.get("app", {}))),
            map=MapSettings(**_merge(asdict(defaults.map), data.get("map", {}))),
            connection=ConnectionSettings(**_merge(asdict(defaults.connection), data.get("connection", {}))),
            teknofest_api=TeknofestApiSettings(
                **_merge(asdict(defaults.teknofest_api), data.get("teknofest_api", {}))
            ),
            video=VideoSettings(**_merge(asdict(defaults.video), data.get("video", {}))),
            ai=AiSettings(**_merge(asdict(defaults.ai), data.get("ai", {}))),
            logging=LoggingSettings(**_merge(asdict(defaults.logging), data.get("logging", {}))),
            safety=SafetySettings(**_merge(asdict(defaults.safety), data.get("safety", {}))),
            aircraft=AircraftSettings(**_merge(asdict(defaults.aircraft), data.get("aircraft", {}))),
        )

    @classmethod
    def load(cls, path: str | Path) -> "Settings":
        path = Path(path)
        if not path.exists():
            settings = cls.default()
            settings.save(path)
            return settings
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return cls.from_mapping(data)

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = asdict(self)
        path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    merged.update(override)
    return merged
