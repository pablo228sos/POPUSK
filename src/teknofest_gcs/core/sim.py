from __future__ import annotations
import math
import time
import random
import threading
from typing import TYPE_CHECKING
from teknofest_gcs.core.models import GeoPoint

if TYPE_CHECKING:
    from teknofest_gcs.core.models import FleetManager

class SimulatedVehicle:
    def __init__(self, id: int, home_lat: float, home_lon: float) -> None:
        self.id = id
        self.home_lat = home_lat
        self.home_lon = home_lon
        self.lat = home_lat
        self.lon = home_lon
        self.alt = 0.0
        self.relative_alt = 0.0
        self.heading = 0.0
        self.roll = 0.0
        self.pitch = 0.0
        self.yaw = 0.0
        self.vx = 0.0
        self.vy = 0.0
        self.vz = 0.0
        self.battery_v = 12.6
        self.battery_percent = 100
        self.rssi = 100
        self.flight_mode = "LANDED"
        self.armed = False
        self.waypoints: list[GeoPoint] = []
        self.target_wp_index = -1
        
        # Sim targets
        self.target_alt = 0.0
        self.target_lat = home_lat
        self.target_lon = home_lon
        self.speed_mps = 8.0 # speed in meters per second
        self.orbit_center_lat = 0.0
        self.orbit_center_lon = 0.0
        self.orbit_angle = 0.0

    def command_arm(self) -> None:
        self.armed = True
        self.flight_mode = "ARMED"

    def command_disarm(self) -> None:
        self.armed = False
        self.flight_mode = "LANDED"
        self.alt = 0.0
        self.relative_alt = 0.0

    def command_takeoff(self, altitude: float = 15.0) -> None:
        if not self.armed:
            self.command_arm()
        self.target_alt = altitude
        self.flight_mode = "TAKEOFF"

    def command_land(self) -> None:
        self.target_alt = 0.0
        self.flight_mode = "LANDING"

    def command_rtl(self) -> None:
        self.target_lat = self.home_lat
        self.target_lon = self.home_lon
        self.target_alt = 15.0
        self.flight_mode = "RTL"

    def command_goto(self, lat: float, lon: float, alt: float = 15.0) -> None:
        self.target_lat = lat
        self.target_lon = lon
        self.target_alt = alt
        self.flight_mode = "GUIDED"

    def command_orbit(self, lat: float, lon: float, radius: float = 20.0) -> None:
        self.orbit_center_lat = lat
        self.orbit_center_lon = lon
        self.target_alt = 15.0
        # Calculate current angle from center
        dy = (self.lat - lat) * 111000.0
        dx = (self.lon - lon) * 111000.0 * math.cos(math.radians(lat))
        self.orbit_angle = math.atan2(dy, dx)
        self.flight_mode = "ORBIT"

    def update(self, dt: float) -> None:
        # Battery depletion simulator
        if self.armed:
            self.battery_percent = max(0, self.battery_percent - random.uniform(0.01, 0.03))
            self.battery_v = 10.0 + (self.battery_percent / 100.0) * 2.6
        
        # RSSI simulation
        self.rssi = max(50, min(100, self.rssi + random.randint(-2, 2)))

        # Altitude simulation
        alt_err = self.target_alt - self.alt
        if abs(alt_err) > 0.1:
            climb_rate = 2.0 # m/s
            step = math.copysign(climb_rate * dt, alt_err)
            if abs(step) > abs(alt_err):
                self.alt = self.target_alt
            else:
                self.alt += step
            self.relative_alt = self.alt
            self.vz = climb_rate if alt_err > 0 else -climb_rate
        else:
            self.vz = 0.0
            if self.flight_mode == "TAKEOFF":
                self.flight_mode = "HOLD"
            elif self.flight_mode == "LANDING" or (self.flight_mode == "RTL" and abs(self.lat - self.home_lat) < 0.0001):
                self.command_disarm()

        # Latitude/Longitude movement simulation
        if self.flight_mode in ("GUIDED", "RTL", "AUTO"):
            # Move towards target
            dy = (self.target_lat - self.lat) * 111000.0
            dx = (self.target_lon - self.lon) * 111000.0 * math.cos(math.radians(self.lat))
            dist = math.sqrt(dx*dx + dy*dy)

            if dist > 1.0:
                self.heading = (math.degrees(math.atan2(dx, dy)) + 360) % 360
                step_dist = self.speed_mps * dt
                if step_dist >= dist:
                    self.lat = self.target_lat
                    self.lon = self.target_lon
                    if self.flight_mode == "RTL":
                        self.flight_mode = "LANDING"
                        self.target_alt = 0.0
                    elif self.flight_mode == "GUIDED":
                        self.flight_mode = "HOLD"
                else:
                    ratio = step_dist / dist
                    self.lat += (self.target_lat - self.lat) * ratio
                    self.lon += (self.target_lon - self.lon) * ratio
                
                self.vx = self.speed_mps * math.sin(math.radians(self.heading))
                self.vy = self.speed_mps * math.cos(math.radians(self.heading))
            else:
                self.vx = 0.0
                self.vy = 0.0

        elif self.flight_mode == "ORBIT":
            # Climb/maintain alt first
            if self.alt < 5.0:
                return

            # Circle orbiting logic
            angular_velocity = self.speed_mps / 20.0 # rad/s (using 20m radius)
            self.orbit_angle += angular_velocity * dt
            
            radius_deg_lat = 20.0 / 111000.0
            radius_deg_lon = 20.0 / (111000.0 * math.cos(math.radians(self.orbit_center_lat)))
            
            new_lat = self.orbit_center_lat + radius_deg_lat * math.sin(self.orbit_angle)
            new_lon = self.orbit_center_lon + radius_deg_lon * math.cos(self.orbit_angle)
            
            # Heading should point tangent to orbit circle
            self.heading = (math.degrees(self.orbit_angle) + 180) % 360
            self.lat = new_lat
            self.lon = new_lon

        else:
            self.vx = 0.0
            self.vy = 0.0

        # Attitude jitter
        if self.armed and self.alt > 1.0:
            self.roll = random.uniform(-3.0, 3.0) + (self.vx * 2.0)
            self.pitch = random.uniform(-3.0, 3.0) + (self.vy * 2.0)
            self.yaw = self.heading
        else:
            self.roll = 0.0
            self.pitch = 0.0
            self.yaw = self.heading


