import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from teknofest_gcs.core.models import GeoPoint, Zone, ZoneType
from teknofest_gcs.geo.planner import plan_route_a_star
from teknofest_gcs.geo.zones import ZoneMonitor, point_in_polygon, route_intersects_zone, zone_contains


class ZoneLogicTests(unittest.TestCase):
    def setUp(self) -> None:
        self.square = Zone(
            identifier="nfz",
            zone_type=ZoneType.NO_FLY,
            points=[
                GeoPoint(0.0, 0.0),
                GeoPoint(0.0, 1.0),
                GeoPoint(1.0, 1.0),
                GeoPoint(1.0, 0.0),
            ],
        )

    def test_point_in_polygon(self) -> None:
        self.assertTrue(point_in_polygon(GeoPoint(0.5, 0.5), self.square.points))
        self.assertFalse(point_in_polygon(GeoPoint(1.5, 0.5), self.square.points))

    def test_route_intersection_detected(self) -> None:
        route = [GeoPoint(-0.5, 0.5), GeoPoint(1.5, 0.5)]
        self.assertTrue(route_intersects_zone(route, self.square))

    def test_mission_zone_validation(self) -> None:
        mission = Zone(
            identifier="mission",
            zone_type=ZoneType.MISSION,
            center=GeoPoint(2.0, 2.0),
            radius_m=60,
        )
        monitor = ZoneMonitor([self.square, mission])
        route = [GeoPoint(-0.5, -0.5), GeoPoint(3.0, 3.0)]
        result = monitor.validate_route(route)
        self.assertTrue(result.intersects_forbidden_zone)
        self.assertTrue(result.missing_mission_zone)

    def test_route_outside_competition_boundary_detected(self) -> None:
        boundary = Zone(
            identifier="boundary",
            zone_type=ZoneType.COMPETITION,
            points=[
                GeoPoint(0.0, 0.0),
                GeoPoint(0.0, 2.0),
                GeoPoint(2.0, 2.0),
                GeoPoint(2.0, 0.0),
            ],
        )
        monitor = ZoneMonitor([boundary])
        route = [GeoPoint(0.5, 0.5), GeoPoint(2.5, 0.5)]
        result = monitor.validate_route(route)
        self.assertTrue(result.outside_competition_boundary)

    def test_a_star_detours_from_circle(self) -> None:
        defense = Zone(
            identifier="defense",
            zone_type=ZoneType.DEFENSE,
            center=GeoPoint(39.0, 32.0),
            radius_m=80,
        )
        start = GeoPoint(39.0, 31.998)
        goal = GeoPoint(39.0, 32.002)
        route = plan_route_a_star(start, goal, [defense], grid_step_m=20, padding_m=250)
        self.assertGreaterEqual(len(route), 2)
        for point in route[1:-1]:
            self.assertFalse(zone_contains(defense, point))


if __name__ == "__main__":
    unittest.main()
