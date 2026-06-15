from __future__ import annotations
import json
from pathlib import Path
from PyQt6.QtCore import QObject, QUrl, pyqtSignal, pyqtSlot
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtWebEngineWidgets import QWebEngineView

class MapBridge(QObject):
    map_clicked = pyqtSignal(float, float)
    vehicle_clicked = pyqtSignal(int)

    @pyqtSlot(float, float)
    def reportMapClick(self, lat: float, lon: float) -> None:
        self.map_clicked.emit(lat, lon)

    @pyqtSlot(int)
    def reportVehicleClicked(self, vehicle_id: int) -> None:
        self.vehicle_clicked.emit(vehicle_id)


class MapView(QWebEngineView):
    map_clicked = pyqtSignal(float, float)
    vehicle_clicked = pyqtSignal(int)

    def __init__(self) -> None:
        super().__init__()
        self._ready = False
        self._pending_scripts: list[str] = []
        
        self._bridge = MapBridge()
        self._bridge.map_clicked.connect(self.map_clicked.emit)
        self._bridge.vehicle_clicked.connect(self.vehicle_clicked.emit)

        # Setup WebChannel
        self._channel = QWebChannel(self.page())
        self._channel.registerObject("bridge", self._bridge)
        self.page().setWebChannel(self._channel)

        self.loadFinished.connect(self._on_loaded)
        
        # Load local HTML
        html_path = Path(__file__).resolve().parent / "assets" / "map" / "index.html"
        self.setUrl(QUrl.fromLocalFile(str(html_path)))

    def update_vehicles(self, vehicles: list) -> None:
        fleet_data = []
        for v in vehicles:
            fleet_data.append({
                "id": v.id,
                "lat": v.lat,
                "lon": v.lon,
                "alt": v.alt,
                "battery": v.battery_percent,
                "battery_v": v.battery_v,
                "rssi": v.rssi,
                "heading": v.heading,
                "mode": v.flight_mode,
                "armed": v.armed
            })
        self._run(f"window.gcsUpdateVehicles({json.dumps(fleet_data)});")

    def select_vehicle(self, vehicle_id: int) -> None:
        self._run(f"window.gcsSelectVehicle({vehicle_id});")

    def update_route(self, route_points: list) -> None:
        route_data = [{"lat": p.lat, "lon": p.lon} for p in route_points]
        self._run(f"window.gcsUpdateRoute({json.dumps(route_data)});")

    def zoom_in(self) -> None:
        self._run("window.gcsZoomIn();")

    def zoom_out(self) -> None:
        self._run("window.gcsZoomOut();")

    def center_on_selected(self) -> None:
        self._run("window.gcsCenterOnVehicle();")

    def _on_loaded(self, ok: bool) -> None:
        if not ok:
            print("[MapView] Error loading Leaflet HTML.")
            return
        self._ready = True
        
        # Bootstrap map with default configs (Istanbul/Teknofest test center)
        config = {
            "tileUrl": "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
            "attribution": "&copy; OpenStreetMap contributors",
            "center": {"lat": 41.143, "lon": 29.081},
            "zoom": 16
        }
        self.page().runJavaScript(f"window.bootstrapMap({json.dumps(config)});")
        
        for script in self._pending_scripts:
            self.page().runJavaScript(script)
        self._pending_scripts.clear()

    def _run(self, script: str) -> None:
        if self._ready:
            self.page().runJavaScript(script)
        else:
            self._pending_scripts.append(script)
