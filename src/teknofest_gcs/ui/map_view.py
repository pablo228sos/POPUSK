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

    def __init__(self, map_settings: any = None) -> None:
        super().__init__()
        self._ready = False
        self._pending_scripts: list[str] = []
        self.map_settings = map_settings
        
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
        
        # Determine parameters from settings or use defaults
        tile_url = "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        attribution = "&copy; OpenStreetMap contributors"
        center_lat = 41.143
        center_lon = 29.081
        zoom = 16
        
        if self.map_settings:
            if hasattr(self.map_settings, "tile_url"):
                tile_url = self.map_settings.tile_url
            elif isinstance(self.map_settings, dict):
                tile_url = self.map_settings.get("tile_url", tile_url)

            if hasattr(self.map_settings, "attribution"):
                attribution = self.map_settings.attribution
            elif isinstance(self.map_settings, dict):
                attribution = self.map_settings.get("attribution", attribution)

            if hasattr(self.map_settings, "center_lat"):
                center_lat = self.map_settings.center_lat
            elif isinstance(self.map_settings, dict):
                center_lat = self.map_settings.get("center_lat", center_lat)

            if hasattr(self.map_settings, "center_lon"):
                center_lon = self.map_settings.center_lon
            elif isinstance(self.map_settings, dict):
                center_lon = self.map_settings.get("center_lon", center_lon)

            if hasattr(self.map_settings, "zoom"):
                zoom = self.map_settings.zoom
            elif isinstance(self.map_settings, dict):
                zoom = self.map_settings.get("zoom", zoom)

        config = {
            "tileUrl": tile_url,
            "attribution": attribution,
            "center": {"lat": center_lat, "lon": center_lon},
            "zoom": zoom
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
