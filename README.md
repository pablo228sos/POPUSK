# Teknofest GCS

Open-source Ground Control Station for the Teknofest combat UAV workflow. The project is built with Python, PyQt6, Qt WebEngine, MAVLink, OpenStreetMap/Leaflet, OpenCV, and an async Teknofest API client.

## What is implemented

- PyQt6 desktop shell with map, telemetry, control, video, settings, and log panels.
- Qt WebEngine map panel with Leaflet, live UAV marker, track, route overlay, and zone rendering.
- MAVLink transport layer with support for 3DR serial telemetry (`COM` + baud) and UDP endpoints.
- VTOL / QuadPlane mission editor for `NAV_VTOL_TAKEOFF`, waypoint, loiter, `NAV_VTOL_LAND`, and `RTL`.
- Competition boundary editor with live out-of-bounds tracking and autopilot fence upload.
- Manual-mode switch counter and autonomy ratio tracking aligned with Teknofest round rules.
- Simulation mode for development when no aircraft or SITL is connected.
- Teknofest API client for login, server time sync, telemetry upload, HSS zone fetch, lock info, kamikaze info, and QR target fetch.
- Strict mission FSM: `INIT -> CONNECTED -> ARMED -> MISSION -> FAILSAFE/RTL`.
- Zone monitoring and A* route re-planning around no-fly and defense zones.
- OpenCV-based video pipeline with optional lightweight AI annotation, recording, and screenshots.
- CSV/JSONL logging for telemetry and events.

## Project layout

- `src/teknofest_gcs/main.py`: app entrypoint.
- `src/teknofest_gcs/runtime.py`: orchestration layer.
- `src/teknofest_gcs/api/client.py`: Teknofest API integration and payload validation.
- `src/teknofest_gcs/comm/mavlink.py`: MAVLink / 3DR connection worker.
- `src/teknofest_gcs/geo/*`: zones, route validation, A* avoidance.
- `src/teknofest_gcs/ui/*`: PyQt6 UI and Leaflet map.
- `tests/*`: regression tests for FSM, zone logic, and telemetry payload rules.

## Run

1. Create a virtual environment with Python 3.10+.
2. Install dependencies:

```bash
pip install -e .
```

3. Start the application:

```bash
teknofest-gcs
```

On first launch the app creates `settings.yaml` in the repo root. Edit that file to switch between:

- `simulation`
- `serial` for 3DR telemetry radios
- `udp` for SITL / network MAVLink

## 3DR configuration

Set in `settings.yaml`:

```yaml
connection:
  transport: "serial"
  serial_port: "COM3"
  baud_rate: 57600
```

For `Matek H743 + ArduPlane QuadPlane/Tailsitter`, keep the controller on ArduPilot Plane firmware and use QuadPlane modes such as `QSTABILIZE`, `QHOVER`, `QLOITER`, `QRTL`, and `QLAND`.

## Teknofest API notes

- The client syncs server time from `/api/sunucusaati` and falls back to `/api/servertime` if needed.
- Telemetry upload is rate-limited to 1 Hz.
- Session cookies are persisted in `.runtime/teknofest_session.json`.
- HSS zones returned by `/api/hss_koordinatlari` are merged into the live map as defense circles.
- `gps_saati` is generated from the telemetry timestamp so the payload can reflect onboard UTC/GPS time rather than local desktop time.

Important:

- Verify the payload names and response bodies against the latest official 2026 Teknofest documents before competition use.
- The latest official references used for this code are:
  - Fighter UAV Competition page: [https://www.teknofest.org/en/competitions/fighter-uav-competition/](https://www.teknofest.org/en/competitions/fighter-uav-competition/)
  - 2026 competition specification PDF: [https://cdn.teknofest.org/media/upload/userFormUpload/2026_SAVASAN_IHA_YARISMASI_SARTNAMESI_ENG_20_02_V2_LM7uv.pdf](https://cdn.teknofest.org/media/upload/userFormUpload/2026_SAVASAN_IHA_YARISMASI_SARTNAMESI_ENG_20_02_V2_LM7uv.pdf)
  - 2026 communication document PDF: [https://cdn.teknofest.org/media/upload/userFormUpload/Fighter_UAV_Communication_Documention_2026_en_19CLi.pdf](https://cdn.teknofest.org/media/upload/userFormUpload/Fighter_UAV_Communication_Documention_2026_en_19CLi.pdf)
  - ArduPilot QuadPlane AUTO missions: [https://ardupilot.org/plane/docs/quadplane-auto-mode.html](https://ardupilot.org/plane/docs/quadplane-auto-mode.html)
  - ArduPilot tailsitter guide: [https://ardupilot.org/plane/docs/guide-tailsitter.html](https://ardupilot.org/plane/docs/guide-tailsitter.html)
  - Mateksys H743-Wing board page: [https://ardupilot.org/plane/docs/common-matekh743-wing.html](https://ardupilot.org/plane/docs/common-matekh743-wing.html)

## Validation

Run the included tests:

```bash
python -m unittest discover -s tests -v
```

## Production hardening still recommended

- Replace public OSM tile URL with a local tile server for strict offline competition mode.
- Replace the placeholder OpenCV detector with the real Hailo / YOLO pipeline that publishes tracked target metadata.
- Add mission download and richer parameter management for the target autopilot.
- Add replay tooling and SITL automation scenarios.
