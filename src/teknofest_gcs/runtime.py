from __future__ import annotations

import asyncio
import threading
from concurrent.futures import Future
from datetime import datetime, timezone

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from teknofest_gcs.api.client import TeknofestApiClient, TelemetryRateLimiter
from teknofest_gcs.comm.mavlink import MavlinkWorker
from teknofest_gcs.comm.simulator import TelemetrySimulator
from teknofest_gcs.config.settings import Settings
from teknofest_gcs.core.models import (
    AiFollowProfile,
    CompetitionStatus,
    ControlAuthority,
    GeoPoint,
    MissionItem,
    MissionItemType,
    MissionPlan,
    OtherDrone,
    TelemetryData,
    Zone,
    ZoneType,
)
from teknofest_gcs.geo.planner import plan_route_a_star
from teknofest_gcs.geo.zones import ZoneMonitor, bearing_deg, haversine_distance_m, offset_point
from teknofest_gcs.logging.service import LogService
from teknofest_gcs.mission.fsm import InvalidTransitionError, MissionEvent, MissionStateMachine
from teknofest_gcs.mission.planning import build_autopilot_fence_plan, validate_mission_plan


class AsyncioRunner:
    def __init__(self) -> None:
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._bootstrap, daemon=True)
        self._thread.start()
        self._ready.wait(timeout=5)

    def _bootstrap(self) -> None:
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self._ready.set()
        self.loop.run_forever()

    def submit(self, coro) -> Future:
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    def shutdown(self) -> None:
        if hasattr(self, "loop"):
            self.loop.call_soon_threadsafe(self.loop.stop)
            self._thread.join(timeout=2)


