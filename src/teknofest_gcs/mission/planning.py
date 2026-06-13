from __future__ import annotations

from dataclasses import dataclass

from teknofest_gcs.core.models import GeoPoint, MissionItemType, MissionPlan, Zone, ZoneType
from teknofest_gcs.geo.zones import ZoneMonitor, approximate_circle


@dataclass(slots=True)
class MissionValidation:
    valid: bool
    message: str
    route_points: list[GeoPoint]


@dataclass(slots=True)
class AutopilotFencePlan:
    return_point: GeoPoint
    inclusion_boundary: list[GeoPoint]
    exclusion_polygons: list[list[GeoPoint]]


def mission_route_points(plan: MissionPlan) -> list[GeoPoint]:
    return plan.route_points()


def validate_mission_plan(plan: MissionPlan, zone_monitor: ZoneMonitor, mission_zone_required: bool = True) -> MissionValidation:
    route = mission_route_points(plan)
    if not route:
        return MissionValidation(valid=False, message="Mission has no route points", route_points=[])
    validation = zone_monitor.validate_route(route)
    if validation.intersects_forbidden_zone:
        return MissionValidation(valid=False, message="Mission intersects a forbidden zone", route_points=route)
    if validation.outside_competition_boundary:
        return MissionValidation(
            valid=False,
            message="Mission exits the competition boundary",
            route_points=route,
        )
    if mission_zone_required and validation.missing_mission_zone:
        return MissionValidation(valid=False, message="Mission does not pass through all mission zones", route_points=route)
    if plan.items[0].item_type != MissionItemType.VTOL_TAKEOFF:
        return MissionValidation(valid=False, message="First mission item must be VTOL takeoff", route_points=route)
    if plan.items[-1].item_type not in {MissionItemType.VTOL_LAND, MissionItemType.RETURN_TO_LAUNCH}:
        return MissionValidation(valid=False, message="Last mission item must be VTOL land or RTL", route_points=route)
    return MissionValidation(valid=True, message="Mission validated", route_points=route)


def build_autopilot_fence_plan(
    zones: list[Zone],
    mission_plan: MissionPlan,
    home: GeoPoint,
    padding_deg: float = 0.004,
) -> AutopilotFencePlan:
    route_points = mission_route_points(mission_plan) or [home]
    all_points = [home, *route_points]
    exclusion_polygons: list[list[GeoPoint]] = []
    competition_boundaries: list[list[GeoPoint]] = []

    for zone in zones:
        if zone.is_circle and zone.center is not None and zone.radius_m is not None:
            polygon = approximate_circle(zone.center, zone.radius_m, segments=18)
        else:
            polygon = list(zone.points)
        if zone.zone_type == ZoneType.COMPETITION:
            competition_boundaries.append(_closed_polygon(polygon))
            all_points.extend(polygon)
            continue
        if zone.zone_type not in {ZoneType.NO_FLY, ZoneType.DEFENSE}:
            continue
        exclusion_polygons.append(_closed_polygon(polygon))
        all_points.extend(polygon)

    if competition_boundaries:
        inclusion_boundary = competition_boundaries[0]
    else:
        min_lat = min(point.lat for point in all_points) - padding_deg
        max_lat = max(point.lat for point in all_points) + padding_deg
        min_lon = min(point.lon for point in all_points) - padding_deg
        max_lon = max(point.lon for point in all_points) + padding_deg
        inclusion_boundary = _closed_polygon([
            GeoPoint(min_lat, min_lon),
            GeoPoint(min_lat, max_lon),
            GeoPoint(max_lat, max_lon),
            GeoPoint(max_lat, min_lon),
        ])
    return AutopilotFencePlan(
        return_point=home,
        inclusion_boundary=inclusion_boundary,
        exclusion_polygons=exclusion_polygons,
    )


def _closed_polygon(points: list[GeoPoint]) -> list[GeoPoint]:
    if not points:
        return []
    if points[0].lat == points[-1].lat and points[0].lon == points[-1].lon:
        return list(points)
    return [*points, points[0]]
