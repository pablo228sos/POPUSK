const state = {
  map: null,
  bridge: null,
  vehicles: {}, // Maps vehicle_id -> { marker, trackLine, trackPoints, selected }
  zonesLayer: null,
  selectedVehicleId: null,
  editorMode: "none",
  waypointMarkers: [],
  routeLine: null
};

window.bootstrapMap = function bootstrapMap(config) {
  if (state.map) return;
  state.map = L.map("map", {
    zoomControl: false,
    preferCanvas: true
  }).setView([config.center.lat, config.center.lon], config.zoom);

  L.tileLayer(config.tileUrl, {
    attribution: config.attribution,
    maxZoom: 20
  }).addTo(state.map);

  state.zonesLayer = L.layerGroup().addTo(state.map);

  // Bind map click handler
  state.map.on("click", (event) => {
    if (state.bridge) {
      state.bridge.reportMapClick(event.latlng.lat, event.latlng.lng);
    }
  });

  // Init WebChannel
  if (window.qt && window.QWebChannel) {
    new QWebChannel(qt.webChannelTransport, (channel) => {
      state.bridge = channel.objects.bridge;
      console.log("QWebChannel connected successfully!");
    });
  }
};

window.gcsSelectVehicle = function gcsSelectVehicle(vehicleId) {
  state.selectedVehicleId = vehicleId;
  // Redraw all markers to show selected state
  Object.keys(state.vehicles).forEach((id) => {
    const v = state.vehicles[id];
    const isSelected = parseInt(id) === vehicleId;
    v.selected = isSelected;
    
    // Update marker styling
    if (v.marker) {
      const shell = v.marker.getElement()?.querySelector(".vehicle-icon-shell");
      if (shell) {
        if (isSelected) {
          shell.classList.add("selected");
        } else {
          shell.classList.remove("selected");
        }
      }
    }
  });
};

window.gcsUpdateVehicles = function gcsUpdateVehicles(fleet) {
  if (!state.map) return;
  
  const currentIds = new Set(fleet.map(v => v.id.toString()));

  // Remove stale vehicles
  Object.keys(state.vehicles).forEach((id) => {
    if (!currentIds.has(id)) {
      state.vehicles[id].marker.remove();
      state.vehicles[id].trackLine.remove();
      delete state.vehicles[id];
    }
  });

  // Update or add active vehicles
  fleet.forEach((payload) => {
    const idStr = payload.id.toString();
    const latLng = [payload.lat, payload.lon];
    const isArmed = payload.armed;
    const heading = payload.heading;
    const isSelected = payload.id === state.selectedVehicleId;

    if (!state.vehicles[idStr]) {
      // Create new vehicle object
      const trackPoints = [latLng];
      const trackLine = L.polyline(trackPoints, {
        color: getRandomColor(payload.id),
        weight: 3,
        opacity: 0.6,
        dashArray: "4 4"
      }).addTo(state.map);

      state.vehicles[idStr] = {
        marker: null,
        trackLine: trackLine,
        trackPoints: trackPoints,
        selected: isSelected
      };
    }

    const v = state.vehicles[idStr];
    v.trackPoints.push(latLng);
    if (v.trackPoints.length > 500) {
      v.trackPoints.shift();
    }
    v.trackLine.setLatLngs(v.trackPoints);

    const armedClass = isArmed ? "armed" : "";
    const selectedClass = isSelected ? "selected" : "";
    
    const icon = L.divIcon({
      className: "vehicle-icon-wrapper",
      html: `
        <div class="vehicle-icon-shell ${armedClass} ${selectedClass}">
          <div class="vehicle-icon" style="transform: rotate(${heading}deg)">&#9992;</div>
          <div class="vehicle-badge-id">${payload.id}</div>
        </div>
      `,
      iconSize: [44, 44],
      iconAnchor: [22, 22]
    });

    if (!v.marker) {
      v.marker = L.marker(latLng, { icon }).addTo(state.map);
      v.marker.on("click", () => {
        if (state.bridge) {
          state.bridge.reportVehicleClicked(payload.id);
        }
      });
    } else {
      v.marker.setLatLng(latLng);
      v.marker.setIcon(icon);
    }

    v.marker.bindPopup(`
      <div class="telemetry-popup">
        <b>БПЛА ${payload.id}</b><br/>
        Режим: <span style="color: #38bdf8; font-weight: bold;">${payload.mode}</span><br/>
        Высота: ${payload.alt.toFixed(1)} м<br/>
        Заряд: ${payload.battery}% (${payload.battery_v.toFixed(1)} В)<br/>
        Связь: ${payload.rssi}%
      </div>
    `);
  });
};

window.gcsUpdateRoute = function gcsUpdateRoute(route) {
  if (!state.map) return;
  if (state.routeLine) state.routeLine.remove();
  state.waypointMarkers.forEach((marker) => marker.remove());
  state.waypointMarkers = [];

  if (!route || !route.length) {
    state.routeLine = null;
    return;
  }

  state.routeLine = L.polyline(route.map((p) => [p.lat, p.lon]), {
    color: "#f59e0b",
    weight: 3,
    opacity: 0.9
  }).addTo(state.map);

  route.forEach((point, index) => {
    const marker = L.marker([point.lat, point.lon], {
      icon: L.divIcon({
        className: "waypoint-wrapper",
        html: `<div class="waypoint-badge">${index + 1}</div>`,
        iconSize: [24, 24],
        iconAnchor: [12, 12]
      })
    }).addTo(state.map);
    state.waypointMarkers.push(marker);
  });
};

window.gcsZoomIn = function gcsZoomIn() {
  if (state.map) state.map.zoomIn();
};

window.gcsZoomOut = function gcsZoomOut() {
  if (state.map) state.map.zoomOut();
};

window.gcsCenterOnVehicle = function gcsCenterOnVehicle() {
  if (!state.map || !state.selectedVehicleId) return;
  const v = state.vehicles[state.selectedVehicleId.toString()];
  if (v && v.marker) {
    state.map.panTo(v.marker.getLatLng(), { animate: true });
  }
};

function getRandomColor(id) {
  const colors = ["#38bdf8", "#34d399", "#fb7185", "#f472b6", "#fbbf24", "#a78bfa", "#2dd4bf"];
  return colors[id % colors.length];
}
