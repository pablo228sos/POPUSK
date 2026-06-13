from __future__ import annotations

import queue
import time
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

from PyQt6.QtCore import QThread, pyqtSignal

from teknofest_gcs.config.settings import AircraftSettings, ConnectionSettings, SafetySettings
from teknofest_gcs.core.models import GeoPoint, MissionItemType, MissionPlan, TelemetryData
from teknofest_gcs.mission.planning import AutopilotFencePlan

try:
    from pymavlink import mavutil
except ImportError:  # pragma: no cover - optional dependency at runtime
    mavutil = None


class MavlinkWorker(QThread):
    telemetry_received = pyqtSignal(object)
    status_message = pyqtSignal(str)
    link_state_changed = pyqtSignal(bool)
    mission_uploaded = pyqtSignal(str)
    fence_uploaded = pyqtSignal(str)
    guided_target_sent = pyqtSignal(object)

    def __init__(self, settings: ConnectionSettings) -> None:
        super().__init__()
        self.settings = settings
        self._running = True
        self._command_queue: queue.SimpleQueue[tuple[str, object | None]] = queue.SimpleQueue()
        self._latest = TelemetryData(position=GeoPoint(lat=0.0, lon=0.0), source="mavlink")
        self._link_active = False
        self._connection = None
        self._target_system = 1
        self._target_component = 1

    def stop(self) -> None:
        self._running = False

    def queue_arm(self) -> None:
        self._command_queue.put(("arm", None))

    def queue_disarm(self) -> None:
        self._command_queue.put(("disarm", None))

    def queue_mode(self, mode: str) -> None:
        self._command_queue.put(("mode", mode))

    def queue_upload_mission(self, plan: MissionPlan) -> None:
        self._command_queue.put(("upload_mission", plan))

    def queue_upload_fence(self, fence_plan: AutopilotFencePlan) -> None:
        self._command_queue.put(("upload_fence", fence_plan))

    def queue_guided_goto(self, point: GeoPoint) -> None:
        self._command_queue.put(("guided_goto", point))

    def queue_configure_profile(self, payload: tuple[AircraftSettings, SafetySettings]) -> None:
        self._command_queue.put(("configure_profile", payload))

    def run(self) -> None:  # pragma: no cover - Qt thread
        if mavutil is None:
            self.status_message.emit("pymavlink is not installed")
            return
        try:
            self._connection = self._open_connection()
            self.status_message.emit("Waiting for MAVLink heartbeat...")
            heartbeat = self._connection.wait_heartbeat(timeout=12)
            self._target_system = heartbeat.get_srcSystem()
            self._target_component = heartbeat.get_srcComponent()
            self._set_link_state(True)
            self.status_message.emit("MAVLink connected")
        except Exception as exc:
            self.status_message.emit(f"MAVLink connect failed: {exc}")
            self._set_link_state(False)
            return

        last_heartbeat = time.monotonic()
        while self._running:
            self._process_command_queue()
            msg = self._connection.recv_match(blocking=True, timeout=0.25)
            if msg is None:
                if time.monotonic() - last_heartbeat > self.settings.heartbeat_timeout_sec:
                    self._set_link_state(False)
                continue
            msg_type = msg.get_type()
            if msg_type == "BAD_DATA":
                continue
            if msg_type == "HEARTBEAT":
                last_heartbeat = time.monotonic()
            self._handle_message(msg)

        self._set_link_state(False)

    def _open_connection(self):
        if self.settings.transport == "serial":
            return mavutil.mavlink_connection(self.settings.serial_port, baud=self.settings.baud_rate)
        if self.settings.transport == "udp":
            return mavutil.mavlink_connection(self.settings.udp_endpoint)
        raise RuntimeError(f"Unsupported transport: {self.settings.transport}")

    def _process_command_queue(self) -> None:
        while not self._command_queue.empty():
            command, value = self._command_queue.get()
            if self._connection is None:
                continue
            try:
                if command == "arm":
                    self._connection.arducopter_arm()
                    self.status_message.emit("ARM command sent")
                elif command == "disarm":
                    self._connection.arducopter_disarm()
                    self.status_message.emit("DISARM command sent")
                elif command == "mode" and isinstance(value, str):
                    self._connection.set_mode(value)
                    self.status_message.emit(f"Mode command sent: {value}")
                elif command == "guided_goto" and isinstance(value, GeoPoint):
                    self._send_guided_goto(value)
                elif command == "upload_mission" and isinstance(value, MissionPlan):
                    self._upload_mission(value)
                elif command == "upload_fence" and isinstance(value, AutopilotFencePlan):
                    self._upload_fence(value)
                elif command == "configure_profile" and isinstance(value, tuple):
                    aircraft, safety = value
                    self._configure_competition_profile(aircraft, safety)
            except Exception as exc:
                self.status_message.emit(f"MAVLink command failed: {exc}")

    def _handle_message(self, msg) -> None:
        if mavutil is None:
            return
        msg_type = msg.get_type()
        if msg_type == "HEARTBEAT":
            self._set_link_state(True)
            self._latest.mode = mavutil.mode_string_v10(msg)
            self._latest.armed = bool(msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED)
            self._latest.autonomous = self._latest.mode.upper() in {
                "AUTO",
                "GUIDED",
                "RTL",
                "QRTL",
                "QLAND",
                "QLOITER",
                "MISSION",
            }
        elif msg_type == "GLOBAL_POSITION_INT":
            self._latest.position = GeoPoint(
                lat=msg.lat / 1e7,
                lon=msg.lon / 1e7,
                altitude_m=msg.relative_alt / 1000.0,
            )
            self._latest.heading_deg = (msg.hdg / 100.0) if msg.hdg != 65535 else self._latest.heading_deg
            if self._latest.timestamp.tzinfo is None:
                self._latest.timestamp = datetime.now(timezone.utc)
            self.telemetry_received.emit(replace(self._latest))
        elif msg_type == "VFR_HUD":
            self._latest.ground_speed_mps = float(msg.groundspeed)
            self._latest.air_speed_mps = float(msg.airspeed)
            self._latest.heading_deg = float(msg.heading % 360)
            self._latest.position.altitude_m = float(msg.alt)
        elif msg_type == "SYSTEM_TIME":
            if getattr(msg, "time_unix_usec", 0) > 0:
                self._latest.timestamp = datetime.fromtimestamp(msg.time_unix_usec / 1e6, tz=timezone.utc)
        elif msg_type == "ATTITUDE":
            self._latest.roll_deg = msg.roll * 57.2958
            self._latest.pitch_deg = msg.pitch * 57.2958
            self._latest.yaw_deg = msg.yaw * 57.2958
        elif msg_type == "SYS_STATUS":
            self._latest.battery_percent = max(0, min(100, int(msg.battery_remaining)))
            self._latest.battery_voltage = msg.voltage_battery / 1000.0

    def _send_guided_goto(self, point: GeoPoint) -> None:
        if mavutil is None or self._connection is None:
            return
        self._connection.mav.mission_item_int_send(
            self._target_system,
            self._target_component,
            0,
            mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT,
            mavutil.mavlink.MAV_CMD_NAV_WAYPOINT,
            2,
            0,
            0.0,
            0.0,
            0.0,
            0.0,
            int(point.lat * 1e7),
            int(point.lon * 1e7),
            float(point.altitude_m),
        )
        self.guided_target_sent.emit(point)
        self.status_message.emit(
            f"GUIDED goto: {point.lat:.6f}, {point.lon:.6f}, {point.altitude_m:.1f} m"
        )

    def _configure_competition_profile(self, aircraft: AircraftSettings, safety: SafetySettings) -> None:
        if mavutil is None:
            return
        self._set_parameter("Q_GUIDED_MODE", 1.0 if aircraft.qguided_mode_enabled else 0.0)
        self._set_parameter("Q_RTL_MODE", float(aircraft.qrtl_mode))
        self._set_parameter("FENCE_ENABLE", 1.0)
        self._set_parameter("FENCE_TYPE", 4.0)
        if safety.fence_action.upper() == "RTL":
            self._set_parameter("FENCE_ACTION", 1.0)
        self.status_message.emit("QuadPlane competition profile applied")

    def _upload_mission(self, plan: MissionPlan) -> None:
        if mavutil is None:
            return
        items = self._build_mission_items(plan)
        self._upload_items(items, mavutil.mavlink.MAV_MISSION_TYPE_MISSION)
        self.mission_uploaded.emit(plan.name)
        self.status_message.emit(f"Mission uploaded: {plan.name} ({len(items)} items)")

    def _upload_fence(self, fence_plan: AutopilotFencePlan) -> None:
        if mavutil is None:
            return
        items = self._build_fence_items(fence_plan)
        self._upload_items(items, mavutil.mavlink.MAV_MISSION_TYPE_FENCE)
        self._set_parameter("FENCE_ENABLE", 1.0)
        self.fence_uploaded.emit(f"{len(items)} fence items")
        self.status_message.emit(f"Fence uploaded ({len(items)} items)")

    def _upload_items(self, items: list[dict[str, Any]], mission_type: int) -> None:
        if self._connection is None or mavutil is None:
            return
        self._connection.mav.mission_clear_all_send(
            self._target_system,
            self._target_component,
            mission_type=mission_type,
        )
        try:
            self._wait_for_message({"MISSION_ACK"}, timeout=1.0, passthrough=False)
        except TimeoutError:
            pass

        self._connection.mav.mission_count_send(
            self._target_system,
            self._target_component,
            len(items),
            mission_type=mission_type,
        )

        while True:
            msg = self._wait_for_message({"MISSION_REQUEST_INT", "MISSION_REQUEST", "MISSION_ACK"}, timeout=12.0)
            msg_type = msg.get_type()
            if msg_type == "MISSION_ACK":
                if int(msg.type) != int(mavutil.mavlink.MAV_MISSION_ACCEPTED):
                    raise RuntimeError(f"Mission upload rejected: ACK type {int(msg.type)}")
                return
            seq = int(msg.seq)
            if seq < 0 or seq >= len(items):
                raise RuntimeError(f"Autopilot requested invalid mission sequence {seq}")
            item = items[seq]
            self._connection.mav.mission_item_int_send(
                self._target_system,
                self._target_component,
                seq,
                int(item["frame"]),
                int(item["command"]),
                int(item["current"]),
                int(item["autocontinue"]),
                float(item["param1"]),
                float(item["param2"]),
                float(item["param3"]),
                float(item["param4"]),
                int(item["x"]),
                int(item["y"]),
                float(item["z"]),
                mission_type=mission_type,
            )

    def _wait_for_message(self, types: set[str], timeout: float, passthrough: bool = True):
        if self._connection is None:
            raise RuntimeError("MAVLink connection is not available")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            msg = self._connection.recv_match(blocking=True, timeout=0.4)
            if msg is None:
                continue
            msg_type = msg.get_type()
            if msg_type in types:
                return msg
            if passthrough:
                self._handle_message(msg)
        raise TimeoutError(f"Timed out waiting for MAVLink message(s): {sorted(types)}")

    def _set_parameter(self, name: str, value: float) -> None:
        if self._connection is None or mavutil is None:
            return
        self._connection.mav.param_set_send(
            self._target_system,
            self._target_component,
            name.encode("ascii"),
            float(value),
            mavutil.mavlink.MAV_PARAM_TYPE_REAL32,
        )
        self.status_message.emit(f"Param set: {name}={value}")

    def _build_mission_items(self, plan: MissionPlan) -> list[dict[str, Any]]:
        if mavutil is None:
            return []
        encoded: list[dict[str, Any]] = []
        for item in plan.items:
            if item.item_type == MissionItemType.VTOL_TAKEOFF:
                encoded.append(
                    self._mission_item(
                        command=mavutil.mavlink.MAV_CMD_NAV_VTOL_TAKEOFF,
                        point=item.point,
                        z=item.point.altitude_m,
                    )
                )
            elif item.item_type == MissionItemType.WAYPOINT:
                encoded.append(
                    self._mission_item(
                        command=mavutil.mavlink.MAV_CMD_NAV_WAYPOINT,
                        point=item.point,
                        param2=item.acceptance_radius_m,
                        z=item.point.altitude_m,
                    )
                )
            elif item.item_type == MissionItemType.LOITER:
                encoded.append(
                    self._mission_item(
                        command=mavutil.mavlink.MAV_CMD_NAV_LOITER_TIME,
                        point=item.point,
                        param1=item.loiter_sec,
                        param3=item.acceptance_radius_m,
                        z=item.point.altitude_m,
                    )
                )
            elif item.item_type == MissionItemType.VTOL_TRANSITION_MC:
                encoded.append(
                    self._mission_item(
                        command=mavutil.mavlink.MAV_CMD_DO_VTOL_TRANSITION,
                        point=item.point,
                        frame=mavutil.mavlink.MAV_FRAME_MISSION,
                        param1=3.0,
                        x=0,
                        y=0,
                        z=0.0,
                    )
                )
            elif item.item_type == MissionItemType.VTOL_TRANSITION_FW:
                encoded.append(
                    self._mission_item(
                        command=mavutil.mavlink.MAV_CMD_DO_VTOL_TRANSITION,
                        point=item.point,
                        frame=mavutil.mavlink.MAV_FRAME_MISSION,
                        param1=4.0,
                        x=0,
                        y=0,
                        z=0.0,
                    )
                )
            elif item.item_type == MissionItemType.VTOL_LAND:
                encoded.append(
                    self._mission_item(
                        command=mavutil.mavlink.MAV_CMD_NAV_VTOL_LAND,
                        point=item.point,
                        z=item.point.altitude_m,
                    )
                )
            elif item.item_type == MissionItemType.RETURN_TO_LAUNCH:
                encoded.append(
                    self._mission_item(
                        command=mavutil.mavlink.MAV_CMD_NAV_RETURN_TO_LAUNCH,
                        point=item.point,
                        frame=mavutil.mavlink.MAV_FRAME_MISSION,
                        x=0,
                        y=0,
                        z=0.0,
                    )
                )
        return encoded

    def _build_fence_items(self, fence_plan: AutopilotFencePlan) -> list[dict[str, Any]]:
        if mavutil is None:
            return []
        items: list[dict[str, Any]] = [
            self._mission_item(
                command=mavutil.mavlink.MAV_CMD_NAV_FENCE_RETURN_POINT,
                point=fence_plan.return_point,
            )
        ]
        items.extend(
            self._encode_polygon(
                fence_plan.inclusion_boundary,
                mavutil.mavlink.MAV_CMD_NAV_FENCE_POLYGON_VERTEX_INCLUSION,
            )
        )
        for polygon in fence_plan.exclusion_polygons:
            items.extend(
                self._encode_polygon(
                    polygon,
                    mavutil.mavlink.MAV_CMD_NAV_FENCE_POLYGON_VERTEX_EXCLUSION,
                )
            )
        return items

    def _encode_polygon(self, polygon: list[GeoPoint], command: int) -> list[dict[str, Any]]:
        return [
            self._mission_item(
                command=command,
                point=point,
                param1=float(len(polygon)),
            )
            for point in polygon
        ]

    def _mission_item(
        self,
        command: int,
        point: GeoPoint,
        *,
        frame: int | None = None,
        current: int = 0,
        autocontinue: int = 1,
        param1: float = 0.0,
        param2: float = 0.0,
        param3: float = 0.0,
        param4: float = 0.0,
        x: int | None = None,
        y: int | None = None,
        z: float | None = None,
    ) -> dict[str, Any]:
        if mavutil is None:
            return {}
        resolved_frame = frame if frame is not None else mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT
        resolved_x = int(point.lat * 1e7) if x is None else x
        resolved_y = int(point.lon * 1e7) if y is None else y
        resolved_z = point.altitude_m if z is None else z
        return {
            "frame": resolved_frame,
            "command": command,
            "current": current,
            "autocontinue": autocontinue,
            "param1": param1,
            "param2": param2,
            "param3": param3,
            "param4": param4,
            "x": resolved_x,
            "y": resolved_y,
            "z": resolved_z,
        }

    def _set_link_state(self, connected: bool) -> None:
        if self._link_active != connected:
            self._link_active = connected
            self.link_state_changed.emit(connected)