class SwarmSimulationEngine:
    def __init__(self, fleet_manager: FleetManager) -> None:
        self.fleet_manager = fleet_manager
        self.vehicles: dict[int, SimulatedVehicle] = {}
        self.running = False
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        
        # Default center coordinates (e.g. Istanbul/Teknofest test field)
        self.center_lat = 41.143
        self.center_lon = 29.081

    def configure_swarm(self, count: int) -> None:
        with self._lock:
            # Clear existing simulated vehicles
            for v_id in list(self.vehicles.keys()):
                self.fleet_manager.remove_vehicle(v_id)
            self.vehicles.clear()

            # Generate new vehicles in a grid/circle formation around center
            for i in range(count):
                vehicle_id = 100 + (i + 1)
                # Offset slightly (approx 30m apart)
                angle = (2 * math.pi * i) / max(1, count)
                radius = 30.0 / 111000.0
                offset_lat = radius * math.cos(angle)
                offset_lon = radius * math.sin(angle) / math.cos(math.radians(self.center_lat))
                
                sim_vehicle = SimulatedVehicle(
                    id=vehicle_id,
                    home_lat=self.center_lat + offset_lat,
                    home_lon=self.center_lon + offset_lon
                )
                self.vehicles[vehicle_id] = sim_vehicle
                self._update_fleet_state(sim_vehicle)

    def start(self) -> None:
        with self._lock:
            if self.running:
                return
            self.running = True
            self._thread = threading.Thread(target=self._run_loop, daemon=True)
            self._thread.start()

    def stop(self) -> None:
        with self._lock:
            self.running = False
        if self._thread:
            self._thread.join(timeout=1.0)

    def send_vehicle_command(self, vehicle_id: int, cmd: str, *args) -> None:
        with self._lock:
            vehicle = self.vehicles.get(vehicle_id)
            if not vehicle:
                return
            
            if cmd == "arm":
                vehicle.command_arm()
            elif cmd == "disarm":
                vehicle.command_disarm()
            elif cmd == "takeoff":
                vehicle.command_takeoff()
            elif cmd == "land":
                vehicle.command_land()
            elif cmd == "rtl":
                vehicle.command_rtl()
            elif cmd == "goto":
                vehicle.command_goto(args[0], args[1])
            elif cmd == "orbit":
                vehicle.command_orbit(args[0], args[1])

    def send_global_command(self, cmd: str, *args) -> None:
        with self._lock:
            for vehicle in self.vehicles.values():
                if cmd == "arm":
                    vehicle.command_arm()
                elif cmd == "disarm":
                    vehicle.command_disarm()
                elif cmd == "takeoff":
                    vehicle.command_takeoff()
                elif cmd == "land":
                    vehicle.command_land()
                elif cmd == "rtl":
                    vehicle.command_rtl()
                elif cmd == "goto":
                    vehicle.command_goto(args[0], args[1])

    def _run_loop(self) -> None:
        last_time = time.time()
        while True:
            with self._lock:
                if not self.running:
                    break
            
            now = time.time()
            dt = now - last_time
            last_time = now

            with self._lock:
                for vehicle in self.vehicles.values():
                    vehicle.update(dt)
                    self._update_fleet_state(vehicle)

            time.sleep(0.1)

    def _update_fleet_state(self, v: SimulatedVehicle) -> None:
        self.fleet_manager.update_vehicle(
            vehicle_id=v.id,
            lat=v.lat,
            lon=v.lon,
            alt=v.alt,
            relative_alt=v.relative_alt,
            heading=v.heading,
            roll=v.roll,
            pitch=v.pitch,
            yaw=v.yaw,
            vx=v.vx,
            vy=v.vy,
            vz=v.vz,
            battery_v=v.battery_v,
            battery_percent=int(v.battery_percent),
            rssi=v.rssi,
            flight_mode=v.flight_mode,
            armed=v.armed
        )
