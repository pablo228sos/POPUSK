from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QProgressBar, QStackedWidget, QFrame, QGridLayout
)
from PyQt6.QtCore import Qt, QTimer

class CalibrationWizard(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.init_ui()

    def init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(15)

        # Header Title
        title = QLabel("Мастер Калибровки БПЛА")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #38bdf8;")
        layout.addWidget(title)

        subtitle = QLabel("Калибровка датчиков полета, компаса и аппаратуры управления радиоканалом.")
        subtitle.setStyleSheet("color: #94a3b8; font-size: 12px;")
        layout.addWidget(subtitle)

        # Step indicator header
        self.step_frame = QFrame()
        self.step_frame.setStyleSheet("background-color: #1e293b; border-radius: 8px; border: 1px solid rgba(255,255,255,0.06);")
        step_layout = QHBoxLayout(self.step_frame)
        step_layout.setContentsMargins(10, 10, 10, 10)
        
        self.step_labels = []
        steps = ["1. Акселерометр", "2. Компас", "3. Радиоаппаратура", "4. Регуляторы ESC"]
        for idx, step_name in enumerate(steps):
            lbl = QLabel(step_name)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet("color: #94a3b8; font-weight: bold; font-size: 11px;")
            if idx == 0:
                lbl.setStyleSheet("color: #38bdf8; font-weight: bold; font-size: 11px;")
            step_layout.addWidget(lbl)
            self.step_labels.append(lbl)
            
            if idx < len(steps) - 1:
                arrow = QLabel("➔")
                arrow.setStyleSheet("color: #475569;")
                step_layout.addWidget(arrow)
                
        layout.addWidget(self.step_frame)

        # Stacked widgets for wizard pages
        self.pages = QStackedWidget()
        
        self.pages.addWidget(self.create_accel_page())
        self.pages.addWidget(self.create_compass_page())
        self.pages.addWidget(self.create_radio_page())
        self.pages.addWidget(self.create_esc_page())
        
        layout.addWidget(self.pages)

        # Bottom navigation
        nav_layout = QHBoxLayout()
        self.btn_prev = QPushButton("Назад")
        self.btn_prev.setObjectName("btn_prev")
        self.btn_prev.setProperty("class", "secondary_btn")
        self.btn_prev.clicked.connect(self.prev_page)
        self.btn_prev.setEnabled(False)

        self.btn_next = QPushButton("Далее")
        self.btn_next.setObjectName("btn_next")
        self.btn_next.setProperty("class", "primary_btn")
        self.btn_next.clicked.connect(self.next_page)

        nav_layout.addWidget(self.btn_prev)
        nav_layout.addStretch()
        nav_layout.addWidget(self.btn_next)
        layout.addLayout(nav_layout)

    def create_accel_page(self) -> QWidget:
        page = QFrame()
        page.setProperty("class", "card")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        lbl = QLabel("Калибровка Акселерометра (3D)")
        lbl.setStyleSheet("font-size: 14px; font-weight: bold; color: #f8fafc;")
        layout.addWidget(lbl)

        desc = QLabel(
            "Для калибровки сенсоров необходимо последовательно разместить БПЛА в 6 положениях:\n"
            "1. Горизонтально на ровной поверхности (Level)\n"
            "2. На левом боку (Left)\n"
            "3. На правом боку (Right)\n"
            "4. Носом вниз (Nose Down)\n"
            "5. Носом вверх (Nose Up)\n"
            "6. Вверх дном (Back)"
        )
        desc.setStyleSheet("color: #cbd5e1; line-height: 1.5; font-size: 12px;")
        layout.addWidget(desc)

        self.accel_status = QLabel("Текущее действие: Ожидание запуска...")
        self.accel_status.setStyleSheet("color: #f59e0b; font-weight: bold; font-size: 12px;")
        layout.addWidget(self.accel_status)

        self.accel_progress = QProgressBar()
        self.accel_progress.setRange(0, 100)
        self.accel_progress.setValue(0)
        self.accel_progress.setStyleSheet("QProgressBar { background-color: #1e293b; border: 1px solid #334155; border-radius: 4px; height: 16px; text-align: center; color: white; } QProgressBar::chunk { background-color: #10b981; }")
        layout.addWidget(self.accel_progress)

        self.btn_start_accel = QPushButton("Начать калибровку")
        self.btn_start_accel.setProperty("class", "success_btn")
        self.btn_start_accel.clicked.connect(self.start_accel_calibration)
        layout.addWidget(self.btn_start_accel)
        
        layout.addStretch()
        return page

    def create_compass_page(self) -> QWidget:
        page = QFrame()
        page.setProperty("class", "card")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        lbl = QLabel("Калибровка Компаса")
        lbl.setStyleSheet("font-size: 14px; font-weight: bold; color: #f8fafc;")
        layout.addWidget(lbl)

        desc = QLabel(
            "Вращайте летательный аппарат вокруг всех осей на 360 градусов в воздухе,\n"
            "пока калибровочные сферы не заполнятся точками. Не проводите калибровку\n"
            "вблизи сильных магнитных полей (в помещениях, рядом с компьютерами или металлом)."
        )
        desc.setStyleSheet("color: #cbd5e1; line-height: 1.5; font-size: 12px;")
        layout.addWidget(desc)

        self.compass_status = QLabel("Степень заполнения сфер: 0%")
        self.compass_status.setStyleSheet("color: #f59e0b; font-weight: bold; font-size: 12px;")
        layout.addWidget(self.compass_status)

        self.compass_progress = QProgressBar()
        self.compass_progress.setRange(0, 100)
        self.compass_progress.setValue(0)
        self.compass_progress.setStyleSheet("QProgressBar { background-color: #1e293b; border: 1px solid #334155; border-radius: 4px; height: 16px; text-align: center; color: white; } QProgressBar::chunk { background-color: #0ea5e9; }")
        layout.addWidget(self.compass_progress)

        self.btn_start_compass = QPushButton("Запустить калибровку компаса")
        self.btn_start_compass.setProperty("class", "success_btn")
        self.btn_start_compass.clicked.connect(self.start_compass_calibration)
        layout.addWidget(self.btn_start_compass)

        layout.addStretch()
        return page

    def create_radio_page(self) -> QWidget:
        page = QFrame()
        page.setProperty("class", "card")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        lbl = QLabel("Калибровка Радиоаппаратуры (Пульт RC)")
        lbl.setStyleSheet("font-size: 14px; font-weight: bold; color: #f8fafc;")
        layout.addWidget(lbl)

        desc = QLabel(
            "Включите передатчик пульта. Переместите все стики и переключатели (тумблеры)\n"
            "в их крайние положения по несколько раз для определения лимитов (1000 - 2000 мкс)."
        )
        desc.setStyleSheet("color: #cbd5e1; line-height: 1.4; font-size: 12px;")
        layout.addWidget(desc)

        # 4 core RC channels view
        grid = QGridLayout()
        grid.setSpacing(10)
        
        channels = ["CH1 (Roll/Крен)", "CH2 (Pitch/Тангаж)", "CH3 (Throttle/Газ)", "CH4 (Yaw/Рыскание)"]
        self.rc_progress_bars = []
        for i, ch_name in enumerate(channels):
            lbl_ch = QLabel(ch_name)
            lbl_ch.setStyleSheet("font-weight: 500; font-size: 11px; color: #94a3b8;")
            grid.addWidget(lbl_ch, i, 0)
            
            pbar = QProgressBar()
            pbar.setRange(1000, 2000)
            pbar.setValue(1500)
            pbar.setStyleSheet("QProgressBar { background-color: #1e293b; border: 1px solid #334155; border-radius: 4px; height: 12px; text-align: center; color: white; font-size: 9px; } QProgressBar::chunk { background-color: #a78bfa; }")
            pbar.setFormat("%v мкс")
            grid.addWidget(pbar, i, 1)
            self.rc_progress_bars.append(pbar)

        layout.addLayout(grid)

        self.btn_start_radio = QPushButton("Запустить калибровку стиков")
        self.btn_start_radio.setProperty("class", "success_btn")
        self.btn_start_radio.clicked.connect(self.start_radio_calibration)
        layout.addWidget(self.btn_start_radio)

        layout.addStretch()
        return page

    def create_esc_page(self) -> QWidget:
        page = QFrame()
        page.setProperty("class", "card")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        lbl = QLabel("Калибровка регуляторов ESC")
        lbl.setStyleSheet("font-size: 14px; font-weight: bold; color: #f8fafc;")
        layout.addWidget(lbl)

        desc = QLabel(
            "Для калибровки диапазона газа регуляторов моторов (ESC):\n\n"
            "1. Снимите пропеллеры с БПЛА (КРИТИЧЕСКИ ВАЖНО ДЛЯ БЕЗОПАСНОСТИ!)\n"
            "2. Подключите пульт RC, установите стик газа на максимум.\n"
            "3. Подсоедините батарею к БПЛА (звуковой сигнал ESC).\n"
            "4. Опустите стик газа на минимум (подтверждающий звуковой сигнал).\n"
            "5. Проверьте плавность вращения моторов при аккуратном поднятии газа."
        )
        desc.setStyleSheet("color: #cbd5e1; line-height: 1.5; font-size: 12px;")
        layout.addWidget(desc)
        
        alert = QLabel("⚠️ ВНИМАНИЕ: Всегда снимайте пропеллеры перед калибровкой регуляторов!")
        alert.setStyleSheet("color: #ef4444; font-weight: bold; font-size: 11px;")
        layout.addWidget(alert)

        self.esc_status = QLabel("Статус: Ожидание")
        self.esc_status.setStyleSheet("color: #f59e0b; font-weight: bold; font-size: 12px;")
        layout.addWidget(self.esc_status)

        self.btn_esc_action = QPushButton("Активировать режим калибровки ESC")
        self.btn_esc_action.setProperty("class", "danger_btn")
        self.btn_esc_action.clicked.connect(self.trigger_esc_calibration)
        layout.addWidget(self.btn_esc_action)

        layout.addStretch()
        return page

    def update_navigation(self) -> None:
        idx = self.pages.currentIndex()
        self.btn_prev.setEnabled(idx > 0)
        
        if idx == self.pages.count() - 1:
            self.btn_next.setText("Завершить")
        else:
            self.btn_next.setText("Далее")

        # Update highlighted step label
        for i, lbl in enumerate(self.step_labels):
            if i == idx:
                lbl.setStyleSheet("color: #38bdf8; font-weight: bold; font-size: 11px;")
            else:
                lbl.setStyleSheet("color: #94a3b8; font-weight: bold; font-size: 11px;")

    def next_page(self) -> None:
        idx = self.pages.currentIndex()
        if idx < self.pages.count() - 1:
            self.pages.setCurrentIndex(idx + 1)
            self.update_navigation()
        else:
            # Complete wizard
            self.accel_status.setText("Текущее действие: Ожидание запуска...")
            self.accel_progress.setValue(0)
            self.compass_status.setText("Степень заполнения сфер: 0%")
            self.compass_progress.setValue(0)
            for pb in self.rc_progress_bars:
                pb.setValue(1500)
            self.esc_status.setText("Статус: Ожидание")
            self.pages.setCurrentIndex(0)
            self.update_navigation()
            
            # If parent has accept() (is a QDialog wrapper), close it
            parent_window = self.window()
            if hasattr(parent_window, "accept"):
                parent_window.accept()

    def prev_page(self) -> None:
        idx = self.pages.currentIndex()
        if idx > 0:
            self.pages.setCurrentIndex(idx - 1)
            self.update_navigation()

    # --- Accel Calibration Loop (Mock) ---
    def start_accel_calibration(self) -> None:
        self.btn_start_accel.setEnabled(False)
        self.accel_val = 0
        self.accel_step = 1
        self.accel_steps_desc = [
            "Level: Установите БПЛА горизонтально...",
            "Left: Поверните БПЛА на левый бок...",
            "Right: Поверните БПЛА на правый бок...",
            "Nose Down: Наклоните БПЛА носом вниз...",
            "Nose Up: Наклоните БПЛА носом вверх...",
            "Back: Переверните БПЛА вверх дном..."
        ]
        self.accel_status.setText(self.accel_steps_desc[0])
        
        self.accel_timer = QTimer()
        self.accel_timer.timeout.connect(self._tick_accel)
        self.accel_timer.start(100) # Tick every 100ms

    def _tick_accel(self) -> None:
        self.accel_val += 4
        self.accel_progress.setValue(self.accel_val)
        
        if self.accel_val >= 100:
            self.accel_val = 0
            if self.accel_step < len(self.accel_steps_desc):
                self.accel_status.setText(self.accel_steps_desc[self.accel_step])
                self.accel_step += 1
            else:
                self.accel_timer.stop()
                self.accel_status.setText("✅ Калибровка акселерометра успешно завершена!")
                self.accel_progress.setValue(100)
                self.btn_start_accel.setEnabled(True)

    # --- Compass Calibration Loop (Mock) ---
    def start_compass_calibration(self) -> None:
        self.btn_start_compass.setEnabled(False)
        self.compass_val = 0
        self.compass_status.setText("Калибровка запущена. Вращайте БПЛА по всем осям...")
        
        self.compass_timer = QTimer()
        self.compass_timer.timeout.connect(self._tick_compass)
        self.compass_timer.start(80)

    def _tick_compass(self) -> None:
        self.compass_val += 2
        self.compass_progress.setValue(self.compass_val)
        self.compass_status.setText(f"Степень заполнения сфер: {self.compass_val}%")
        
        if self.compass_val >= 100:
            self.compass_timer.stop()
            self.compass_status.setText("✅ Калибровка компаса успешно выполнена!")
            self.btn_start_compass.setEnabled(True)

    # --- Radio Stick Calibration Loop (Mock) ---
    def start_radio_calibration(self) -> None:
        self.btn_start_radio.setEnabled(False)
        self.radio_ticks = 0
        
        self.radio_timer = QTimer()
        self.radio_timer.timeout.connect(self._tick_radio)
        self.radio_timer.start(50)

    def _tick_radio(self) -> None:
        self.radio_ticks += 1
        
        # Jitter stick values to simulate user calibration movement
        angle = self.radio_ticks * 0.15
        
        # Channel values oscillate between 1000 and 2000
        ch1 = int(1500 + 480 * math.sin(angle))
        ch2 = int(1500 + 450 * math.cos(angle * 0.8))
        ch3 = int(1500 + 490 * math.sin(angle * 1.2))
        ch4 = int(1500 + 470 * math.cos(angle * 0.5))
        
        self.rc_progress_bars[0].setValue(ch1)
        self.rc_progress_bars[1].setValue(ch2)
        self.rc_progress_bars[2].setValue(ch3)
        self.rc_progress_bars[3].setValue(ch4)
        
        if self.radio_ticks >= 80:
            self.radio_timer.stop()
            for pb in self.rc_progress_bars:
                pb.setValue(1500)
            self.btn_start_radio.setEnabled(True)

    # --- ESC Calibration (Mock) ---
    def trigger_esc_calibration(self) -> None:
        self.esc_status.setText("Калибровка ESC запущена! Установите газ на максимум на пульте.")
        QTimer.singleShot(2500, lambda: self.esc_status.setText("ESC вошел в режим калибровки. Подтверждающий гудок. Опустите газ на минимум."))
        QTimer.singleShot(5000, lambda: self.esc_status.setText("✅ Калибровка регуляторов ESC успешно завершена."))

import math