class GcsRuntime(QObject):
    telemetry_updated = pyqtSignal(object)
    other_drones_updated = pyqtSignal(object)
    zones_updated = pyqtSignal(object)
    route_updated = pyqtSignal(object)
    mission_plan_changed = pyqtSignal(object)
    mission_state_changed = pyqtSignal(str)
    control_authority_changed = pyqtSignal(str)
    competition_status_changed = pyqtSignal(object)
    log_message = pyqtSignal(str)
    api_status_changed = pyqtSignal(str)
    connection_changed = pyqtSignal(bool)

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings
        self.log_service = LogService(settings.logging)
        self.state_machine = MissionStateMachine()
        self.zone_monitor = ZoneMonitor()
        self.telemetry: TelemetryData | None = None
        self.other_drones: list[OtherDrone] = []
        self.route: list[GeoPoint] = []
        self.competition_boundary: Zone | None = None
        self.user_zones: list[Zone] = []
        self.hss_zones: list[Zone] = []
        self.mission_plan = MissionPlan(name=f"{settings.aircraft.aircraft_name} Mission")
        self.control_authority = ControlAuthority.MANUAL
        self.ai_follow = AiFollowProfile(follow_distance_m=settings.ai.follow_distance_m)
        self.ai_enabled = settings.ai.enabled
        self.competition_status = CompetitionStatus(manual_mode_limit=settings.safety.manual_mode_limit)
        self._defense_violation_active = False
        self._no_fly_violation_active = False
        self._out_of_bounds_active = False

        self._simulation = TelemetrySimulator(
            center=GeoPoint(lat=settings.map.center_lat, lon=settings.map.center_lon)
        )
        self._simulation_timer = QTimer(self)
        self._simulation_timer.setInterval(200)
        self._simulation_timer.timeout.connect(self._tick_simulation)

        self._watchdog_timer = QTimer(self)
        self._watchdog_timer.setInterval(1000)
        self._watchdog_timer.timeout.connect(self._watchdog_check)

        self._api_timer = QTimer(self)
        self._api_timer.setInterval(settings.teknofest_api.telemetry_period_sec * 1000)
        self._api_timer.timeout.connect(self._send_teknofest_telemetry)

        self._time_sync_timer = QTimer(self)
        self._time_sync_timer.setInterval(settings.teknofest_api.time_sync_period_sec * 1000)
        self._time_sync_timer.timeout.connect(self._sync_server_time)

        self._ai_follow_timer = QTimer(self)
        self._ai_follow_timer.setInterval(800)
        self._ai_follow_timer.timeout.connect(self._tick_ai_follow)

        self._competition_timer = QTimer(self)
        self._competition_timer.setInterval(1000)
        self._competition_timer.timeout.connect(self._tick_competition_status)

        self._last_telemetry_at: datetime | None = None
        self._rate_limiter = TelemetryRateLimiter(settings.teknofest_api.telemetry_period_sec)

        self._runner = AsyncioRunner() if settings.teknofest_api.enabled else None
        self._api_client = TeknofestApiClient(settings.teknofest_api) if settings.teknofest_api.enabled else None
        self._mavlink_worker: MavlinkWorker | None = None
        self._load_competition_boundary_from_settings()

    def start(self) -> None:
        if self.settings.connection.transport == "simulation" or self.settings.app.simulation:
            self.load_demo_zones()
            self._transition(MissionEvent.LINK_ESTABLISHED)
            self._simulation_timer.start()
            self.connection_changed.emit(True)
            self._log("Simulation telemetry started")
        else:
            self._start_mavlink()

        self._watchdog_timer.start()
        self._competition_timer.start()
        if self._api_client is not None and self._runner is not None:
            self._connect_teknofest_api()
            self._api_timer.start()
            self._time_sync_timer.start()
        self.control_authority_changed.emit(self.control_authority.value)
        self.competition_status_changed.emit(self.competition_status)

    def stop(self) -> None:
        self._simulation_timer.stop()
        self._watchdog_timer.stop()
        self._api_timer.stop()
        self._time_sync_timer.stop()
        self._ai_follow_timer.stop()
        self._competition_timer.stop()
        if self._mavlink_worker is not None:
            self._mavlink_worker.stop()
            self._mavlink_worker.wait(1000)
        if self._runner is not None and self._api_client is not None:
            close_future = self._runner.submit(self._api_client.close())
            close_future.result(timeout=3)
            self._runner.shutdown()

    def arm(self) -> None:
        if not self._is_flight_active():
            self._reset_competition_status()
        self._transition(MissionEvent.ARM)
        if self.telemetry is not None:
            self.telemetry.armed = True
            self.telemetry.mode = "ARMED"
            self.telemetry_updated.emit(self.telemetry)
        if self._mavlink_worker is not None:
            self._mavlink_worker.queue_arm()

    def disarm(self) -> None:
        self._transition(MissionEvent.DISARM)
        if self.telemetry is not None:
            self.telemetry.armed = False
            self.telemetry.mode = "STANDBY"
            self.telemetry_updated.emit(self.telemetry)
        if self._mavlink_worker is not None:
            self._mavlink_worker.queue_disarm()

    def set_control_authority(self, authority: ControlAuthority) -> None:
        self.control_authority = authority
        self.control_authority_changed.emit(authority.value)
        self._log(f"Control authority set to {authority.value}")

    def set_flight_mode(self, mode: str) -> None:
        if self.telemetry is not None:
            self.telemetry.mode = mode
            self.telemetry.autonomous = mode in {"AUTO", "GUIDED", "RTL", "QRTL", "QLAND", "MISSION"}
            self.telemetry_updated.emit(self.telemetry)
        if self._mavlink_worker is not None:
            self._mavlink_worker.queue_mode(mode)
        self._log(f"Flight mode requested: {mode}")

    def set_manual_mode(self, mode: str = "QSTABILIZE") -> None:
        if self.control_authority != ControlAuthority.MANUAL and self._is_flight_active():
            self.competition_status.manual_mode_switches += 1
            self.competition_status_changed.emit(self.competition_status)
        self.set_control_authority(ControlAuthority.MANUAL)
        self.ai_follow.enabled = False
        self._ai_follow_timer.stop()
        self.set_flight_mode(mode)

    def set_auto_mode(self) -> None:
        self.set_control_authority(ControlAuthority.AUTO)
        self.ai_follow.enabled = False
        self._ai_follow_timer.stop()
        self.set_flight_mode("AUTO")

    def engage_ai_follow(self, team_id: int | None) -> None:
        self.ai_follow.enabled = True
        self.ai_follow.target_team_id = team_id
        self.ai_follow.follow_distance_m = self.settings.ai.follow_distance_m
        self.set_control_authority(ControlAuthority.AI)
        self.configure_competition_profile()
        self.set_flight_mode("GUIDED")
        self._ai_follow_timer.start()
        self._log(f"AI follow engaged for target team {team_id if team_id is not None else 'auto'}")

    def disable_ai_follow(self) -> None:
        self.ai_follow.enabled = False
        self._ai_follow_timer.stop()
        if self.control_authority == ControlAuthority.AI:
            self.set_manual_mode()
        self._log("AI follow disabled")

    def set_ai_enabled(self, enabled: bool) -> None:
        self.ai_enabled = enabled
        self.settings.ai.enabled = enabled
        self._log(f"AI {'enabled' if enabled else 'disabled'}")

    def update_settings(self, settings: Settings) -> None:
        self.settings = settings
        self.ai_follow.follow_distance_m = settings.ai.follow_distance_m
        self.competition_status.manual_mode_limit = settings.safety.manual_mode_limit
        self._load_competition_boundary_from_settings()
        self._log("Settings updated")

    def set_competition_boundary(self, points: list[GeoPoint]) -> None:
        if len(points) < 3:
            return
        self.competition_boundary = Zone(
            identifier="competition-boundary",
            zone_type=ZoneType.COMPETITION,
            points=list(points),
            label="Competition Boundary",
        )
        self.settings.map.competition_boundary_points = [
            {"lat": point.lat, "lon": point.lon}
            for point in points
        ]
        self._rebuild_zone_monitor()
        self._log("Competition boundary updated")

    def clear_competition_boundary(self) -> None:
        self.competition_boundary = None
        self.settings.map.competition_boundary_points = []
        self._rebuild_zone_monitor()
        self._log("Competition boundary cleared")

    def configure_competition_profile(self) -> None:
        if self._mavlink_worker is not None:
            self._mavlink_worker.queue_configure_profile((self.settings.aircraft, self.settings.safety))
        self._log(
            f"Competition profile ready for {self.settings.aircraft.aircraft_name} "
            f"({self.settings.aircraft.controller_board})"
        )

    def add_mission_item(self, item: MissionItem) -> None:
        self.mission_plan.items.append(item)
        self.mission_plan.uploaded = False
        self._refresh_mission_state()

    def add_takeoff_item(self, altitude_m: float | None = None) -> None:
        base = self.home_point()
        self.add_mission_item(
            MissionItem(
                item_type=MissionItemType.VTOL_TAKEOFF,
                point=GeoPoint(base.lat, base.lon, altitude_m or self.settings.aircraft.mission_takeoff_alt_m),
                speed_mps=self.settings.aircraft.cruise_speed_mps,
                description="VTOL takeoff",
            )
        )

    def add_waypoint(self, point: GeoPoint, altitude_m: float | None = None) -> None:
        self.add_mission_item(
            MissionItem(
                item_type=MissionItemType.WAYPOINT,
                point=GeoPoint(point.lat, point.lon, altitude_m or self.settings.aircraft.cruise_altitude_m),
                speed_mps=self.settings.aircraft.cruise_speed_mps,
                description="Waypoint",
            )
        )

    def add_loiter(self, point: GeoPoint, altitude_m: float | None = None, loiter_sec: float = 10.0) -> None:
        self.add_mission_item(
            MissionItem(
                item_type=MissionItemType.LOITER,
                point=GeoPoint(point.lat, point.lon, altitude_m or self.settings.aircraft.cruise_altitude_m),
                loiter_sec=loiter_sec,
                description="VTOL hold / loiter",
            )
        )

    def add_vtol_land(self, point: GeoPoint) -> None:
        self.add_mission_item(
            MissionItem(
                item_type=MissionItemType.VTOL_LAND,
                point=GeoPoint(point.lat, point.lon, self.settings.aircraft.mission_landing_alt_m),
                description="VTOL land",
            )
        )

    def add_rtl(self) -> None:
        base = self.home_point()
        self.add_mission_item(
            MissionItem(
                item_type=MissionItemType.RETURN_TO_LAUNCH,
                point=GeoPoint(base.lat, base.lon, 0.0),
                description="Return to launch",
            )
        )

    def clear_mission(self) -> None:
        self.mission_plan.items.clear()
        self.mission_plan.uploaded = False
        self.route = []
        self.route_updated.emit(self.route)
        self._refresh_mission_state()
        self._log("Mission cleared")

    def upload_mission(self) -> bool:
        self._refresh_mission_state()
        if not self.mission_plan.valid:
            self._log(f"Mission upload blocked: {self.mission_plan.validation_message}")
            return False
        if self._mavlink_worker is None:
            self.mission_plan.uploaded = True
            self._refresh_mission_state()
            self._log("Mission marked as uploaded in simulation mode")
            return True
        self.configure_competition_profile()
        self._mavlink_worker.queue_upload_mission(self.mission_plan)
        self._log("Mission upload queued")
        return True

    def add_zone(self, zone: Zone) -> None:
        self.user_zones.append(zone)
        self._rebuild_zone_monitor()
        self._log(f"Zone added: {zone.label or zone.identifier}")

    def clear_user_zones(self) -> None:
        self.user_zones.clear()
        self._rebuild_zone_monitor()
        self._log("User zones cleared")

    def upload_fence(self) -> bool:
        if self._mavlink_worker is None:
            self._log("Fence upload skipped in simulation mode")
            return False
        fence_plan = build_autopilot_fence_plan(
            zones=self.zone_monitor.zones,
            mission_plan=self.mission_plan,
            home=self.home_point(),
        )
        self.configure_competition_profile()
        self._mavlink_worker.queue_upload_fence(fence_plan)
        self._log("Fence upload queued")
        return True

    def start_mission(self) -> None:
        self._transition(MissionEvent.START_MISSION)
        self.set_auto_mode()
        self._log("Mission started")

    def trigger_rtl(self, reason: str = "manual") -> None:
        self._transition(MissionEvent.TRIGGER_RTL)
        self.set_flight_mode("QRTL" if self.settings.aircraft.vehicle_class == "quadplane" else "RTL")
        self._log(f"RTL triggered: {reason}")

    def trigger_qland(self, reason: str = "manual") -> None:
        self.set_control_authority(ControlAuthority.AUTO)
        self.set_flight_mode("QLAND")
        self._log(f"QLAND triggered: {reason}")

    def plan_demo_route(self) -> None:
        if self.telemetry is None:
            return
        goal = GeoPoint(
            lat=self.settings.map.center_lat + 0.006,
            lon=self.settings.map.center_lon - 0.004,
            altitude_m=self.settings.aircraft.cruise_altitude_m,
        )
        self.route = plan_route_a_star(self.telemetry.position, goal, self.zone_monitor.zones)
        self.route_updated.emit(self.route)
        self._log("Avoidance route recalculated")

    def refresh_hss(self) -> None:
        if self._api_client is None or self._runner is None:
            return
        future = self._runner.submit(self._api_client.fetch_hss_zones())
        future.add_done_callback(self._handle_hss_result)

    def home_point(self) -> GeoPoint:
        if self.telemetry is not None:
            return GeoPoint(
                lat=self.telemetry.position.lat,
                lon=self.telemetry.position.lon,
                altitude_m=self.telemetry.position.altitude_m,
            )
        return GeoPoint(
            lat=self.settings.map.center_lat,
            lon=self.settings.map.center_lon,
            altitude_m=0.0,
        )

    def load_demo_zones(self) -> None:
        if self.competition_boundary is None:
            self.competition_boundary = Zone(
                identifier="competition-boundary",
                zone_type=ZoneType.COMPETITION,
                points=[
                    GeoPoint(self.settings.map.center_lat - 0.010, self.settings.map.center_lon - 0.012),
                    GeoPoint(self.settings.map.center_lat - 0.010, self.settings.map.center_lon + 0.012),
                    GeoPoint(self.settings.map.center_lat + 0.010, self.settings.map.center_lon + 0.012),
                    GeoPoint(self.settings.map.center_lat + 0.010, self.settings.map.center_lon - 0.012),
                ],
                label="Competition Boundary",
            )
        self.user_zones = [
            Zone(
                identifier="nfz-1",
                zone_type=ZoneType.NO_FLY,
                points=[
                    GeoPoint(self.settings.map.center_lat + 0.001, self.settings.map.center_lon - 0.004),
                    GeoPoint(self.settings.map.center_lat + 0.004, self.settings.map.center_lon - 0.002),
                    GeoPoint(self.settings.map.center_lat + 0.003, self.settings.map.center_lon + 0.001),
                    GeoPoint(self.settings.map.center_lat, self.settings.map.center_lon),
                ],
                label="No-Fly Alpha",
            ),
            Zone(
                identifier="mission-1",
                zone_type=ZoneType.MISSION,
                center=GeoPoint(self.settings.map.center_lat + 0.005, self.settings.map.center_lon + 0.003),
                radius_m=120,
                label="Mission Corridor",
            ),
        ]
        self.hss_zones = [
            Zone(
                identifier="def-1",
                zone_type=ZoneType.DEFENSE,
                center=GeoPoint(self.settings.map.center_lat - 0.003, self.settings.map.center_lon + 0.003),
                radius_m=90,
                label="Defense Zone",
            ),
        ]
        self._rebuild_zone_monitor()

    def _start_mavlink(self) -> None:
        self._mavlink_worker = MavlinkWorker(self.settings.connection)
        self._mavlink_worker.telemetry_received.connect(self._ingest_telemetry)
        self._mavlink_worker.status_message.connect(self._log)
        self._mavlink_worker.link_state_changed.connect(self._handle_link_state)
        self._mavlink_worker.mission_uploaded.connect(self._handle_mission_uploaded)
        self._mavlink_worker.fence_uploaded.connect(self._handle_fence_uploaded)
        self._mavlink_worker.guided_target_sent.connect(
            lambda point: self._log(
                f"Guided target sent: {point.lat:.6f}, {point.lon:.6f}, {point.altitude_m:.1f} m"
            )
        )
        self._mavlink_worker.start()

    def _tick_simulation(self) -> None:
        self._ingest_telemetry(self._simulation.next())

    def _ingest_telemetry(self, telemetry: TelemetryData) -> None:
        self.telemetry = telemetry
        self._last_telemetry_at = datetime.now(timezone.utc)
        evaluation = self.zone_monitor.evaluate_position(telemetry.position)
        if evaluation.has_defense_violation and not self._defense_violation_active:
            if self.settings.safety.defense_action.upper() == "RTL":
                self.trigger_rtl("entered defense zone")
            else:
                self.trigger_qland("entered defense zone")
            self._log("Defense/HSS violation detected")
        if evaluation.has_no_fly_violation and not self._no_fly_violation_active and self.settings.safety.auto_reroute:
            self.plan_demo_route()
            self._log("No-fly avoidance reroute triggered")
        if evaluation.outside_boundary and not self._out_of_bounds_active:
            self._log("Competition boundary violation detected")
        self._defense_violation_active = evaluation.has_defense_violation
        self._no_fly_violation_active = evaluation.has_no_fly_violation
        self._out_of_bounds_active = evaluation.outside_boundary
        self.telemetry_updated.emit(telemetry)
        self.log_service.log_telemetry(telemetry)

    def _watchdog_check(self) -> None:
        if self._last_telemetry_at is None:
            return
        age = (datetime.now(timezone.utc) - self._last_telemetry_at).total_seconds()
        if age > self.settings.connection.heartbeat_timeout_sec:
            self._transition(MissionEvent.LINK_LOST)
            self.trigger_rtl("watchdog timeout")

    def _tick_ai_follow(self) -> None:
        if not self.ai_follow.enabled or self.telemetry is None or self._mavlink_worker is None:
            return
        target = self._resolve_ai_target()
        if target is None:
            return
        heading = target.heading_deg
        if heading <= 0.0:
            heading = bearing_deg(self.telemetry.position, target.position)
        desired = offset_point(
            target.position,
            self.ai_follow.follow_distance_m,
            (heading + 180.0) % 360.0,
            altitude_m=target.position.altitude_m,
        )
        if haversine_distance_m(self.telemetry.position, desired) < 1.0:
            return
        self._mavlink_worker.queue_guided_goto(desired)
        self.set_flight_mode("GUIDED")

    def _tick_competition_status(self) -> None:
        if not self._is_flight_active() or self.telemetry is None:
            self.competition_status_changed.emit(self.competition_status)
            return
        self.competition_status.flight_seconds += 1
        if self._is_autonomous_active():
            self.competition_status.autonomous_seconds += 1
        evaluation = self.zone_monitor.evaluate_position(self.telemetry.position)
        if evaluation.has_defense_violation:
            self.competition_status.defense_violation_seconds += 1
        if evaluation.outside_boundary:
            self.competition_status.out_of_bounds_seconds += 1
        self.competition_status_changed.emit(self.competition_status)

    def _resolve_ai_target(self) -> OtherDrone | None:
        if not self.other_drones:
            return None
        if self.ai_follow.target_team_id is not None:
            return next((drone for drone in self.other_drones if drone.team_id == self.ai_follow.target_team_id), None)
        return min(
            self.other_drones,
            key=lambda drone: haversine_distance_m(self.telemetry.position, drone.position) if self.telemetry else 10**9,
        )

    def _send_teknofest_telemetry(self) -> None:
        if self._api_client is None or self._runner is None or self.telemetry is None:
            return
        if not self._api_client.time_sync.synced():
            return
        server_now = self._api_client.time_sync.now()
        if not self._rate_limiter.allow(server_now):
            return
        future = self._runner.submit(self._api_client.send_telemetry(self.settings.app.team_id, self.telemetry))
        future.add_done_callback(self._handle_telemetry_post_result)

    def _connect_teknofest_api(self) -> None:
        if self._api_client is None or self._runner is None:
            return
        if not self.settings.teknofest_api.username:
            self.api_status_changed.emit("Teknofest API disabled: empty credentials")
            return
        self.api_status_changed.emit("Teknofest API login...")
        future = self._runner.submit(self._api_client.login())
        future.add_done_callback(self._handle_login_result)

    def _sync_server_time(self) -> None:
        if self._api_client is None or self._runner is None:
            return
        future = self._runner.submit(self._api_client.fetch_server_time())
        future.add_done_callback(self._handle_time_sync_result)

    def _handle_link_state(self, connected: bool) -> None:
        if connected:
            self._transition(MissionEvent.LINK_ESTABLISHED)
            self.configure_competition_profile()
        else:
            self._transition(MissionEvent.LINK_LOST)
        self.connection_changed.emit(connected)

    def _handle_login_result(self, future: Future) -> None:
        try:
            future.result()
            self.api_status_changed.emit("Teknofest API authenticated")
            self._sync_server_time()
        except Exception as exc:
            self.api_status_changed.emit(f"Teknofest API login failed: {exc}")
            self._log(f"Teknofest API login failed: {exc}")

    def _handle_time_sync_result(self, future: Future) -> None:
        try:
            server_time = future.result()
            self.api_status_changed.emit(f"Server time sync: {server_time.isoformat()}")
        except Exception as exc:
            self.api_status_changed.emit(f"Time sync failed: {exc}")
            self._log(f"Time sync failed: {exc}")

    def _handle_telemetry_post_result(self, future: Future) -> None:
        try:
            self.other_drones = future.result()
            self.other_drones_updated.emit(self.other_drones)
            self.api_status_changed.emit(f"Telemetry pushed at {datetime.now().strftime('%H:%M:%S')}")
        except Exception as exc:
            self.api_status_changed.emit(f"Telemetry push failed: {exc}")
            self._log(f"Telemetry push failed: {exc}")

    def _handle_hss_result(self, future: Future) -> None:
        try:
            self.hss_zones = future.result()
            self._rebuild_zone_monitor()
            self._log(f"HSS zones updated: {len(self.hss_zones)}")
        except Exception as exc:
            self._log(f"HSS refresh failed: {exc}")

    def _handle_mission_uploaded(self, name: str) -> None:
        self.mission_plan.uploaded = True
        self._refresh_mission_state()
        self._log(f"Mission upload completed: {name}")

    def _handle_fence_uploaded(self, message: str) -> None:
        self.mission_plan.fence_uploaded = True
        self._refresh_mission_state()
        self._log(f"Fence upload completed: {message}")

    def _rebuild_zone_monitor(self) -> None:
        zones: list[Zone] = []
        if self.competition_boundary is not None:
            zones.append(self.competition_boundary)
        zones.extend(self.user_zones)
        zones.extend(self.hss_zones)
        self.zone_monitor.set_zones(zones)
        self.zones_updated.emit(zones)
        self._refresh_mission_state()

    def _refresh_mission_state(self) -> None:
        validation = validate_mission_plan(
            self.mission_plan,
            self.zone_monitor,
            mission_zone_required=self.settings.safety.mission_zone_required,
        )
        self.mission_plan.valid = validation.valid
        self.mission_plan.validation_message = validation.message
        self.route = validation.route_points
        self.route_updated.emit(self.route)
        self.mission_plan_changed.emit(self.mission_plan)

    def _transition(self, event: MissionEvent) -> None:
        try:
            result = self.state_machine.apply(event)
        except InvalidTransitionError:
            return
        self.mission_state_changed.emit(result.current.value)
        self._log(f"FSM {result.previous.value} -> {result.current.value} ({event.value})")

    def _log(self, message: str) -> None:
        self.log_service.log_event("runtime", message)
        self.log_message.emit(message)

    def _load_competition_boundary_from_settings(self) -> None:
        raw_points = self.settings.map.competition_boundary_points
        if len(raw_points) < 3:
            self.competition_boundary = None
            self._rebuild_zone_monitor()
            return
        self.competition_boundary = Zone(
            identifier="competition-boundary",
            zone_type=ZoneType.COMPETITION,
            points=[
                GeoPoint(lat=float(point["lat"]), lon=float(point["lon"]))
                for point in raw_points
            ],
            label="Competition Boundary",
        )
        self._rebuild_zone_monitor()

    def _reset_competition_status(self) -> None:
        self.competition_status = CompetitionStatus(manual_mode_limit=self.settings.safety.manual_mode_limit)
        self._defense_violation_active = False
        self._no_fly_violation_active = False
        self._out_of_bounds_active = False
        self.competition_status_changed.emit(self.competition_status)

    def _is_flight_active(self) -> bool:
        return bool(
            self.telemetry is not None and (
                self.telemetry.armed or self.state_machine.state.value in {"ARMED", "MISSION", "FAILSAFE", "RTL"}
            )
        )

    def _is_autonomous_active(self) -> bool:
        if self.telemetry is not None and self.telemetry.autonomous:
            return True
        return self.control_authority in {ControlAuthority.AUTO, ControlAuthority.AI}
