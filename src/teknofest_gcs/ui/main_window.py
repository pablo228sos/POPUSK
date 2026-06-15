from __future__ import annotations
import os
import time
from pathlib import Path
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QFrame, 
    QPushButton, QLabel, QListWidget, QListWidgetItem, 
    QPlainTextEdit, QSpinBox, QDoubleSpinBox, QGridLayout, QDialog,
    QProgressBar, QScrollArea, QSizePolicy
)
from PyQt6.QtCore import Qt, QTimer, pyqtSlot, pyqtSignal

from teknofest_gcs.core.models import FleetManager, GeoPoint
from teknofest_gcs.core.sim import SwarmSimulationEngine
from teknofest_gcs.ui.map_view import MapView
from teknofest_gcs.ui.calibration import CalibrationWizard

class CalibrationDialog(QDialog):
    def __init__(self, drone_id: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Калибровка БПЛА {drone_id}")
        self.resize(550, 480)
        self.setModal(True)
        self.setStyleSheet("background-color: #0f172a; border-radius: 12px; border: 1px solid rgba(56, 189, 248, 0.3);")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        
        wizard = CalibrationWizard()
        layout.addWidget(wizard)


class DroneListItemWidget(QWidget):
    calibrate_clicked = pyqtSignal(int)

    def __init__(self, drone_id: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.drone_id = drone_id
        self.init_ui()

    def init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # Card container
        self.card = QFrame()
        self.card.setObjectName("card")
        self.card.setProperty("class", "drone_card")
        self.card.setStyleSheet("background-color: rgba(30, 41, 59, 0.5); border: 1px solid rgba(255, 255, 255, 0.06); border-radius: 8px;")
        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(8, 8, 8, 8)
        card_layout.setSpacing(4)

        # Top row: ID and mode
        top_row = QHBoxLayout()
        self.lbl_id = QLabel(f"🛸 БПЛА {self.drone_id}")
        self.lbl_id.setStyleSheet("font-weight: bold; font-size: 12px; color: #38bdf8;")
        self.lbl_mode = QLabel("STANDBY")
        self.lbl_mode.setStyleSheet("font-size: 10px; color: #94a3b8; font-weight: 700; padding: 1px 4px; background-color: rgba(255,255,255,0.04); border-radius: 3px;")
        
        top_row.addWidget(self.lbl_id)
        top_row.addStretch()
        top_row.addWidget(self.lbl_mode)
        card_layout.addLayout(top_row)

        # Telemetry metrics
        grid = QGridLayout()
        grid.setSpacing(2)
        
        self.lbl_alt = QLabel("Alt: 0.0 м")
        self.lbl_alt.setStyleSheet("font-size: 10px; color: #cbd5e1;")
        self.lbl_speed = QLabel("Spd: 0.0 м/с")
        self.lbl_speed.setStyleSheet("font-size: 10px; color: #cbd5e1;")
        
        grid.addWidget(self.lbl_alt, 0, 0)
        grid.addWidget(self.lbl_speed, 0, 1)
        card_layout.addLayout(grid)

        # Battery Bar
        bat_row = QHBoxLayout()
        self.bat_bar = QProgressBar()
        self.bat_bar.setRange(0, 100)
        self.bat_bar.setValue(100)
        self.bat_bar.setTextVisible(True)
        self.bat_bar.setStyleSheet("QProgressBar { background-color: #1e293b; border-radius: 3px; height: 10px; text-align: center; color: white; font-size: 7px; font-weight: bold; } QProgressBar::chunk { background-color: #10b981; }")
        
        self.btn_calib = QPushButton("Калибровать 🔧")
        self.btn_calib.setStyleSheet("font-size: 9px; padding: 2px 4px; background-color: rgba(56, 189, 248, 0.15); color: #38bdf8; border: 1px solid rgba(56, 189, 248, 0.3); border-radius: 3px;")
        self.btn_calib.clicked.connect(lambda: self.calibrate_clicked.emit(self.drone_id))

        bat_row.addWidget(self.bat_bar)
        bat_row.addWidget(self.btn_calib)
        card_layout.addLayout(bat_row)

        layout.addWidget(self.card)

    def update_state(self, alt: float, speed: float, battery: int, mode: str, armed: bool, selected: bool) -> None:
        self.lbl_mode.setText(mode)
        self.lbl_alt.setText(f"Alt: {alt:.1f} м")
        self.lbl_speed.setText(f"Spd: {speed:.1f} м/с")
        self.bat_bar.setValue(battery)
        
        if battery < 30:
            self.bat_bar.setStyleSheet("QProgressBar { background-color: #1e293b; border-radius: 3px; height: 10px; text-align: center; color: white; font-size: 7px; font-weight: bold; } QProgressBar::chunk { background-color: #ef4444; }")
        else:
            self.bat_bar.setStyleSheet("QProgressBar { background-color: #1e293b; border-radius: 3px; height: 10px; text-align: center; color: white; font-size: 7px; font-weight: bold; } QProgressBar::chunk { background-color: #10b981; }")

        if selected:
            self.card.setStyleSheet("background-color: rgba(16, 185, 129, 0.08); border-color: rgba(16, 185, 129, 0.5); border-radius: 8px;")
        else:
            self.card.setStyleSheet("background-color: rgba(30, 41, 59, 0.5); border-color: rgba(255, 255, 255, 0.06); border-radius: 8px;")


class MainWindow(QMainWindow):
    def __init__(self, settings: any = None, settings_path: any = None) -> None:
        super().__init__()
        self.setWindowTitle("AetherFlow Ground Control Station - Swarm Dashboard")
        self.resize(1366, 768)
        
        # Core Models & Simulation
        self.fleet_manager = FleetManager()
        self.sim_engine = SwarmSimulationEngine(self.fleet_manager)
        self.active_vehicle_id: int | None = None
        self.drone_widgets: dict[int, DroneListItemWidget] = {}
        
        # Load Global QSS
        self.load_stylesheet()
        
        # Setup Layout
        self.init_ui()
        
        # Periodic Telemetry Update Timer (5 Hz)
        self.telemetry_timer = QTimer()
        self.telemetry_timer.timeout.connect(self.update_telemetry_ui)
        self.telemetry_timer.start(200)

        self.log_event("Премиальная НСУ AetherFlow запущена.")
        self.log_event("Интерфейс инициализирован в режиме параллельных панелей.")

    def load_stylesheet(self) -> None:
        qss_path = Path(__file__).resolve().parent / "assets" / "styles.qss"
        if qss_path.exists():
            with open(qss_path, "r", encoding="utf-8") as f:
                self.setStyleSheet(f.read())
        else:
            print(f"[UI] Warning: Stylesheet not found at {qss_path}")

    def init_ui(self) -> None:
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        # Map View (Expanding center) - instantiated first to prevent AttributeErrors in panels
        self.map_view = MapView()
        self.map_view.map_clicked.connect(self.on_map_clicked)
        self.map_view.vehicle_clicked.connect(self.on_vehicle_marker_clicked)
        self.map_view.setStyleSheet("border-radius: 12px; border: 1px solid #334155;")

        # 1. Top Bar QFrame
        top_bar = self.create_top_bar()
        main_layout.addWidget(top_bar)

        # 2. Middle Row (Left Sidebar | Full Map | Right Sidebar)
        middle_layout = QHBoxLayout()
        middle_layout.setSpacing(10)

        # Left Panel (Fixed width)
        left_panel = self.create_left_panel()
        middle_layout.addWidget(left_panel)

        # Map View added to middle row layout
        middle_layout.addWidget(self.map_view, stretch=3)

        # Right Panel (Fixed width)
        right_panel = self.create_right_panel()
        middle_layout.addWidget(right_panel)

        main_layout.addLayout(middle_layout, stretch=1)

        # 3. Bottom Panel (Terminal Event Logs)
        bottom_panel = self.create_bottom_panel()
        main_layout.addWidget(bottom_panel)

    def create_top_bar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("top_bar")
        bar.setProperty("class", "overlay_panel")
        bar.setStyleSheet("background-color: #1e293b; border: 1px solid #334155; border-radius: 8px;")
        
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(15, 8, 15, 8)
        layout.setSpacing(15)

        # Logo text
        lbl_logo = QLabel("AETHERFLOW GCS")
        lbl_logo.setStyleSheet("font-size: 15px; font-weight: bold; color: #38bdf8; letter-spacing: 2px;")
        layout.addWidget(lbl_logo)

        lbl_divider = QLabel("|")
        lbl_divider.setStyleSheet("color: #334155; font-size: 14px;")
        layout.addWidget(lbl_divider)

        # Tactical global command buttons
        btn_arm = QPushButton("ARM РОЙ")
        btn_arm.setProperty("class", "success_btn")
        btn_arm.clicked.connect(lambda: self.send_swarm_command("arm"))
        
        btn_takeoff = QPushButton("🚀 ВЗЛЕТ")
        btn_takeoff.setProperty("class", "primary_btn")
        btn_takeoff.clicked.connect(lambda: self.send_swarm_command("takeoff"))

        btn_rtl = QPushButton("🏡 ВОЗВРАТ (RTL)")
        btn_rtl.setProperty("class", "danger_btn")
        btn_rtl.clicked.connect(lambda: self.send_swarm_command("rtl"))

        btn_land = QPushButton("🛬 ПОСАДКА")
        btn_land.setProperty("class", "secondary_btn")
        btn_land.clicked.connect(lambda: self.send_swarm_command("land"))

        layout.addWidget(btn_arm)
        layout.addWidget(btn_takeoff)
        layout.addWidget(btn_rtl)
        layout.addWidget(btn_land)
        
        layout.addStretch()

        # Map controls
        btn_zoom_in = QPushButton("➕")
        btn_zoom_in.setProperty("class", "icon_btn")
        btn_zoom_in.clicked.connect(self.map_view.zoom_in)
        
        btn_zoom_out = QPushButton("➖")
        btn_zoom_out.setProperty("class", "icon_btn")
        btn_zoom_out.clicked.connect(self.map_view.zoom_out)

        btn_center = QPushButton("🎯 ЦЕНТР")
        btn_center.setProperty("class", "icon_btn")
        btn_center.clicked.connect(self.map_view.center_on_selected)

        layout.addWidget(btn_zoom_in)
        layout.addWidget(btn_zoom_out)
        layout.addWidget(btn_center)

        return bar

    def create_left_panel(self) -> QWidget:
        panel = QFrame()
        panel.setProperty("class", "overlay_panel")
        panel.setStyleSheet("background-color: #111827; border: 1px solid #1e293b; border-radius: 8px;")
        panel.setFixedWidth(280)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # Header Title
        title_bar = QFrame()
        title_bar.setStyleSheet("border-bottom: 1px solid #1e293b; padding: 10px; background-color: rgba(30,41,59,0.2);")
        title_layout = QHBoxLayout(title_bar)
        title_layout.setContentsMargins(10, 5, 10, 5)
        lbl_title = QLabel("Флот БПЛА & Сеть")
        lbl_title.setStyleSheet("font-size: 13px; font-weight: bold; color: #f8fafc;")
        title_layout.addWidget(lbl_title)
        layout.addWidget(title_bar)

        # Connection setup group
        conn_box = QFrame()
        conn_layout = QGridLayout(conn_box)
        conn_layout.setContentsMargins(12, 5, 12, 5)
        conn_layout.setSpacing(8)

        conn_layout.addWidget(QLabel("Кол-во дронов:"), 0, 0)
        self.spn_count = QSpinBox()
        self.spn_count.setRange(1, 30)
        self.spn_count.setValue(5)
        conn_layout.addWidget(self.spn_count, 0, 1)

        self.btn_sim_toggle = QPushButton("Запуск роя в Sim")
        self.btn_sim_toggle.setProperty("class", "primary_btn")
        self.btn_sim_toggle.clicked.connect(self.toggle_simulation)
        conn_layout.addWidget(self.btn_sim_toggle, 1, 0, 1, 2)

        layout.addWidget(conn_box)

        # Drone Scroll List Area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background: transparent; border: none;")
        
        self.scroll_content = QWidget()
        self.scroll_content.setStyleSheet("background: transparent;")
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        self.scroll_layout.setContentsMargins(8, 0, 8, 0)
        self.scroll_layout.setSpacing(2)
        self.scroll_layout.addStretch()
        
        scroll.setWidget(self.scroll_content)
        layout.addWidget(scroll)

        return panel

    def create_right_panel(self) -> QWidget:
        panel = QFrame()
        panel.setProperty("class", "overlay_panel")
        panel.setStyleSheet("background-color: #111827; border: 1px solid #1e293b; border-radius: 8px;")
        panel.setFixedWidth(290)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # Header Title
        title_bar = QFrame()
        title_bar.setStyleSheet("border-bottom: 1px solid #1e293b; padding: 10px; background-color: rgba(30,41,59,0.2);")
        title_layout = QHBoxLayout(title_bar)
        title_layout.setContentsMargins(10, 5, 10, 5)
        lbl_title = QLabel("Инфо-Панель HUD")
        lbl_title.setStyleSheet("font-size: 13px; font-weight: bold; color: #f8fafc;")
        title_layout.addWidget(lbl_title)
        layout.addWidget(title_bar)

        # Selected drone detailed telemetry
        self.telemetry_card = QFrame()
        self.telemetry_card.setStyleSheet("padding: 8px; background-color: rgba(30,41,59,0.3); border-radius: 6px; margin: 0 10px;")
        card_layout = QVBoxLayout(self.telemetry_card)
        card_layout.setContentsMargins(8, 8, 8, 8)
        card_layout.setSpacing(6)

        self.lbl_sel_name = QLabel("БПЛА НЕ ВЫБРАН")
        self.lbl_sel_name.setStyleSheet("font-size: 13px; font-weight: bold; color: #38bdf8;")
        card_layout.addWidget(self.lbl_sel_name)

        self.lbl_sel_telemetry = QLabel(
            "Режим: OFFLINE\n"
            "Высота: 0.0 м\n"
            "Скорость: 0.0 м/с\n"
            "Батарея: 0%\n"
            "Компас: 0.0°\n"
            "Крен/Тангаж: 0.0° / 0.0°"
        )
        self.lbl_sel_telemetry.setStyleSheet("font-family: 'Consolas', monospace; font-size: 11px; color: #cbd5e1; line-height: 1.4;")
        card_layout.addWidget(self.lbl_sel_telemetry)

        layout.addWidget(self.telemetry_card)

        # Video streams simulated section
        video_title = QLabel("📡 Видеокамеры роя")
        video_title.setStyleSheet("font-weight: bold; color: #94a3b8; font-size: 11px; margin-left: 12px;")
        layout.addWidget(video_title)

        # Mock Video feeds layout
        self.video_grid = QFrame()
        self.video_grid.setStyleSheet("margin: 0 10px;")
        grid_layout = QGridLayout(self.video_grid)
        grid_layout.setContentsMargins(0, 0, 0, 0)
        grid_layout.setSpacing(8)

        # 4 mock video cards
        self.video_cards = []
        for i in range(4):
            card = QFrame()
            card.setStyleSheet("background-color: #020617; border: 1px solid #334155; border-radius: 4px; min-height: 70px;")
            c_lay = QVBoxLayout(card)
            c_lay.setContentsMargins(4, 4, 4, 4)
            
            lbl_cam = QLabel(f"CAM {i+1} - NO FEED")
            lbl_cam.setStyleSheet("color: #475569; font-size: 9px; font-weight: bold;")
            lbl_cam.setAlignment(Qt.AlignmentFlag.AlignCenter)
            c_lay.addWidget(lbl_cam)
            
            grid_layout.addWidget(card, i // 2, i % 2)
            self.video_cards.append(lbl_cam)

        layout.addWidget(self.video_grid)
        layout.addStretch()

        return panel

    def create_bottom_panel(self) -> QWidget:
        panel = QFrame()
        panel.setProperty("class", "overlay_panel")
        panel.setStyleSheet("background-color: #111827; border: 1px solid #1e293b; border-radius: 8px;")
        panel.setFixedHeight(120)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)

        # Header Title
        title_bar = QFrame()
        title_bar.setStyleSheet("border-bottom: 1px solid #1e293b; padding: 6px 12px; background-color: rgba(30,41,59,0.2);")
        title_layout = QHBoxLayout(title_bar)
        title_layout.setContentsMargins(10, 2, 10, 2)
        lbl_title = QLabel("Терминал Событий роя БПЛА")
        lbl_title.setStyleSheet("font-size: 11px; font-weight: bold; color: #f8fafc;")
        title_layout.addWidget(lbl_title)
        
        btn_clr = QPushButton("Очистить")
        btn_clr.setStyleSheet("font-size: 9px; padding: 1px 4px; background-color: rgba(255,255,255,0.05); color: #94a3b8; border-radius: 3px;")
        btn_clr.clicked.connect(lambda: self.txt_logs.clear())
        title_layout.addStretch()
        title_layout.addWidget(btn_clr)
        
        layout.addWidget(title_bar)

        # Terminal Console logs
        self.txt_logs = QPlainTextEdit()
        self.txt_logs.setReadOnly(True)
        self.txt_logs.setStyleSheet("QPlainTextEdit { background-color: #020617; border: none; color: #38bdf8; font-family: 'Consolas', monospace; font-size: 11px; }")
        layout.addWidget(self.txt_logs)

        return panel

    # --- Actions and Events ---
    def log_event(self, text: str) -> None:
        timestamp = time.strftime("[%H:%M:%S]")
        self.txt_logs.appendPlainText(f"{timestamp} {text}")

    def toggle_simulation(self) -> None:
        if not self.sim_engine.running:
            # Configure and launch
            count = self.spn_count.value()
            self.sim_engine.configure_swarm(count)
            self.sim_engine.start()
            
            # Change buttons states
            self.btn_sim_toggle.setText("Остановить рой")
            self.btn_sim_toggle.setProperty("class", "danger_btn")
            self.btn_sim_toggle.style().unpolish(self.btn_sim_toggle)
            self.btn_sim_toggle.style().polish(self.btn_sim_toggle)
            
            # Generate UI drone list widgets
            self.rebuild_drone_widgets(count)
            self.log_event(f"Запущена симуляция роя БПЛА. Активно: {count} дронов.")
        else:
            self.sim_engine.stop()
            self.btn_sim_toggle.setText("Запуск роя в Sim")
            self.btn_sim_toggle.setProperty("class", "primary_btn")
            self.btn_sim_toggle.style().unpolish(self.btn_sim_toggle)
            self.btn_sim_toggle.style().polish(self.btn_sim_toggle)
            
            # Clear UI list widgets
            self.clear_drone_widgets()
            self.log_event("Симуляция роя БПЛА остановлена.")

    def rebuild_drone_widgets(self, count: int) -> None:
        self.clear_drone_widgets()
        
        # Remove spacer at bottom of layout
        self.scroll_layout.takeAt(self.scroll_layout.count() - 1)
        
        for i in range(count):
            drone_id = 100 + (i + 1)
            item_widget = DroneListItemWidget(drone_id)
            item_widget.calibrate_clicked.connect(self.trigger_drone_calibration)
            
            self.scroll_layout.addWidget(item_widget)
            self.drone_widgets[drone_id] = item_widget
            
        # Re-append spacer to pack widgets at top
        self.scroll_layout.addStretch()

    def clear_drone_widgets(self) -> None:
        for w in list(self.drone_widgets.values()):
            w.deleteLater()
        self.drone_widgets.clear()
        self.active_vehicle_id = None

    def trigger_drone_calibration(self, drone_id: int) -> None:
        self.log_event(f"Команда: Открытие мастера калибровки для БПЛА {drone_id}")
        dialog = CalibrationDialog(drone_id, self)
        dialog.exec()

    def update_telemetry_ui(self) -> None:
        vehicles = self.fleet_manager.online_vehicles()
        self.map_view.update_vehicles(vehicles)

        # Update drone cards telemetry
        for v in vehicles:
            widget = self.drone_widgets.get(v.id)
            if widget:
                speed = (v.vx**2 + v.vy**2)**0.5
                selected = v.id == self.active_vehicle_id
                widget.update_state(
                    alt=v.alt,
                    speed=speed,
                    battery=v.battery_percent,
                    mode=v.flight_mode,
                    armed=v.armed,
                    selected=selected
                )

        # Update detailed right HUD panel
        if self.active_vehicle_id is not None:
            v = self.fleet_manager.get_vehicle(self.active_vehicle_id)
            if v and v.is_online:
                self.lbl_sel_name.setText(f"🛸 БПЛА {v.id} HUD")
                speed = (v.vx**2 + v.vy**2)**0.5
                self.lbl_sel_telemetry.setText(
                    f"Режим: {v.flight_mode}\n"
                    f"Широта: {v.lat:.6f}°\n"
                    f"Долгота: {v.lon:.6f}°\n"
                    f"Высота: {v.alt:.1f} м\n"
                    f"Скорость: {speed:.1f} м/с\n"
                    f"Батарея: {v.battery_percent}% ({v.battery_v:.2f} В)\n"
                    f"Компас: {v.heading:.1f}°\n"
                    f"Крен/Тангаж: {v.roll:.1f}° / {v.pitch:.1f}°"
                )
                
                # Update visual camera feeds titles
                for idx, feed in enumerate(self.video_cards):
                    if idx == 0:
                        feed.setText(f"CAM БПЛА {v.id}\nFEED ACTIVE\nROLL: {v.roll:.1f}°")
                        feed.setStyleSheet("color: #10b981; font-size: 10px; font-weight: bold;")
                    else:
                        feed.setText(f"CAM {idx+1} - STDBY")
                        feed.setStyleSheet("color: #475569; font-size: 10px; font-weight: bold;")
            else:
                self.active_vehicle_id = None
                self.lbl_sel_name.setText("БПЛА НЕ ВЫБРАН")
                self.lbl_sel_telemetry.setText("Режим: OFFLINE\nВысота: 0.0 м...")
        else:
            self.lbl_sel_name.setText("БПЛА НЕ ВЫБРАН")
            self.lbl_sel_telemetry.setText("Режим: OFFLINE\nВысота: 0.0 м...")

    def on_vehicle_marker_clicked(self, vehicle_id: int) -> None:
        self.select_active_vehicle(vehicle_id)

    def on_drone_item_clicked(self, item) -> None:
        pass # Using custom widgets directly

    # Custom click selection directly from Left sidebar click overrides
    def mousePressEvent(self, event) -> None:
        child = self.childAt(event.position().toPoint())
        if child:
            parent_widget = child.parent()
            while parent_widget:
                if isinstance(parent_widget, DroneListItemWidget):
                    self.select_active_vehicle(parent_widget.drone_id)
                    break
                parent_widget = parent_widget.parent()
        super().mousePressEvent(event)

    def select_active_vehicle(self, vehicle_id: int) -> None:
        self.active_vehicle_id = vehicle_id
        self.map_view.select_vehicle(vehicle_id)
        self.log_event(f"Выбран активный аппарат роя: БПЛА {vehicle_id}")

    def on_map_clicked(self, lat: float, lon: float) -> None:
        if self.active_vehicle_id is not None:
            self.log_event(f"Команда: БПЛА {self.active_vehicle_id} лететь в точку ({lat:.6f}, {lon:.6f})")
            if self.sim_engine.running:
                self.sim_engine.send_vehicle_command(self.active_vehicle_id, "goto", lat, lon)
            
            # Visualise waypoint on map
            wp = [GeoPoint(lat=lat, lon=lon)]
            self.map_view.update_route(wp)

    def send_swarm_command(self, cmd: str) -> None:
        self.log_event(f"📢 ГРУППОВАЯ КОМАНДА: '{cmd.upper()}' для всех аппаратов роя!")
        if self.sim_engine.running:
            self.sim_engine.send_global_command(cmd)

    def closeEvent(self, event) -> None:
        self.sim_engine.stop()
        event.accept()
