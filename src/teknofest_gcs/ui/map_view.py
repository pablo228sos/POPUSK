from __future__ import annotations

import json
from pathlib import Path

from PyQt6.QtCore import QObject, QUrl, pyqtSignal, pyqtSlot
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtWebEngineCore import QWebEngineProfile
from PyQt6.QtWebEngineWidgets import QWebEngineView

from teknofest_gcs.config.settings import MapSettings
from teknofest_gcs.core.models import GeoPoint, OtherDrone, Zone


class MapBridge(QObject):
    map_clicked = pyqtSignal(float, float)

    @pyqtSlot(float, float)
    def reportMapClick(self, lat: float, lon: float) -> None:
        self.map_clicked.emit(lat, lon)


class MapView(QWebEngineView):
    map_clicked = pyqtSignal(float, float)

    def __init__(self, settings: MapSettings) -> None:
        super().__init__()
        self.settings = settings
        self._ready = False
        self._pending_scripts: list[str] = []
        self._bridge = MapBridge()
        self._bridge.map_clicked.connect(self.map_clicked.emit)

        profile = QWebEngineProfile.defaultProfile()
        cache_path = Path(settings.cache_path).resolve()
        cache_path.mkdir(parents=True, exist_ok=True)
        profile.setCachePath(str(cache_path))
        profile.setPersistentStoragePath(str(cache_path))

        channel = QWebChannel(self.page())
        channel.registerObject("bridge", self._bridge)
        self.page().setWebChannel(channel)

        self.loadFinished.connect(self._on_loaded)
        html_path = Path(__file__).resolve().parent / "assets" / "map" / "index.html"
        self.setUrl(QUrl.fromLocalFile(str(html_path)))

    def set_vehicle(self, point: GeoPoint, heading_deg: float, mode: str) -> None:
        payload = {"lat": point.lat, "lon": point.lon, "heading": heading_deg, "mode": mode}
        self._run(f"window.gcsUpdateVehicle({json.dumps(payload)});")

    def set_other_drones(self, drones: list[OtherDrone]) -> None:
        payload = [
            {"team_id": drone.team_id, "lat": drone.position.lat, "lon": drone.position.lon, "latency_ms": drone.latency_ms}
            for drone in drones
        ]
        self._run(f"window.gcsUpdateOtherDrones({json.dumps(payload)});")

    def set_zones(self, zones: list[Zone]) -> None:
        payload = []
        for zone in zones:
            payload.append(
                {
                    "id": zone.identifier,
                    "type": zone.zone_type.value,
                    "label": zone.label,
                    "points": [{"lat": p.lat, "lon": p.lon} for p in zone.points],
                    "center": {"lat": zone.center.lat, "lon": zone.center.lon} if zone.center else None,
                    "radius_m": zone.radius_m,
                }
            )
        self._run(f"window.gcsUpdateZones({json.dumps(payload)});")

    def set_route(self, route: list[GeoPoint]) -> None:
        payload = [{"lat": point.lat, "lon": point.lon} for point in route]
        self._run(f"window.gcsUpdateRoute({json.dumps(payload)});")

    def zoom_in(self) -> None:
        self._run("window.gcsZoomIn();")

    def zoom_out(self) -> None:
        self._run("window.gcsZoomOut();")

    def center_on_vehicle(self) -> None:
        self._run("window.gcsCenterOnVehicle();")

    def set_editor_mode(self, mode: str, label: str = "") -> None:
        payload = {"mode": mode, "label": label}
        self._run(f"window.gcsSetEditorState({json.dumps(payload)});")

    def set_draft_overlay(self, points: list[GeoPoint], zone_type: str = "", radius_m: float | None = None) -> None:
        payload = {
            "points": [{"lat": point.lat, "lon": point.lon} for point in points],
            "zone_type": zone_type,
            "radius_m": radius_m,
        }
        self._run(f"window.gcsUpdateDraft({json.dumps(payload)});")

    def _on_loaded(self, ok: bool) -> None:
        if not ok:
            return
        self._ready = True
        config = {
            "tileUrl": self.settings.tile_url,
            "attribution": self.settings.attribution,
            "center": {"lat": self.settings.center_lat, "lon": self.settings.center_lon},
            "zoom": self.settings.zoom,
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
