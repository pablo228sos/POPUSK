from __future__ import annotations

from dataclasses import dataclass
from math import atan2, cos, degrees, radians, sin, sqrt

from teknofest_gcs.core.models import GeoPoint, RoutePlan, Zone, ZoneType


EARTH_RADIUS_M = 6_371_000.0


def haversine_distance_m(a: GeoPoint, b: GeoPoint) -> float:
    lat1 = radians(a.lat)
    lon1 = radians(a.lon)
    lat2 = radians(b.lat)
    lon2 = radians(b.lon)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_M * atan2(sqrt(h), sqrt(1 - h))


def bearing_deg(a: GeoPoint, b: GeoPoint) -> float:
    lat1 = radians(a.lat)
    lat2 = radians(b.lat)
    dlon = radians(b.lon - a.lon)
    y = sin(dlon) * cos(lat2)
    x = cos(lat1) * sin(lat2) - sin(lat1) * cos(lat2) * cos(dlon)
    return (degrees(atan2(y, x)) + 360.0) % 360.0


def offset_point(point: GeoPoint, distance_m: float, bearing_degrees: float, altitude_m: float | None = None) -> GeoPoint:
    bearing = radians(bearing_degrees)
    lat1 = radians(point.lat)
    lon1 = radians(point.lon)
    angular_distance = distance_m / EARTH_RADIUS_M

    sin_lat2 = sin(lat1) * cos(angular_distance) + cos(lat1) * sin(angular_distance) * cos(bearing)
    lat2 = atan2(sin_lat2, sqrt(max(0.0, 1.0 - sin_lat2 * sin_lat2)))
    lon2 = lon1 + atan2(
        sin(bearing) * sin(angular_distance) * cos(lat1),
        cos(angular_distance) - sin(lat1) * sin(lat2),
    )
    return GeoPoint(
        lat=degrees(lat2),
        lon=degrees(lon2),
        altitude_m=point.altitude_m if altitude_m is None else altitude_m,
    )


def approximate_circle(center: GeoPoint, radius_m: float, segments: int = 18) -> list[GeoPoint]:
    return [
        offset_point(center, radius_m, bearing, altitude_m=center.altitude_m)
        for bearing in [index * (360.0 / segments) for index in range(segments)]
    ]


def point_in_polygon(point: GeoPoint, polygon: list[GeoPoint]) -> bool:
    crossings = 0
    for index in range(len(polygon)):
        a = polygon[index]
        b = polygon[(index + 1) % len(polygon)]
        if ((a.lon > point.lon) != (b.lon > point.lon)):
            slope = (b.lat - a.lat) / (b.lon - a.lon)
            intersect_lat = slope * (point.lon - a.lon) + a.lat
            if point.lat < intersect_lat:
                crossings += 1
    return crossings % 2 == 1


def zone_contains(zone: Zone, point: GeoPoint) -> bool:
    if zone.is_circle and zone.center is not None and zone.radius_m is not None:
        return haversine_distance_m(zone.center, point) <= zone.radius_m
    return point_in_polygon(point, zone.points)


def segment_intersects_zone(a: GeoPoint, b: GeoPoint, zone: Zone, samples: int = 24) -> bool:
    for probe in sample_segment(a, b, samples):
        if zone_contains(zone, probe):
            return True
    return False


def route_intersects_zone(waypoints: list[GeoPoint], zone: Zone) -> bool:
    if len(waypoints) < 2:
        return False
    return any(segment_intersects_zone(waypoints[i], waypoints[i + 1], zone) for i in range(len(waypoints) - 1))


def sample_segment(a: GeoPoint, b: GeoPoint, samples: int = 24) -> list[GeoPoint]:
    return [
        GeoPoint(
            lat=a.lat + (b.lat - a.lat) * alpha,
            lon=a.lon + (b.lon - a.lon) * alpha,
            altitude_m=a.altitude_m + (b.altitude_m - a.altitude_m) * alpha,
        )
        for alpha in [step / samples for step in range(samples + 1)]
    ]


def route_within_boundary(waypoints: list[GeoPoint], boundary: Zone, samples: int = 24) -> bool:
    if len(waypoints) < 2:
        return all(zone_contains(boundary, waypoint) for waypoint in waypoints)
    for index in range(len(waypoints) - 1):
        probes = sample_segment(waypoints[index], waypoints[index + 1], samples)
        if not all(zone_contains(boundary, probe) for probe in probes):
            return False
    return True


@dataclass(slots=True)
class ZoneEvaluation:
    violated_zones: list[Zone]
    mission_zones_reached: set[str]
    outside_boundary: bool = False

    @property
    def has_defense_violation(self) -> bool:
        return any(zone.zone_type == ZoneType.DEFENSE for zone in self.violated_zones)

    @property
    def has_no_fly_violation(self) -> bool:
        return any(zone.zone_type == ZoneType.NO_FLY for zone in self.violated_zones)


class ZoneMonitor:
    def __init__(self, zones: list[Zone] | None = None) -> None:
        self._zones: list[Zone] = zones or []

    @property
    def zones(self) -> list[Zone]:
        return list(self._zones)

    def set_zones(self, zones: list[Zone]) -> None:
        self._zones = list(zones)

    def evaluate_position(self, point: GeoPoint) -> ZoneEvaluation:
        competition_boundaries = [zone for zone in self._zones if zone.zone_type == ZoneType.COMPETITION]
        violated = [
            zone
            for zone in self._zones
            if zone.zone_type != ZoneType.COMPETITION and zone_contains(zone, point)
        ]
        reached = {zone.identifier for zone in violated if zone.zone_type == ZoneType.MISSION}
        outside_boundary = bool(competition_boundaries) and not any(
            zone_contains(zone, point) for zone in competition_boundaries
        )
        return ZoneEvaluation(
            violated_zones=violated,
            mission_zones_reached=reached,
            outside_boundary=outside_boundary,
        )

    def validate_route(self, waypoints: list[GeoPoint]) -> RoutePlan:
        forbidden = any(
            route_intersects_zone(waypoints, zone) for zone in self._zones if zone.zone_type in {ZoneType.NO_FLY, ZoneType.DEFENSE}
        )
        mission_zones = [zone for zone in self._zones if zone.zone_type == ZoneType.MISSION]
        competition_boundaries = [zone for zone in self._zones if zone.zone_type == ZoneType.COMPETITION]
        reached = {
            zone.identifier
            for zone in mission_zones
            if any(zone_contains(zone, waypoint) for waypoint in waypoints)
        }
        outside_boundary = bool(competition_boundaries) and not any(
            route_within_boundary(waypoints, boundary) for boundary in competition_boundaries
        )
        return RoutePlan(
            waypoints=list(waypoints),
            intersects_forbidden_zone=forbidden,
            missing_mission_zone=len(reached) != len(mission_zones) if mission_zones else False,
            outside_competition_boundary=outside_boundary,
        )
