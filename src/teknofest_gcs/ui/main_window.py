from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QCloseEvent, QImage, QPixmap
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from teknofest_gcs.ai.processor import AiProcessor
from teknofest_gcs.config.settings import Settings
from teknofest_gcs.core.models import ControlAuthority, GeoPoint, Zone, ZoneType
from teknofest_gcs.geo.zones import haversine_distance_m
from teknofest_gcs.runtime import GcsRuntime
from teknofest_gcs.ui.hud_widgets import RingGauge
from teknofest_gcs.ui.map_view import MapView
from teknofest_gcs.video.service import VideoWorker


class MainWindow(QMainWindow):
    TOP_HEIGHT = 74
    LEFT_WIDTH = 76
    RIGHT_WIDTH = 460
    EDGE = 18

    def __init__(self, settings: Settings, settings_path: Path) -> None:
        super().__init__()
        self.settings = settings
        self.settings_path = settings_path
        self.runtime = GcsRuntime(settings)
        self.ai_processor = AiProcessor(enabled=settings.ai.enabled, annotate_frames=settings.ai.annotate_frames)
        self.video_worker = VideoWorker(settings.video.source, settings.video.output_dir, self.ai_processor)
        self.flight_started_at: datetime | None = None
        self._last_message = "System ready"
        self.editor_mode = "none"
        self.draft_points: list[GeoPoint] = []
        self.zone_sequence = 1

        self.setWindowTitle(settings.app.title)
        self.resize(1760, 1020)
        self.setMinimumSize(1420, 860)
        self._build_ui()
        self._apply_styles()
        self._bind_runtime()
        self._bind_video()

        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(1000)
        self._clock_timer.timeout.connect(self._update_flight_timer)
        self._clock_timer.start()

        self.runtime.start()
        self.video_worker.start()

    def closeEvent(self, event: QCloseEvent) -> None:
        self.video_worker.stop()
        self.video_worker.wait(1000)
        self.runtime.stop()
        super().closeEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._position_overlays()

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("RootSurface")
        self.setCentralWidget(root)

        self.map_view = MapView(self.settings.map)
        self.map_view.setParent(root)

        self.top_bar = self._build_top_bar(root)
        self.left_toolbar = self._build_left_toolbar(root)
        self.right_panel = self._build_right_panel(root)

        self._position_overlays()

    def _build_top_bar(self, parent: QWidget) -> QFrame:
        frame = QFrame(parent)
        frame.setObjectName("TopBar")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(18, 12, 18, 12)
        layout.setSpacing(12)

        self.brand_label = QLabel(f"{self.settings.aircraft.aircraft_name} / TEKNOFEST GCS")
        self.brand_label.setObjectName("BrandLabel")
        self.brand_label.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)

        self.connection_chip = QLabel("LINK OFF")
        self.connection_chip.setObjectName("ChipBlue")
        self.state_chip = QLabel("INIT")
        self.state_chip.setObjectName("ChipGreen")
        self.mode_chip = QLabel("QSTABILIZE")
        self.mode_chip.setObjectName("ChipAmber")
        self.authority_chip = QLabel("MANUAL")
        self.authority_chip.setObjectName("ChipDark")
        self.timer_chip = QLabel("00:00:00")
        self.timer_chip.setObjectName("ChipDark")
        self.message_chip = QLabel(self._last_message)
        self.message_chip.setObjectName("ChipMessage")
        self.message_chip.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        for chip in [
            self.connection_chip,
            self.state_chip,
            self.mode_chip,
            self.authority_chip,
            self.timer_chip,
            self.message_chip,
        ]:
            chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
            chip.setMinimumHeight(42)

        layout.addWidget(self.brand_label)
        layout.addWidget(self.connection_chip)
        layout.addWidget(self.state_chip)
        layout.addWidget(self.mode_chip)
        layout.addWidget(self.authority_chip)
        layout.addWidget(self.timer_chip)
        layout.addWidget(self.message_chip, 1)
        return frame

    def _build_left_toolbar(self, parent: QWidget) -> QFrame:
        frame = QFrame(parent)
        frame.setObjectName("ToolRail")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        buttons = [
            ("ACT", lambda: self._switch_panel(0)),
            ("MIS", lambda: self._switch_panel(1)),
            ("+", self.map_view.zoom_in),
            ("-", self.map_view.zoom_out),
            ("CTR", self.map_view.center_on_vehicle),
            ("HSS", self.runtime.refresh_hss),
            ("X", self._cancel_editor),
        ]
        for label, handler in buttons:
            button = QPushButton(label)
            button.setObjectName("RailButton")
            button.clicked.connect(handler)
            button.setFixedSize(54, 54)
            layout.addWidget(button)
        layout.addStretch(1)
        return frame

    def _build_right_panel(self, parent: QWidget) -> QFrame:
        frame = QFrame(parent)
        frame.setObjectName("RightPanel")
        outer = QVBoxLayout(frame)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(0)
        self.tab_actions_btn = QPushButton("Actions")
        self.tab_routes_btn = QPushButton("Planner")
        self.tab_actions_btn.setCheckable(True)
        self.tab_routes_btn.setCheckable(True)
        self.tab_actions_btn.setChecked(True)
        self.tab_actions_btn.clicked.connect(lambda: self._switch_panel(0))
        self.tab_routes_btn.clicked.connect(lambda: self._switch_panel(1))
        self._tab_group = QButtonGroup(self)
        self._tab_group.setExclusive(True)
        self._tab_group.addButton(self.tab_actions_btn)
        self._tab_group.addButton(self.tab_routes_btn)
        for button in [self.tab_actions_btn, self.tab_routes_btn]:
            button.setObjectName("PanelTab")
            button.setMinimumHeight(40)
            header.addWidget(button)
        outer.addLayout(header)

        self.panel_stack = QStackedWidget()
        self.panel_stack.addWidget(self._build_actions_page())
        self.panel_stack.addWidget(self._build_planner_page())
        outer.addWidget(self.panel_stack, 1)
        return frame

    def _build_actions_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        ops_block = QFrame()
        ops_block.setObjectName("GlassBlock")
        ops_layout = QVBoxLayout(ops_block)
        ops_layout.setContentsMargins(14, 14, 14, 14)
        ops_layout.setSpacing(10)
        ops_title = QLabel("Flight Ops")
        ops_title.setObjectName("BlockTitle")
        ops_layout.addWidget(ops_title)

        actions = [
            ("ARM", self._arm),
            ("DISARM", self.runtime.disarm),
            ("UPLOAD MISSION", self._upload_mission),
            ("UPLOAD FENCE", self.runtime.upload_fence),
            ("START AUTO", self._start_mission),
            ("SAVE CFG", self._save_settings),
        ]
        action_grid = QGridLayout()
        action_grid.setHorizontalSpacing(8)
        action_grid.setVerticalSpacing(8)
        for index, (label, handler) in enumerate(actions):
            button = QPushButton(label)
            button.setObjectName("ActionButton")
            button.clicked.connect(handler)
            action_grid.addWidget(button, index // 2, index % 2)
        ops_layout.addLayout(action_grid)
        layout.addWidget(ops_block)

        mode_block = QFrame()
        mode_block.setObjectName("GlassBlock")
        mode_layout = QVBoxLayout(mode_block)
        mode_layout.setContentsMargins(14, 14, 14, 14)
        mode_layout.setSpacing(10)
        mode_title = QLabel("Mode Control")
        mode_title.setObjectName("BlockTitle")
        mode_layout.addWidget(mode_title)

        mode_grid = QGridLayout()
        mode_grid.setHorizontalSpacing(8)
        mode_grid.setVerticalSpacing(8)
        mode_actions = [
            ("MANUAL", lambda: self.runtime.set_manual_mode("QSTABILIZE")),
            ("QHOVER", lambda: self.runtime.set_flight_mode("QHOVER")),
            ("QLOITER", lambda: self.runtime.set_flight_mode("QLOITER")),
            ("AUTO", self.runtime.set_auto_mode),
            ("GUIDED", lambda: self.runtime.set_flight_mode("GUIDED")),
            ("AI FOLLOW", self._engage_ai_follow),
            ("QRTL", lambda: self.runtime.trigger_rtl("operator")),
            ("QLAND", lambda: self.runtime.trigger_qland("operator")),
        ]
        for index, (label, handler) in enumerate(mode_actions):
            button = QPushButton(label)
            button.setObjectName("ActionButton")
            button.clicked.connect(handler)
            mode_grid.addWidget(button, index // 2, index % 2)
        mode_layout.addLayout(mode_grid)

        follow_row = QHBoxLayout()
        follow_label = QLabel("AI Target")
        follow_label.setObjectName("MetricCaption")
        self.ai_target_combo = QComboBox()
        self.ai_target_combo.addItem("Nearest", None)
        follow_row.addWidget(follow_label)
        follow_row.addWidget(self.ai_target_combo, 1)
        mode_layout.addLayout(follow_row)
        layout.addWidget(mode_block)

        telemetry_frame = QFrame()
        telemetry_frame.setObjectName("GlassBlock")
        telemetry_layout = QVBoxLayout(telemetry_frame)
        telemetry_layout.setContentsMargins(14, 14, 14, 14)
        telemetry_layout.setSpacing(10)
        title = QLabel("Flight Telemetry")
        title.setObjectName("BlockTitle")
        telemetry_layout.addWidget(title)

        self.telemetry_labels = {
            "lat": QLabel("0.000000"),
            "lon": QLabel("0.000000"),
            "alt": QLabel("0.0 m"),
            "ground_speed": QLabel("0.0 m/s"),
            "air_speed": QLabel("0.0 m/s"),
            "heading": QLabel("0.0 deg"),
            "battery": QLabel("100%"),
            "mode": QLabel("STANDBY"),
        }
        self.metric_labels = {
            "home_distance": QLabel("0.00 km"),
            "route_length": QLabel("0.00 km"),
            "waypoints": QLabel("0"),
            "api": QLabel("Idle"),
        }

        metric_grid = QGridLayout()
        metric_grid.setHorizontalSpacing(18)
        metric_grid.setVerticalSpacing(8)
        pairs = [
            ("Lat", self.telemetry_labels["lat"]),
            ("Lon", self.telemetry_labels["lon"]),
            ("Altitude", self.telemetry_labels["alt"]),
            ("Gnd speed", self.telemetry_labels["ground_speed"]),
            ("Air speed", self.telemetry_labels["air_speed"]),
            ("Heading", self.telemetry_labels["heading"]),
            ("Battery", self.telemetry_labels["battery"]),
            ("Mode", self.telemetry_labels["mode"]),
        ]
        for index, (caption, value) in enumerate(pairs):
            label = QLabel(caption)
            label.setObjectName("MetricCaption")
            value.setObjectName("MetricValue")
            metric_grid.addWidget(label, index, 0)
            metric_grid.addWidget(value, index, 1)
        telemetry_layout.addLayout(metric_grid)

        info_row = QHBoxLayout()
        info_row.setSpacing(12)
        self.ring_gauge = RingGauge()
        info_row.addWidget(self.ring_gauge, 0, Qt.AlignmentFlag.AlignCenter)

        status_col = QVBoxLayout()
        status_col.setSpacing(8)
        for caption, key in [
            ("Home Dist", "home_distance"),
            ("Route Len", "route_length"),
            ("Waypoints", "waypoints"),
            ("API", "api"),
        ]:
            block = QFrame()
            block.setObjectName("InsetBlock")
            block_layout = QVBoxLayout(block)
            block_layout.setContentsMargins(10, 10, 10, 10)
            block_layout.setSpacing(2)
            block_caption = QLabel(caption)
            block_caption.setObjectName("InsetCaption")
            block_value = self.metric_labels[key]
            block_value.setObjectName("InsetValue")
            block_layout.addWidget(block_caption)
            block_layout.addWidget(block_value)
            status_col.addWidget(block)
        info_row.addLayout(status_col, 1)
        telemetry_layout.addLayout(info_row)
        layout.addWidget(telemetry_frame)

        video_frame = QFrame()
        video_frame.setObjectName("GlassBlock")
        video_layout = QVBoxLayout(video_frame)
        video_layout.setContentsMargins(14, 14, 14, 14)
        video_layout.setSpacing(10)
        video_title = QLabel("Video / AI")
        video_title.setObjectName("BlockTitle")
        video_layout.addWidget(video_title)

        self.video_label = QLabel("Video stream idle")
        self.video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_label.setMinimumHeight(180)
        self.video_label.setObjectName("VideoPreview")
        video_layout.addWidget(self.video_label)

        video_controls = QHBoxLayout()
        start_record_btn = QPushButton("REC")
        stop_record_btn = QPushButton("STOP")
        screenshot_btn = QPushButton("SHOT")
        for button in [start_record_btn, stop_record_btn, screenshot_btn]:
            button.setObjectName("SmallAction")
        start_record_btn.clicked.connect(self.video_worker.start_recording)
        stop_record_btn.clicked.connect(self.video_worker.stop_recording)
        screenshot_btn.clicked.connect(self._take_screenshot)
        video_controls.addWidget(start_record_btn)
        video_controls.addWidget(stop_record_btn)
        video_controls.addWidget(screenshot_btn)
        video_layout.addLayout(video_controls)

        self.ai_checkbox = QCheckBox("Enable AI pipeline (Raspberry Pi + Hailo companion ready)")
        self.ai_checkbox.setChecked(self.settings.ai.enabled)
        self.ai_checkbox.toggled.connect(self._toggle_ai)
        video_layout.addWidget(self.ai_checkbox)

        self.detections_label = QLabel("Detections: 0")
        self.detections_label.setObjectName("MetricValue")
        video_layout.addWidget(self.detections_label)
        layout.addWidget(video_frame)
        return page

    def _build_planner_page(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setObjectName("ConfigScroll")
        outer.addWidget(scroll)

        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        route_frame = QFrame()
        route_frame.setObjectName("GlassBlock")
        route_layout = QVBoxLayout(route_frame)
        route_layout.setContentsMargins(14, 14, 14, 14)
        route_layout.setSpacing(10)
        title = QLabel("Mission / Route")
        title.setObjectName("BlockTitle")
        route_layout.addWidget(title)

        self.route_summary = QLabel("No mission loaded")
        self.route_summary.setObjectName("RouteSummary")
        route_layout.addWidget(self.route_summary)

        self.editor_hint = QLabel("Editor: idle")
        self.editor_hint.setObjectName("MetricCaption")
        route_layout.addWidget(self.editor_hint)

        self.mission_manifest = QPlainTextEdit()
        self.mission_manifest.setObjectName("DataArea")
        self.mission_manifest.setReadOnly(True)
        self.mission_manifest.setPlaceholderText("Mission items will appear here.")
        route_layout.addWidget(self.mission_manifest, 1)

        self.other_drones_label = QPlainTextEdit()
        self.other_drones_label.setObjectName("DataArea")
        self.other_drones_label.setReadOnly(True)
        self.other_drones_label.setPlaceholderText("Other UAVs from Teknofest telemetry responses.")
        route_layout.addWidget(self.other_drones_label, 1)

        self.competition_status_output = QPlainTextEdit()
        self.competition_status_output.setObjectName("DataArea")
        self.competition_status_output.setReadOnly(True)
        self.competition_status_output.setPlaceholderText("Competition counters will appear here.")
        route_layout.addWidget(self.competition_status_output, 1)
        layout.addWidget(route_frame, 1)

        mission_editor = QFrame()
        mission_editor.setObjectName("GlassBlock")
        mission_layout = QVBoxLayout(mission_editor)
        mission_layout.setContentsMargins(14, 14, 14, 14)
        mission_layout.setSpacing(10)
        mission_title = QLabel("Mission Editor")
        mission_title.setObjectName("BlockTitle")
        mission_layout.addWidget(mission_title)

        form = QFormLayout()
        self.default_altitude_spin = QDoubleSpinBox()
        self.default_altitude_spin.setRange(0.0, 500.0)
        self.default_altitude_spin.setDecimals(1)
        self.default_altitude_spin.setValue(self.settings.aircraft.cruise_altitude_m)
        self.takeoff_altitude_spin = QDoubleSpinBox()
        self.takeoff_altitude_spin.setRange(5.0, 200.0)
        self.takeoff_altitude_spin.setDecimals(1)
        self.takeoff_altitude_spin.setValue(self.settings.aircraft.mission_takeoff_alt_m)
        self.loiter_spin = QDoubleSpinBox()
        self.loiter_spin.setRange(1.0, 120.0)
        self.loiter_spin.setDecimals(1)
        self.loiter_spin.setValue(10.0)
        self.follow_distance_spin = QDoubleSpinBox()
        self.follow_distance_spin.setRange(1.0, 50.0)
        self.follow_distance_spin.setDecimals(1)
        self.follow_distance_spin.setValue(self.settings.ai.follow_distance_m)
        self.follow_distance_spin.valueChanged.connect(self._update_follow_distance)
        form.addRow("Cruise Alt", self.default_altitude_spin)
        form.addRow("VTOL Takeoff Alt", self.takeoff_altitude_spin)
        form.addRow("Loiter Sec", self.loiter_spin)
        form.addRow("AI Follow Dist", self.follow_distance_spin)
        mission_layout.addLayout(form)

        mission_buttons = QGridLayout()
        mission_buttons.setHorizontalSpacing(8)
        mission_buttons.setVerticalSpacing(8)
        mission_actions = [
            ("ADD VTOL TKOF", self._add_takeoff_item),
            ("ADD WP ON MAP", self._begin_add_waypoint),
            ("ADD LOITER ON MAP", self._begin_add_loiter),
            ("ADD VTOL LAND", self._begin_add_land),
            ("ADD RTL", self.runtime.add_rtl),
            ("CLEAR MISSION", self.runtime.clear_mission),
        ]
        for index, (label, handler) in enumerate(mission_actions):
            button = QPushButton(label)
            button.setObjectName("ActionButton")
            button.clicked.connect(handler)
            mission_buttons.addWidget(button, index // 2, index % 2)
        mission_layout.addLayout(mission_buttons)
        layout.addWidget(mission_editor)

        boundary_editor = QFrame()
        boundary_editor.setObjectName("GlassBlock")
        boundary_layout = QVBoxLayout(boundary_editor)
        boundary_layout.setContentsMargins(14, 14, 14, 14)
        boundary_layout.setSpacing(10)
        boundary_title = QLabel("Competition Boundary")
        boundary_title.setObjectName("BlockTitle")
        boundary_layout.addWidget(boundary_title)

        self.boundary_manifest = QLabel("Boundary not configured")
        self.boundary_manifest.setObjectName("RouteSummary")
        boundary_layout.addWidget(self.boundary_manifest)

        boundary_buttons = QGridLayout()
        boundary_buttons.setHorizontalSpacing(8)
        boundary_buttons.setVerticalSpacing(8)
        boundary_actions = [
            ("DRAW BORDER", self._begin_competition_boundary),
            ("SET BORDER", self._finish_competition_boundary),
            ("CLEAR BORDER", self.runtime.clear_competition_boundary),
        ]
        for index, (label, handler) in enumerate(boundary_actions):
            button = QPushButton(label)
            button.setObjectName("ActionButton")
            button.clicked.connect(handler)
            boundary_buttons.addWidget(button, 0, index)
        boundary_layout.addLayout(boundary_buttons)
        layout.addWidget(boundary_editor)

        zone_editor = QFrame()
        zone_editor.setObjectName("GlassBlock")
        zone_layout = QVBoxLayout(zone_editor)
        zone_layout.setContentsMargins(14, 14, 14, 14)
        zone_layout.setSpacing(10)
        zone_title = QLabel("Zone Editor")
        zone_title.setObjectName("BlockTitle")
        zone_layout.addWidget(zone_title)

        zone_form = QFormLayout()
        self.zone_type_combo = QComboBox()
        self.zone_type_combo.addItem("No-Fly", ZoneType.NO_FLY)
        self.zone_type_combo.addItem("Mission", ZoneType.MISSION)
        self.zone_type_combo.addItem("Defense", ZoneType.DEFENSE)
        self.zone_radius_spin = QDoubleSpinBox()
        self.zone_radius_spin.setRange(20.0, 5000.0)
        self.zone_radius_spin.setDecimals(1)
        self.zone_radius_spin.setValue(150.0)
        zone_form.addRow("Zone Type", self.zone_type_combo)
        zone_form.addRow("Circle Radius m", self.zone_radius_spin)
        zone_layout.addLayout(zone_form)

        zone_buttons = QGridLayout()
        zone_buttons.setHorizontalSpacing(8)
        zone_buttons.setVerticalSpacing(8)
        zone_actions = [
            ("POLYGON", self._begin_zone_polygon),
            ("CIRCLE", self._begin_zone_circle),
            ("FINISH", self._finish_zone),
            ("CLEAR DRAFT", self._cancel_editor),
            ("CLEAR ZONES", self.runtime.clear_user_zones),
            ("FETCH HSS", self.runtime.refresh_hss),
        ]
        for index, (label, handler) in enumerate(zone_actions):
            button = QPushButton(label)
            button.setObjectName("ActionButton")
            button.clicked.connect(handler)
            zone_buttons.addWidget(button, index // 2, index % 2)
        zone_layout.addLayout(zone_buttons)

        self.zone_manifest = QPlainTextEdit()
        self.zone_manifest.setObjectName("DataArea")
        self.zone_manifest.setReadOnly(True)
        self.zone_manifest.setPlaceholderText("Configured zones will appear here.")
        zone_layout.addWidget(self.zone_manifest)
        layout.addWidget(zone_editor)

        config_frame = QFrame()
        config_frame.setObjectName("GlassBlock")
        form_layout = QFormLayout(config_frame)
        form_layout.setContentsMargins(14, 14, 14, 14)
        form_layout.setSpacing(8)

        self.transport_combo = QComboBox()
        self.transport_combo.addItems(["simulation", "serial", "udp"])
        self.transport_combo.setCurrentText(self.settings.connection.transport)
        self.serial_port_edit = QLineEdit(self.settings.connection.serial_port)
        self.baud_rate_edit = QLineEdit(str(self.settings.connection.baud_rate))
        self.udp_edit = QLineEdit(self.settings.connection.udp_endpoint)
        self.tile_url_edit = QLineEdit(self.settings.map.tile_url)
        self.api_url_edit = QLineEdit(self.settings.teknofest_api.base_url)
        self.api_user_edit = QLineEdit(self.settings.teknofest_api.username)
        self.api_pass_edit = QLineEdit(self.settings.teknofest_api.password)
        self.api_pass_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.video_source_edit = QLineEdit(self.settings.video.source)

        form_layout.addRow("Transport", self.transport_combo)
        form_layout.addRow("3DR / COM", self.serial_port_edit)
        form_layout.addRow("Baud", self.baud_rate_edit)
        form_layout.addRow("UDP endpoint", self.udp_edit)
        form_layout.addRow("Tile URL", self.tile_url_edit)
        form_layout.addRow("API URL", self.api_url_edit)
        form_layout.addRow("Username", self.api_user_edit)
        form_layout.addRow("Password", self.api_pass_edit)
        form_layout.addRow("Video source", self.video_source_edit)
        layout.addWidget(config_frame)

        apply_btn = QPushButton("Apply + Save")
        apply_btn.setObjectName("ActionButton")
        apply_btn.clicked.connect(self._apply_settings)
        layout.addWidget(apply_btn)

        logs_frame = QFrame()
        logs_frame.setObjectName("GlassBlock")
        logs_layout = QVBoxLayout(logs_frame)
        logs_layout.setContentsMargins(14, 14, 14, 14)
        logs_layout.setSpacing(10)
        logs_title = QLabel("Event Log")
        logs_title.setObjectName("BlockTitle")
        logs_layout.addWidget(logs_title)
        self.log_output = QPlainTextEdit()
        self.log_output.setObjectName("DataArea")
        self.log_output.setReadOnly(True)
        self.log_output.document().setMaximumBlockCount(250)
        logs_layout.addWidget(self.log_output)
        layout.addWidget(logs_frame)

        layout.addStretch(1)
        scroll.setWidget(body)
        return page

    def _position_overlays(self) -> None:
        root = self.centralWidget()
        if root is None:
            return
        width = root.width()
        height = root.height()

        self.map_view.setGeometry(0, 0, width, height)
        self.top_bar.setGeometry(self.EDGE, self.EDGE, width - self.EDGE * 2, self.TOP_HEIGHT)
        self.left_toolbar.setGeometry(
            self.EDGE,
            self.EDGE + self.TOP_HEIGHT + 12,
            self.LEFT_WIDTH,
            min(470, height - self.TOP_HEIGHT - self.EDGE * 3),
        )
        self.right_panel.setGeometry(
            width - self.RIGHT_WIDTH - self.EDGE,
            self.EDGE + self.TOP_HEIGHT + 12,
            self.RIGHT_WIDTH,
            height - self.TOP_HEIGHT - self.EDGE * 3 - 12,
        )
        self.top_bar.raise_()
        self.left_toolbar.raise_()
        self.right_panel.raise_()

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget#RootSurface {
                background: #05080c;
                color: #eef4ff;
                font-family: "Segoe UI";
            }
            QFrame#TopBar, QFrame#ToolRail, QFrame#RightPanel, QFrame#GlassBlock {
                background: rgba(7, 12, 17, 185);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 18px;
            }
            QFrame#InsetBlock {
                background: rgba(255, 255, 255, 0.03);
                border: 1px solid rgba(255, 255, 255, 0.06);
                border-radius: 14px;
            }
            QLabel#BrandLabel {
                font-size: 26px;
                font-weight: 800;
                letter-spacing: 1px;
                color: #f4f7fb;
                padding: 0 8px;
            }
            QLabel#ChipBlue, QLabel#ChipGreen, QLabel#ChipAmber, QLabel#ChipDark, QLabel#ChipMessage {
                border-radius: 14px;
                padding: 0 18px;
                font-size: 16px;
                font-weight: 700;
            }
            QLabel#ChipBlue { background: rgba(24, 130, 232, 0.88); }
            QLabel#ChipGreen { background: rgba(30, 164, 61, 0.88); }
            QLabel#ChipAmber { background: rgba(194, 147, 14, 0.9); }
            QLabel#ChipDark { background: rgba(16, 22, 30, 0.9); }
            QLabel#ChipMessage {
                background: rgba(23, 142, 235, 0.82);
                padding-left: 20px;
                padding-right: 20px;
            }
            QPushButton#RailButton {
                background: rgba(255, 255, 255, 0.06);
                color: #f6fbff;
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 14px;
                font-size: 13px;
                font-weight: 800;
            }
            QPushButton#RailButton:hover { background: rgba(40, 165, 255, 0.22); }
            QPushButton#PanelTab {
                background: rgba(14, 20, 28, 0.92);
                color: #93a7c4;
                border: none;
                font-size: 15px;
                font-weight: 700;
                border-radius: 12px;
            }
            QPushButton#PanelTab:checked {
                background: rgba(23, 145, 241, 0.95);
                color: #ffffff;
            }
            QPushButton#ActionButton, QPushButton#SmallAction {
                background: rgba(24, 145, 242, 0.9);
                color: white;
                border: none;
                border-radius: 12px;
                min-height: 40px;
                font-size: 13px;
                font-weight: 700;
                padding: 0 12px;
            }
            QPushButton#ActionButton:hover, QPushButton#SmallAction:hover {
                background: rgba(47, 165, 255, 1.0);
            }
            QLabel#BlockTitle {
                font-size: 18px;
                font-weight: 700;
                color: #ffffff;
            }
            QLabel#MetricCaption, QLabel#InsetCaption {
                color: #8ea2bf;
                font-size: 11px;
                font-weight: 700;
                letter-spacing: 0.6px;
                text-transform: uppercase;
            }
            QLabel#MetricValue, QLabel#InsetValue {
                color: #ffffff;
                font-size: 15px;
                font-weight: 700;
            }
            QLabel#RouteSummary {
                color: #dbe7f7;
                font-size: 14px;
                line-height: 1.4;
            }
            QLabel#VideoPreview {
                background: rgba(3, 8, 14, 0.82);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 16px;
                color: #9ab4d0;
                font-weight: 700;
            }
            QPlainTextEdit#DataArea {
                background: rgba(3, 7, 12, 0.68);
                border: 1px solid rgba(255, 255, 255, 0.07);
                border-radius: 14px;
                color: #dce7f5;
                padding: 10px;
                selection-background-color: rgba(24, 145, 242, 0.35);
            }
            QScrollArea#ConfigScroll {
                background: transparent;
                border: none;
            }
            QLineEdit, QComboBox, QDoubleSpinBox {
                background: rgba(255, 255, 255, 0.04);
                color: white;
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 10px;
                min-height: 34px;
                padding: 0 10px;
            }
            QCheckBox {
                color: #e6eef8;
                font-size: 13px;
                font-weight: 600;
            }
            QScrollBar:vertical {
                background: transparent;
                width: 8px;
                margin: 4px;
            }
            QScrollBar::handle:vertical {
                background: rgba(255, 255, 255, 0.16);
                border-radius: 4px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
            """
        )

    def _bind_runtime(self) -> None:
        self.runtime.telemetry_updated.connect(self._update_telemetry)
        self.runtime.other_drones_updated.connect(self._update_other_drones)
        self.runtime.zones_updated.connect(self._update_zones)
        self.runtime.route_updated.connect(self._update_route)
        self.runtime.mission_plan_changed.connect(self._update_mission_plan)
        self.runtime.mission_state_changed.connect(self._update_mission_state)
        self.runtime.control_authority_changed.connect(self._update_control_authority)
        self.runtime.competition_status_changed.connect(self._update_competition_status)
        self.runtime.log_message.connect(self._append_log)
        self.runtime.api_status_changed.connect(self._update_api_status)
        self.runtime.connection_changed.connect(self._update_connection)
        self.map_view.map_clicked.connect(self._handle_map_click)

    def _bind_video(self) -> None:
        self.video_worker.frame_ready.connect(self._update_video_frame)
        self.video_worker.status_message.connect(self._append_log)
        self.video_worker.detections_updated.connect(lambda count: self.detections_label.setText(f"Detections: {count}"))

    def _switch_panel(self, index: int) -> None:
        self.panel_stack.setCurrentIndex(index)
        self.tab_actions_btn.setChecked(index == 0)
        self.tab_routes_btn.setChecked(index == 1)

    def _update_telemetry(self, telemetry) -> None:
        self.telemetry_labels["lat"].setText(f"{telemetry.position.lat:.6f}")
        self.telemetry_labels["lon"].setText(f"{telemetry.position.lon:.6f}")
        self.telemetry_labels["alt"].setText(f"{telemetry.position.altitude_m:.1f} m")
        self.telemetry_labels["ground_speed"].setText(f"{telemetry.ground_speed_mps:.1f} m/s")
        self.telemetry_labels["air_speed"].setText(f"{telemetry.air_speed_mps:.1f} m/s")
        self.telemetry_labels["heading"].setText(f"{telemetry.heading_deg:.1f} deg")
        self.telemetry_labels["battery"].setText(f"{telemetry.battery_percent}% / {telemetry.battery_voltage:.2f} V")
        self.telemetry_labels["mode"].setText(telemetry.mode)
        self.mode_chip.setText(telemetry.mode)

        home = GeoPoint(self.settings.map.center_lat, self.settings.map.center_lon)
        home_distance_km = haversine_distance_m(home, telemetry.position) / 1000.0
        route_length_km = self._route_length_km()
        self.metric_labels["home_distance"].setText(f"{home_distance_km:.2f} km")
        self.metric_labels["route_length"].setText(f"{route_length_km:.2f} km")
        self.metric_labels["waypoints"].setText(str(max(0, len(self.runtime.route) - 1)))

        self.ring_gauge.set_value(
            progress=telemetry.battery_percent / 100.0,
            primary_text=f"{telemetry.battery_percent}%",
            headline=f"{telemetry.ground_speed_mps:.1f} m/s",
            subline=f"{home_distance_km:.2f} km",
            accent="#ffb020" if telemetry.battery_percent > 30 else "#ff5f57",
        )

        if telemetry.armed and self.flight_started_at is None:
            self.flight_started_at = datetime.now(timezone.utc)
        self._update_flight_timer()
        self.map_view.set_vehicle(telemetry.position, telemetry.heading_deg, telemetry.mode)

    def _update_other_drones(self, drones) -> None:
        lines = []
        current_team = self.ai_target_combo.currentData()
        self.ai_target_combo.blockSignals(True)
        self.ai_target_combo.clear()
        self.ai_target_combo.addItem("Nearest", None)
        for drone in drones:
            lines.append(
                f"Team {drone.team_id}: {drone.position.lat:.5f}, {drone.position.lon:.5f} | "
                f"{drone.position.altitude_m:.1f} m | {drone.latency_ms} ms"
            )
            self.ai_target_combo.addItem(f"Team {drone.team_id}", drone.team_id)
        if current_team is not None:
            index = self.ai_target_combo.findData(current_team)
            if index >= 0:
                self.ai_target_combo.setCurrentIndex(index)
        self.ai_target_combo.blockSignals(False)
        self.other_drones_label.setPlainText("\n".join(lines))
        self.map_view.set_other_drones(drones)

    def _update_route(self, route) -> None:
        self.map_view.set_route(route)
        route_length_km = self._route_length_km()
        self.metric_labels["route_length"].setText(f"{route_length_km:.2f} km")
        self.metric_labels["waypoints"].setText(str(max(0, len(route) - 1)))
        if route:
            self.route_summary.setText(
                f"Route ready with {max(0, len(route) - 1)} legs.\n"
                f"Estimated path length: {route_length_km:.2f} km."
            )
        else:
            self.route_summary.setText("No mission route available")

    def _update_zones(self, zones) -> None:
        self.map_view.set_zones(zones)
        lines = []
        boundary = None
        for zone in zones:
            if zone.zone_type == ZoneType.COMPETITION:
                boundary = zone
            if zone.is_circle and zone.center is not None and zone.radius_m is not None:
                lines.append(
                    f"{zone.zone_type.value}: {zone.label or zone.identifier} | "
                    f"{zone.center.lat:.5f}, {zone.center.lon:.5f} | R={zone.radius_m:.1f} m"
                )
            else:
                lines.append(f"{zone.zone_type.value}: {zone.label or zone.identifier} | {len(zone.points)} vertices")
        self.zone_manifest.setPlainText("\n".join(lines))
        if boundary is None:
            self.boundary_manifest.setText("Boundary not configured")
        else:
            self.boundary_manifest.setText(f"Boundary ready: {len(boundary.points)} vertices")

    def _update_mission_plan(self, plan) -> None:
        lines = [
            f"Mission: {plan.name}",
            f"Valid: {'YES' if plan.valid else 'NO'}",
            f"Upload: {'YES' if plan.uploaded else 'NO'}",
            f"Fence: {'YES' if plan.fence_uploaded else 'NO'}",
            f"Status: {plan.validation_message}",
            "",
        ]
        for index, item in enumerate(plan.items, start=1):
            lines.append(
                f"{index:02d}. {item.item_type.value} | "
                f"{item.point.lat:.5f}, {item.point.lon:.5f}, {item.point.altitude_m:.1f} m"
            )
        self.mission_manifest.setPlainText("\n".join(lines))

    def _update_mission_state(self, state: str) -> None:
        self.state_chip.setText(state)
        if state in {"ARMED", "MISSION"} and self.flight_started_at is None:
            self.flight_started_at = datetime.now(timezone.utc)
        if state in {"INIT", "CONNECTED"}:
            self.flight_started_at = None
            self.timer_chip.setText("00:00:00")

    def _update_control_authority(self, authority: str) -> None:
        self.authority_chip.setText(authority.upper())

    def _update_competition_status(self, status) -> None:
        autonomy_pct = status.autonomy_ratio * 100.0
        lines = [
            f"Manual switches: {status.manual_mode_switches}/{status.manual_mode_limit}",
            f"Autonomy ratio: {autonomy_pct:.1f}%",
            f"HSS violation time: {status.defense_violation_seconds} s",
            f"Out-of-bounds time: {status.out_of_bounds_seconds} s",
            f"Flight timer: {status.flight_seconds} s",
        ]
        self.competition_status_output.setPlainText("\n".join(lines))

    def _update_api_status(self, status: str) -> None:
        self.metric_labels["api"].setText(status)
        self._set_message(status)

    def _update_connection(self, connected: bool) -> None:
        self.connection_chip.setText("LINK ON" if connected else "LINK OFF")
        self.connection_chip.setObjectName("ChipGreen" if connected else "ChipBlue")
        self.connection_chip.style().unpolish(self.connection_chip)
        self.connection_chip.style().polish(self.connection_chip)

    def _update_video_frame(self, image: QImage) -> None:
        pixmap = QPixmap.fromImage(image).scaled(
            self.video_label.size(),
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.video_label.setPixmap(pixmap)

    def _append_log(self, message: str) -> None:
        self.log_output.appendPlainText(message)
        self._set_message(message)

    def _update_flight_timer(self) -> None:
        if self.flight_started_at is None:
            self.timer_chip.setText("00:00:00")
            return
        elapsed = int((datetime.now(timezone.utc) - self.flight_started_at).total_seconds())
        hours = elapsed // 3600
        minutes = (elapsed % 3600) // 60
        seconds = elapsed % 60
        self.timer_chip.setText(f"{hours:02d}:{minutes:02d}:{seconds:02d}")

    def _set_message(self, message: str) -> None:
        self._last_message = message.strip() or "System ready"
        trimmed = self._last_message
        if len(trimmed) > 72:
            trimmed = trimmed[:69] + "..."
        self.message_chip.setText(trimmed)

    def _route_length_km(self) -> float:
        route = self.runtime.route
        if len(route) < 2:
            return 0.0
        total = 0.0
        for index in range(len(route) - 1):
            total += haversine_distance_m(route[index], route[index + 1])
        return total / 1000.0

    def _arm(self) -> None:
        try:
            self.runtime.arm()
        except Exception as exc:
            QMessageBox.critical(self, "ARM failed", str(exc))

    def _start_mission(self) -> None:
        try:
            if not self.runtime.upload_mission():
                return
            self.runtime.start_mission()
        except Exception as exc:
            QMessageBox.critical(self, "Mission failed", str(exc))

    def _upload_mission(self) -> None:
        if not self.runtime.upload_mission():
            QMessageBox.warning(self, "Mission invalid", self.runtime.mission_plan.validation_message)

    def _toggle_ai(self, enabled: bool) -> None:
        self.ai_processor.set_enabled(enabled)
        self.runtime.set_ai_enabled(enabled)

    def _take_screenshot(self) -> None:
        path = self.video_worker.take_screenshot()
        if path:
            self._append_log(f"Screenshot saved: {path}")
        else:
            self._append_log("Screenshot unavailable")

    def _update_follow_distance(self, value: float) -> None:
        self.settings.ai.follow_distance_m = value
        self.runtime.ai_follow.follow_distance_m = value

    def _engage_ai_follow(self) -> None:
        team_id = self.ai_target_combo.currentData()
        self.runtime.engage_ai_follow(team_id)

    def _add_takeoff_item(self) -> None:
        self.runtime.add_takeoff_item(self.takeoff_altitude_spin.value())

    def _begin_add_waypoint(self) -> None:
        self._set_editor_mode("mission_waypoint", "Click map to append waypoints")

    def _begin_add_loiter(self) -> None:
        self._set_editor_mode("mission_loiter", "Click map to insert loiter point")

    def _begin_add_land(self) -> None:
        self._set_editor_mode("mission_land", "Click map for VTOL landing point")

    def _begin_zone_polygon(self) -> None:
        self._set_editor_mode("zone_polygon", "Click map to draw polygon zone")

    def _begin_zone_circle(self) -> None:
        self._set_editor_mode("zone_circle", "Click map to place circle zone center")

    def _begin_competition_boundary(self) -> None:
        self._set_editor_mode("competition_boundary", "Click map to draw competition boundary")

    def _set_editor_mode(self, mode: str, hint: str) -> None:
        self.editor_mode = mode
        self.draft_points = []
        self.editor_hint.setText(f"Editor: {hint}")
        self.map_view.set_editor_mode(mode, hint)
        self.map_view.set_draft_overlay([])

    def _cancel_editor(self) -> None:
        self.editor_mode = "none"
        self.draft_points = []
        self.editor_hint.setText("Editor: idle")
        self.map_view.set_editor_mode("none", "")
        self.map_view.set_draft_overlay([])

    def _finish_zone(self) -> None:
        zone_type = self.zone_type_combo.currentData()
        if self.editor_mode == "zone_polygon":
            if len(self.draft_points) < 3:
                QMessageBox.warning(self, "Zone", "Polygon zone needs at least 3 points.")
                return
            zone = Zone(
                identifier=f"user-zone-{self.zone_sequence}",
                zone_type=zone_type,
                points=list(self.draft_points),
                label=f"{zone_type.value}-{self.zone_sequence}",
            )
            self.zone_sequence += 1
            self.runtime.add_zone(zone)
            self._cancel_editor()
            return
        if self.editor_mode == "zone_circle":
            if len(self.draft_points) != 1:
                QMessageBox.warning(self, "Zone", "Click the map to place the circle center first.")
                return
            center = self.draft_points[0]
            zone = Zone(
                identifier=f"user-zone-{self.zone_sequence}",
                zone_type=zone_type,
                center=center,
                radius_m=self.zone_radius_spin.value(),
                label=f"{zone_type.value}-{self.zone_sequence}",
            )
            self.zone_sequence += 1
            self.runtime.add_zone(zone)
            self._cancel_editor()

    def _finish_competition_boundary(self) -> None:
        if self.editor_mode != "competition_boundary":
            QMessageBox.warning(self, "Boundary", "Activate border drawing first.")
            return
        if len(self.draft_points) < 3:
            QMessageBox.warning(self, "Boundary", "Competition boundary needs at least 3 points.")
            return
        self.runtime.set_competition_boundary(self.draft_points)
        self._cancel_editor()

    def _handle_map_click(self, lat: float, lon: float) -> None:
        point = GeoPoint(lat=lat, lon=lon, altitude_m=self.default_altitude_spin.value())
        if self.editor_mode == "mission_waypoint":
            self.runtime.add_waypoint(point, self.default_altitude_spin.value())
            return
        if self.editor_mode == "mission_loiter":
            self.runtime.add_loiter(point, self.default_altitude_spin.value(), self.loiter_spin.value())
            self._cancel_editor()
            return
        if self.editor_mode == "mission_land":
            self.runtime.add_vtol_land(point)
            self._cancel_editor()
            return
        if self.editor_mode == "competition_boundary":
            self.draft_points.append(point)
            self.map_view.set_draft_overlay(self.draft_points, ZoneType.COMPETITION.value)
            return
        if self.editor_mode == "zone_polygon":
            self.draft_points.append(point)
            self.map_view.set_draft_overlay(self.draft_points, self.zone_type_combo.currentData().value)
            return
        if self.editor_mode == "zone_circle":
            self.draft_points = [point]
            self.map_view.set_draft_overlay(
                self.draft_points,
                self.zone_type_combo.currentData().value,
                self.zone_radius_spin.value(),
            )

    def _apply_settings(self) -> None:
        self.settings.connection.transport = self.transport_combo.currentText()
        self.settings.connection.serial_port = self.serial_port_edit.text().strip()
        self.settings.connection.baud_rate = int(self.baud_rate_edit.text().strip())
        self.settings.connection.udp_endpoint = self.udp_edit.text().strip()
        self.settings.map.tile_url = self.tile_url_edit.text().strip()
        self.settings.teknofest_api.base_url = self.api_url_edit.text().strip()
        self.settings.teknofest_api.username = self.api_user_edit.text().strip()
        self.settings.teknofest_api.password = self.api_pass_edit.text()
        self.settings.video.source = self.video_source_edit.text().strip()
        self.settings.aircraft.cruise_altitude_m = self.default_altitude_spin.value()
        self.settings.aircraft.mission_takeoff_alt_m = self.takeoff_altitude_spin.value()
        self.settings.ai.follow_distance_m = self.follow_distance_spin.value()
        self.video_worker.set_source(self.settings.video.source)
        self.runtime.update_settings(self.settings)
        self._save_settings()
        self._append_log("Settings applied; restart recommended for transport changes")

    def _save_settings(self) -> None:
        self.settings.save(self.settings_path)
        self._append_log(f"Settings saved: {self.settings_path}")
