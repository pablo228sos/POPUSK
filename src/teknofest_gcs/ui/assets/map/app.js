const state = {
  map: null,
  bridge: null,
  vehicleMarker: null,
  vehicleLatLng: null,
  vehicleTrack: [],
  vehicleTrackLine: null,
  zonesLayer: null,
  draftLayer: null,
  routeLine: null,
  otherMarkers: [],
  waypointMarkers: [],
  editor: {
    mode: "none",
    label: "",
  },
};

function zoneColor(type) {
  if (type === "no_fly") return "#ef4444";
  if (type === "defense") return "#f59e0b";
  if (type === "competition") return "#e2f1ff";
  return "#38bdf8";
}

window.bootstrapMap = function bootstrapMap(config) {
  if (state.map) return;
  state.map = L.map("map", {
    zoomControl: false,
    preferCanvas: true,
  }).setView([config.center.lat, config.center.lon], config.zoom);

  L.tileLayer(config.tileUrl, {
    attribution: config.attribution,
    subdomains: ["a", "b", "c"],
    maxZoom: 20,
  }).addTo(state.map);

  state.zonesLayer = L.layerGroup().addTo(state.map);
  state.draftLayer = L.layerGroup().addTo(state.map);
  state.vehicleTrackLine = L.polyline([], {
    color: "#59ff65",
    weight: 4,
    opacity: 0.82,
  }).addTo(state.map);

  state.map.on("click", (event) => {
    if (!state.bridge || state.editor.mode === "none") return;
    state.bridge.reportMapClick(event.latlng.lat, event.latlng.lng);
  });

  if (window.qt && window.QWebChannel) {
    new QWebChannel(qt.webChannelTransport, (channel) => {
      state.bridge = channel.objects.bridge;
    });
  }
};

window.gcsUpdateVehicle = function gcsUpdateVehicle(payload) {
  if (!state.map) return;
  const latLng = [payload.lat, payload.lon];
  state.vehicleLatLng = latLng;
  const icon = L.divIcon({
    className: "vehicle-icon-wrapper",
    html: `<div class="vehicle-icon-shell"><div class="vehicle-icon" style="transform: rotate(${payload.heading}deg)">&#9992;</div></div>`,
    iconSize: [44, 44],
    iconAnchor: [22, 22],
  });
  if (!state.vehicleMarker) {
    state.vehicleMarker = L.marker(latLng, { icon }).addTo(state.map);
  } else {
    state.vehicleMarker.setLatLng(latLng);
    state.vehicleMarker.setIcon(icon);
  }
  state.vehicleMarker.bindPopup(
    `<div class="telemetry-popup"><b>UAV</b><br/>Mode: ${payload.mode}<br/>Heading: ${payload.heading.toFixed(1)}</div>`,
  );
  state.vehicleTrack.push(latLng);
  if (state.vehicleTrack.length > 300) state.vehicleTrack.shift();
  state.vehicleTrackLine.setLatLngs(state.vehicleTrack);
};

window.gcsUpdateOtherDrones = function gcsUpdateOtherDrones(drones) {
  if (!state.map) return;
  state.otherMarkers.forEach((marker) => marker.remove());
  state.otherMarkers = drones.map((drone) => {
    const marker = L.marker([drone.lat, drone.lon], {
      icon: L.divIcon({
        className: "other-drone-wrapper",
        html: `<div class="other-drone-badge">${drone.team_id}</div>`,
        iconSize: [28, 28],
        iconAnchor: [14, 14],
      }),
    }).addTo(state.map);
    marker.bindPopup(`<b>Team ${drone.team_id}</b><br/>Latency: ${drone.latency_ms} ms`);
    return marker;
  });
};

window.gcsUpdateZones = function gcsUpdateZones(zones) {
  if (!state.map || !state.zonesLayer) return;
  state.zonesLayer.clearLayers();
  zones.forEach((zone) => {
    const color = zoneColor(zone.type);
    if (zone.center && zone.radius_m) {
      L.circle([zone.center.lat, zone.center.lon], {
        radius: zone.radius_m,
        color,
        weight: 2,
        fillColor: color,
        fillOpacity: zone.type === "mission" ? 0.15 : zone.type === "competition" ? 0.03 : 0.24,
        dashArray: zone.type === "competition" ? "10 8" : null,
      }).bindTooltip(zone.label || zone.id).addTo(state.zonesLayer);
      return;
    }
    const points = zone.points.map((point) => [point.lat, point.lon]);
    L.polygon(points, {
      color,
      weight: zone.type === "competition" ? 3 : 2,
      fillColor: color,
      fillOpacity: zone.type === "competition" ? 0.03 : 0.22,
      dashArray: zone.type === "competition" ? "10 8" : null,
    }).bindTooltip(zone.label || zone.id).addTo(state.zonesLayer);
  });
};

window.gcsUpdateRoute = function gcsUpdateRoute(route) {
  if (!state.map) return;
  if (state.routeLine) state.routeLine.remove();
  state.waypointMarkers.forEach((marker) => marker.remove());
  state.waypointMarkers = [];

  if (!route.length) {
    state.routeLine = null;
    return;
  }

  state.routeLine = L.polyline(route.map((point) => [point.lat, point.lon]), {
    color: "#d9f542",
    weight: 2.5,
    opacity: 0.92,
  }).addTo(state.map);

  route.forEach((point, index) => {
    const label = index === 0 ? "1" : `${index + 1}`;
    const marker = L.marker([point.lat, point.lon], {
      icon: L.divIcon({
        className: "waypoint-wrapper",
        html: `<div class="waypoint-badge wp-badge">${label}</div>`,
        iconSize: [34, 34],
        iconAnchor: [17, 17],
      }),
    }).addTo(state.map);
    state.waypointMarkers.push(marker);
  });
};

window.gcsZoomIn = function gcsZoomIn() {
  if (!state.map) return;
  state.map.zoomIn();
};

window.gcsZoomOut = function gcsZoomOut() {
  if (!state.map) return;
  state.map.zoomOut();
};

window.gcsCenterOnVehicle = function gcsCenterOnVehicle() {
  if (!state.map || !state.vehicleLatLng) return;
  state.map.panTo(state.vehicleLatLng, { animate: true, duration: 0.4 });
};

window.gcsSetEditorState = function gcsSetEditorState(payload) {
  state.editor = payload;
  const container = document.getElementById("map");
  if (!container) return;
  container.dataset.editorMode = payload.mode || "none";
};

window.gcsUpdateDraft = function gcsUpdateDraft(payload) {
  if (!state.map || !state.draftLayer) return;
  state.draftLayer.clearLayers();
  const points = payload.points || [];
  if (!points.length) return;

  const latLngs = points.map((point) => [point.lat, point.lon]);
  if (payload.radius_m && points.length === 1) {
    L.circle(latLngs[0], {
      radius: payload.radius_m,
      color: zoneColor(payload.zone_type || "defense"),
      weight: 2,
      dashArray: "8 6",
      fillOpacity: 0.14,
    }).addTo(state.draftLayer);
    return;
  }

  L.polyline(latLngs, {
    color: "#f8fafc",
    weight: 2,
    dashArray: "6 6",
    opacity: 0.85,
  }).addTo(state.draftLayer);

  latLngs.forEach((latLng) => {
    L.circleMarker(latLng, {
      radius: 4,
      color: "#ffffff",
      weight: 1,
      fillOpacity: 1,
    }).addTo(state.draftLayer);
  });
};
