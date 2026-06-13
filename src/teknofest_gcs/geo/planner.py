from __future__ import annotations

import heapq
from dataclasses import dataclass
from math import cos, radians, sqrt

from teknofest_gcs.core.models import GeoPoint, Zone, ZoneType
from teknofest_gcs.geo.zones import zone_contains


@dataclass(frozen=True, slots=True)
class GridNode:
    x: int
    y: int


def plan_route_a_star(
    start: GeoPoint,
    goal: GeoPoint,
    zones: list[Zone],
    grid_step_m: float = 40.0,
    padding_m: float = 150.0,
) -> list[GeoPoint]:
    min_lat = min(start.lat, goal.lat)
    max_lat = max(start.lat, goal.lat)
    min_lon = min(start.lon, goal.lon)
    max_lon = max(start.lon, goal.lon)
    lat_padding = padding_m / 111_111.0
    lon_padding = padding_m / (111_111.0 * max(cos(radians(start.lat)), 0.25))
    min_lat -= lat_padding
    max_lat += lat_padding
    min_lon -= lon_padding
    max_lon += lon_padding
    lat_step = grid_step_m / 111_111.0
    lon_step = grid_step_m / (111_111.0 * max(cos(radians(start.lat)), 0.25))

    width = max(3, int((max_lon - min_lon) / lon_step) + 1)
    height = max(3, int((max_lat - min_lat) / lat_step) + 1)

    def point_from_node(node: GridNode) -> GeoPoint:
        return GeoPoint(
            lat=min_lat + node.y * lat_step,
            lon=min_lon + node.x * lon_step,
        )

    def node_from_point(point: GeoPoint) -> GridNode:
        x = min(width - 1, max(0, int(round((point.lon - min_lon) / lon_step))))
        y = min(height - 1, max(0, int(round((point.lat - min_lat) / lat_step))))
        return GridNode(x=x, y=y)

    def blocked(node: GridNode) -> bool:
        point = point_from_node(node)
        return any(zone_contains(zone, point) for zone in zones if zone.zone_type in {ZoneType.NO_FLY, ZoneType.DEFENSE})

    start_node = node_from_point(start)
    goal_node = node_from_point(goal)
    if blocked(start_node) or blocked(goal_node):
        return [start, goal]

    def heuristic(a: GridNode, b: GridNode) -> float:
        return sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2)

    frontier: list[tuple[float, int, GridNode]] = [(0.0, 0, start_node)]
    came_from: dict[GridNode, GridNode | None] = {start_node: None}
    cost_so_far: dict[GridNode, float] = {start_node: 0.0}
    sequence = 1
    neighbors = [
        (-1, -1), (0, -1), (1, -1),
        (-1, 0),            (1, 0),
        (-1, 1),  (0, 1),   (1, 1),
    ]

    while frontier:
        _, _, current = heapq.heappop(frontier)
        if current == goal_node:
            break
        for dx, dy in neighbors:
            nx = current.x + dx
            ny = current.y + dy
            if not (0 <= nx < width and 0 <= ny < height):
                continue
            candidate = GridNode(nx, ny)
            if blocked(candidate):
                continue
            step_cost = sqrt(dx * dx + dy * dy)
            new_cost = cost_so_far[current] + step_cost
            if candidate not in cost_so_far or new_cost < cost_so_far[candidate]:
                cost_so_far[candidate] = new_cost
                priority = new_cost + heuristic(candidate, goal_node)
                heapq.heappush(frontier, (priority, sequence, candidate))
                sequence += 1
                came_from[candidate] = current

    if goal_node not in came_from:
        return [start, goal]

    nodes: list[GridNode] = []
    current = goal_node
    while current is not None:
        nodes.append(current)
        current = came_from[current]
    nodes.reverse()

    route = [start]
    route.extend(point_from_node(node) for node in nodes[1:-1])
    route.append(goal)
    return _compress_route(route, zones)


def _compress_route(route: list[GeoPoint], zones: list[Zone]) -> list[GeoPoint]:
    if len(route) <= 2:
        return route
    compressed = [route[0]]
    anchor = route[0]
    for index in range(2, len(route)):
        candidate = route[index]
        if any(_intersects_forbidden(anchor, candidate, zone) for zone in zones if zone.zone_type in {ZoneType.NO_FLY, ZoneType.DEFENSE}):
            anchor = route[index - 1]
            compressed.append(anchor)
    compressed.append(route[-1])
    return compressed


def _intersects_forbidden(a: GeoPoint, b: GeoPoint, zone: Zone) -> bool:
    steps = 12
    for index in range(steps + 1):
        t = index / steps
        point = GeoPoint(
            lat=a.lat + (b.lat - a.lat) * t,
            lon=a.lon + (b.lon - a.lon) * t,
        )
        if zone_contains(zone, point):
            return True
    return False
