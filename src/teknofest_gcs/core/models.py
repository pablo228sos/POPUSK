from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class ZoneType(str, Enum):
    NO_FLY = "no_fly"
    DEFENSE = "defense"
    MISSION = "mission"
    COMPETITION = "competition"


class ControlAuthority(str, Enum):
    MANUAL = "manual"
    AUTO = "auto"
    AI = "ai"


class MissionItemType(str, Enum):
    VTOL_TAKEOFF = "vtol_takeoff"
    WAYPOINT = "waypoint"
    VTOL_TRANSITION_FW = "vtol_transition_fw"
    VTOL_TRANSITION_MC = "vtol_transition_mc"
    LOITER = "loiter"
    VTOL_LAND = "vtol_land"
    RETURN_TO_LAUNCH = "rtl"


@dataclass(slots=True)
class GeoPoint:
    lat: float
    lon: float
    altitude_m: float = 0.0


@dataclass(slots=True)
class TargetInfo:
    center_x: int = 0
    center_y: int = 0
    width: int = 0
    height: int = 0
    locked: bool = False
    qr_text: str = ""


@dataclass(slots=True)
class TelemetryData:
    position: GeoPoint
    ground_speed_mps: float = 0.0
    air_speed_mps: float = 0.0
    heading_deg: float = 0.0
    pitch_deg: float = 0.0
    roll_deg: float = 0.0
    yaw_deg: float = 0.0
    battery_percent: int = 100
    battery_voltage: float = 16.0
    mode: str = "STANDBY"
    armed: bool = False
    autonomous: bool = False
    source: str = "simulation"
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    target: TargetInfo = field(default_factory=TargetInfo)


@dataclass(slots=True)
class OtherDrone:
    team_id: int
    position: GeoPoint
    heading_deg: float = 0.0
    latency_ms: int = 0
    name: str = ""


@dataclass(slots=True)
class Zone:
    identifier: str
    zone_type: ZoneType
    points: list[GeoPoint] = field(default_factory=list)
    center: GeoPoint | None = None
    radius_m: float | None = None
    label: str = ""

    @property
    def is_circle(self) -> bool:
        return self.center is not None and self.radius_m is not None


@dataclass(slots=True)
class RoutePlan:
    waypoints: list[GeoPoint]
    intersects_forbidden_zone: bool = False
    missing_mission_zone: bool = False
    outside_competition_boundary: bool = False


@dataclass(slots=True)
class MissionItem:
    item_type: MissionItemType
    point: GeoPoint
    speed_mps: float = 0.0
    loiter_sec: float = 0.0
    acceptance_radius_m: float = 20.0
    description: str = ""


@dataclass(slots=True)
class MissionPlan:
    name: str = "Combat Mission"
    items: list[MissionItem] = field(default_factory=list)
    uploaded: bool = False
    fence_uploaded: bool = False
    valid: bool = True
    validation_message: str = ""

    def route_points(self) -> list[GeoPoint]:
        return [item.point for item in self.items if item.item_type in {
            MissionItemType.VTOL_TAKEOFF,
            MissionItemType.WAYPOINT,
            MissionItemType.LOITER,
            MissionItemType.VTOL_LAND,
        }]


@dataclass(slots=True)
class AircraftProfile:
    autopilot: str = "ArduPlane"
    controller_board: str = "Matek H743-Wing"
    vehicle_class: str = "quadplane"
    vtol_type: str = "tailsitter"
    aircraft_name: str = "VTOL Talister"
    cruise_altitude_m: float = 120.0
    mission_takeoff_alt_m: float = 35.0
    mission_landing_alt_m: float = 0.0
    cruise_speed_mps: float = 24.0
    qguided_mode_enabled: bool = True
    qrtl_mode: int = 1
    follow_distance_m: float = 2.0
    follow_altitude_bias_m: float = 0.0


@dataclass(slots=True)
class AiFollowProfile:
    enabled: bool = False
    target_team_id: int | None = None
    follow_distance_m: float = 2.0
    capture_mode: str = "teknofest_telemetry"
    lock_required: bool = False


@dataclass(slots=True)
class ApiClock:
    server_time: datetime
    offset_seconds: float


@dataclass(slots=True)
class CompetitionStatus:
    manual_mode_switches: int = 0
    manual_mode_limit: int = 3
    flight_seconds: int = 0
    autonomous_seconds: int = 0
    defense_violation_seconds: int = 0
    out_of_bounds_seconds: int = 0

    @property
    def autonomy_ratio(self) -> float:
        if self.flight_seconds <= 0:
            return 0.0
        return self.autonomous_seconds / self.flight_seconds

    @property
    def manual_limit_exceeded(self) -> bool:
        return self.manual_mode_switches > self.manual_mode_limit
