from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import aiohttp
except ImportError:  # pragma: no cover - optional dependency at runtime
    aiohttp = None

from teknofest_gcs.config.settings import TeknofestApiSettings
from teknofest_gcs.core.models import GeoPoint, OtherDrone, TargetInfo, TelemetryData, Zone, ZoneType


class ApiError(RuntimeError):
    pass


STATUS_MESSAGES = {
    200: "OK",
    204: "Format error",
    400: "Invalid request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Endpoint not found",
    500: "Server error",
}


@dataclass(slots=True)
class TimeSyncState:
    offset_seconds: float = 0.0
    last_sync_monotonic: float = 0.0

    def synced(self) -> bool:
        return self.last_sync_monotonic > 0

    def now(self) -> datetime:
        return datetime.fromtimestamp(time.time() + self.offset_seconds, tz=timezone.utc)


class TelemetryRateLimiter:
    def __init__(self, period_seconds: float = 1.0) -> None:
        self.period_seconds = period_seconds
        self._last_sent_at: float = 0.0

    def allow(self, server_now: datetime) -> bool:
        now_ts = server_now.timestamp()
        if now_ts - self._last_sent_at < self.period_seconds:
            return False
        self._last_sent_at = now_ts
        return True


class TeknofestApiClient:
    def __init__(self, settings: TeknofestApiSettings) -> None:
        self.settings = settings
        self.base_url = settings.base_url.rstrip("/")
        self.session_file = Path(settings.session_file)
        self._session: aiohttp.ClientSession | None = None
        self.time_sync = TimeSyncState()

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def login(self) -> dict[str, Any]:
        payload = {
            "kadi": self.settings.username,
            "sifre": self.settings.password,
        }
        response = await self._request("POST", "/api/giris", json_payload=payload)
        await self._save_session()
        return response

    async def fetch_server_time(self) -> datetime:
        try:
            payload = await self._request("GET", "/api/sunucusaati")
        except ApiError as exc:
            if "404" not in str(exc):
                raise
            payload = await self._request("GET", "/api/servertime")
        server_time = parse_server_time(payload)
        self.time_sync.offset_seconds = server_time.timestamp() - time.time()
        self.time_sync.last_sync_monotonic = time.monotonic()
        return server_time

    async def send_telemetry(self, team_id: int, telemetry: TelemetryData) -> list[OtherDrone]:
        payload = build_telemetry_payload(team_id=team_id, telemetry=telemetry, server_time=self.time_sync.now())
        response = await self._request("POST", "/api/telemetri_gonder", json_payload=payload)
        return parse_other_drones(response)

    async def send_lock_info(self, start_time: datetime, end_time: datetime, autonomous: bool) -> dict[str, Any]:
        payload = {
            "kilitlenmeBaslangicZamani": gps_clock_payload(start_time),
            "kilitlenmeBitisZamani": gps_clock_payload(end_time),
            "otonom_kilitlenme": 1 if autonomous else 0,
        }
        return await self._request("POST", "/api/kilitlenme_bilgisi", json_payload=payload)

    async def send_kamikaze_info(self, start_time: datetime, end_time: datetime, qr_text: str) -> dict[str, Any]:
        payload = {
            "kamikazeBaslangicZamani": gps_clock_payload(start_time),
            "kamikazeBitisZamani": gps_clock_payload(end_time),
            "qrMetni": qr_text,
        }
        return await self._request("POST", "/api/kamikaze_bilgisi", json_payload=payload)

    async def fetch_qr_coordinates(self) -> GeoPoint | None:
        response = await self._request("GET", "/api/qr_koordinati")
        if not response:
            return None
        if "qrEnlem" in response and "qrBoylam" in response:
            return GeoPoint(lat=float(response["qrEnlem"]), lon=float(response["qrBoylam"]))
        if "koordinat" in response:
            item = response["koordinat"]
            return GeoPoint(lat=float(item["enlem"]), lon=float(item["boylam"]))
        return None

    async def fetch_hss_zones(self) -> list[Zone]:
        response = await self._request("GET", "/api/hss_koordinatlari")
        raw_zones = response.get("hss_koordinat_bilgileri", response if isinstance(response, list) else [])
        zones: list[Zone] = []
        for index, item in enumerate(raw_zones):
            zones.append(
                Zone(
                    identifier=str(item.get("id", index)),
                    zone_type=ZoneType.DEFENSE,
                    center=GeoPoint(lat=float(item["hssEnlem"]), lon=float(item["hssBoylam"])),
                    radius_m=float(item["hssYaricap"]),
                    label=f"HSS {item.get('id', index)}",
                )
            )
        if "sunucusaati" in response:
            server_time = parse_server_time(response)
            self.time_sync.offset_seconds = server_time.timestamp() - time.time()
            self.time_sync.last_sync_monotonic = time.monotonic()
        return zones

    async def _request(self, method: str, path: str, json_payload: dict[str, Any] | None = None) -> dict[str, Any]:
        session = await self._ensure_session()
        url = f"{self.base_url}{path}"
        async with session.request(method, url, json=json_payload) as response:
            text = await response.text()
            if response.status != 200:
                raise ApiError(f"{response.status} {STATUS_MESSAGES.get(response.status, 'Unexpected status')}: {text}")
            await self._save_session()
            if not text.strip():
                return {}
            try:
                return json.loads(text)
            except json.JSONDecodeError as exc:
                raise ApiError(f"Invalid JSON from {path}: {text}") from exc

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if aiohttp is None:
            raise ApiError("aiohttp is not installed")
        if self._session is not None and not self._session.closed:
            return self._session
        self._session = aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar())
        await self._load_session()
        return self._session

    async def _load_session(self) -> None:
        if self._session is None or not self.session_file.exists():
            return
        try:
            data = json.loads(self.session_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return
        cookies = data.get("cookies", {})
        self._session.cookie_jar.update_cookies(cookies)

    async def _save_session(self) -> None:
        if self._session is None:
            return
        self.session_file.parent.mkdir(parents=True, exist_ok=True)
        cookies = {
            key: morsel.value
            for key, morsel in self._session.cookie_jar.filter_cookies(self.base_url).items()
        }
        payload = {"cookies": cookies}
        self.session_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def build_telemetry_payload(
    team_id: int,
    telemetry: TelemetryData,
    server_time: datetime | None = None,
) -> dict[str, Any]:
    _validate_telemetry(telemetry)
    gps_time = telemetry.timestamp if telemetry.timestamp else (server_time or datetime.now(timezone.utc))
    return {
        "takim_numarasi": team_id,
        "iha_enlem": round(telemetry.position.lat, 7),
        "iha_boylam": round(telemetry.position.lon, 7),
        "iha_irtifa": round(telemetry.position.altitude_m, 2),
        "iha_dikilme": round(telemetry.pitch_deg, 2),
        "iha_yonelme": int(round(telemetry.heading_deg % 360)),
        "iha_yatis": round(telemetry.roll_deg, 2),
        "iha_hiz": round(telemetry.ground_speed_mps, 2),
        "iha_batarya": int(telemetry.battery_percent),
        "iha_otonom": 1 if telemetry.autonomous else 0,
        "iha_kilitlenme": 1 if telemetry.target.locked else 0,
        "hedef_merkez_X": int(telemetry.target.center_x),
        "hedef_merkez_Y": int(telemetry.target.center_y),
        "hedef_genislik": int(telemetry.target.width),
        "hedef_yukseklik": int(telemetry.target.height),
        "gps_saati": gps_clock_payload(gps_time),
    }


def parse_other_drones(payload: dict[str, Any]) -> list[OtherDrone]:
    drones: list[OtherDrone] = []
    for item in payload.get("konumBilgileri", []):
        drones.append(
            OtherDrone(
                team_id=int(item.get("takim_numarasi", 0)),
                position=GeoPoint(
                    lat=float(item.get("iha_enlem", 0.0)),
                    lon=float(item.get("iha_boylam", 0.0)),
                    altitude_m=float(item.get("iha_irtifa", 0.0)),
                ),
                heading_deg=float(item.get("iha_yonelme", 0.0)),
                latency_ms=int(item.get("zaman_farki", 0)),
                name=f"Team {item.get('takim_numarasi', '?')}",
            )
        )
    return drones


def parse_server_time(payload: dict[str, Any]) -> datetime:
    data = payload.get("sunucusaati", payload)
    now = datetime.now(timezone.utc)
    if isinstance(data, str):
        return datetime.fromisoformat(data)
    return datetime(
        year=now.year,
        month=now.month,
        day=int(data.get("gun", now.day)),
        hour=int(data.get("saat", 0)),
        minute=int(data.get("dakika", 0)),
        second=int(data.get("saniye", 0)),
        microsecond=int(data.get("milisaniye", 0)) * 1000,
        tzinfo=timezone.utc,
    )


def gps_clock_payload(moment: datetime) -> dict[str, int]:
    utc_moment = moment.astimezone(timezone.utc)
    return {
        "saat": utc_moment.hour,
        "dakika": utc_moment.minute,
        "saniye": utc_moment.second,
        "milisaniye": int(utc_moment.microsecond / 1000),
    }


def _validate_telemetry(telemetry: TelemetryData) -> None:
    _require_range("latitude", telemetry.position.lat, -90.0, 90.0)
    _require_range("longitude", telemetry.position.lon, -180.0, 180.0)
    _require_range("battery_percent", telemetry.battery_percent, 0, 100)
    _require_range("heading_deg", telemetry.heading_deg, 0, 360)
    _require_range("pitch_deg", telemetry.pitch_deg, -90.0, 90.0)
    _require_range("roll_deg", telemetry.roll_deg, -90.0, 90.0)
    if telemetry.ground_speed_mps < 0 or telemetry.air_speed_mps < 0:
        raise ApiError("Speed values cannot be negative")
    if telemetry.target.locked:
        if telemetry.target.center_x <= 0 or telemetry.target.center_y <= 0:
            raise ApiError("Locked target must provide non-zero center coordinates")
        if telemetry.target.width <= 0 or telemetry.target.height <= 0:
            raise ApiError("Locked target must provide non-zero size")


def _require_range(label: str, value: float, minimum: float, maximum: float) -> None:
    if not (minimum <= value <= maximum):
        raise ApiError(f"{label} must be in range {minimum}..{maximum}, got {value}")
