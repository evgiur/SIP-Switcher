# main_gui.py
import sys
import json
import os
import traceback # <-- ДОБАВИТЬ ЭТОТ ИМПОРТ
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QLabel, QComboBox, QPushButton, QGroupBox, QMessageBox)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPixmap, QFont
import pygame

# Импортируем наши модули
import audio_manager
from window_monitor import MonitorThread

CONFIG_FILE = 'config.json'
# Определяем абсолютный путь к папке, где лежит скрипт
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def get_resource_path(relative_path):
    """Создает полный, надежный путь к файлу ресурса."""
    return os.path.join(BASE_DIR, relative_path)

class SipManagerApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SIP Helper")
        self.setGeometry(200, 200, 400, 450)

        # Инициализация pygame для звуковых уведомлений
        pygame.mixer.init()
        # ИСПРАВЛЕНО: Используем более надежный формат .wav
        self.alert_sound = self.load_sound(get_resource_path('sounds/alert.wav'))

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.layout = QVBoxLayout(self.central_widget)

        self.init_ui()
        self.load_config()
        self.populate_devices()
        
        self.start_monitoring()

    def init_ui(self):
        # --- Секция статуса ---
        status_group = QGroupBox("Текущий статус")
        status_layout = QHBoxLayout()
        self.status_icon_label = QLabel()
        self.status_text_label = QLabel("Ожидание...")
        self.status_text_label.setFont(QFont("Arial", 12))
        status_layout.addWidget(self.status_icon_label)
        status_layout.addWidget(self.status_text_label, 1)
        status_group.setLayout(status_layout)
        self.layout.addWidget(status_group)

        # --- Секция выбора устройств ---
        devices_group = QGroupBox("Настройка аудиоустройств")
        devices_layout = QVBoxLayout()
        
        self.headset_combo = QComboBox()
        self.speakers_combo = QComboBox()
        
        devices_layout.addWidget(QLabel("Гарнитура (для звонка):"))
        devices_layout.addWidget(self.headset_combo)
        devices_layout.addWidget(QLabel("Динамики (по умолчанию):"))
        devices_layout.addWidget(self.speakers_combo)
        
        self.save_btn = QPushButton("Сохранить настройки")
        self.save_btn.clicked.connect(self.save_config)
        devices_layout.addWidget(self.save_btn)
        
        devices_group.setLayout(devices_layout)
        self.layout.addWidget(devices_group)
        self.layout.addStretch()

        # Загрузка иконок
        self.icons = {
            "speakers": QPixmap(get_resource_path('icons/speakers.png')),
            "headset": QPixmap(get_resource_path('icons/headset.png')),
            "disconnected": QPixmap(get_resource_path('icons/shutdown.png'))
        }
        self.update_status("disconnected", "SIP-телефон не найден")

    def load_sound(self, path):
        if os.path.exists(path):
            return pygame.mixer.Sound(path)
        print(f"⚠️ Звуковой файл не найден: {path}")
        return None

    def play_alert(self):
        if self.alert_sound:
            self.alert_sound.play()

    def update_status(self, icon_key, text):
        if icon_key in self.icons:
            self.status_icon_label.setPixmap(self.icons[icon_key].scaled(64, 64, Qt.KeepAspectRatio))
        self.status_text_label.setText(text)

    def populate_devices(self):
        self.devices = audio_manager.get_all_audio_devices()
        
        self.headset_combo.clear()
        self.speakers_combo.clear()

        if not self.devices:
            self.headset_combo.addItem("Устройства не найдены", None)
            self.speakers_combo.addItem("Устройства не найдены", None)
            return

        for name, dev_id in self.devices:
            self.headset_combo.addItem(name, dev_id)
            self.speakers_combo.addItem(name, dev_id)
        
        config = self.load_config()
        if 'headset' in config and config['headset']['id']:
            idx = self.headset_combo.findData(config['headset']['id'])
            if idx != -1: self.headset_combo.setCurrentIndex(idx)
        if 'speakers' in config and config['speakers']['id']:
            idx = self.speakers_combo.findData(config['speakers']['id'])
            if idx != -1: self.speakers_combo.setCurrentIndex(idx)

    def load_config(self):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def save_config(self):
        config = {
            "headset": {
                "name": self.headset_combo.currentText(),
                "id": self.headset_combo.currentData()
            },
            "speakers": {
                "name": self.speakers_combo.currentText(),
                "id": self.speakers_combo.currentData()
            }
        }
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
        
        QMessageBox.information(self, "Сохранено", "Настройки аудиоустройств сохранены.")
        self.on_call_ended()

    def start_monitoring(self):
        self.monitor_thread = MonitorThread()
        self.monitor_thread.call_started.connect(self.on_call_started)
        self.monitor_thread.call_ended.connect(self.on_call_ended)
        self.monitor_thread.process_stopped.connect(self.on_process_stopped)
        self.monitor_thread.process_running.connect(self.on_process_running)
        self.monitor_thread.start()

    def on_call_started(self):
        print("GUI: Получен сигнал 'call_started'")
        if audio_manager.set_device_from_config('headset'):
            self.update_status("headset", "Активен звонок\n(Гарнитура)")
        
        self.setWindowState(self.windowState() & ~Qt.WindowMinimized | Qt.WindowActive)
        self.activateWindow()
        self.raise_()

    def on_call_ended(self):
        print("GUI: Получен сигнал 'call_ended'")
        if audio_manager.set_device_from_config('speakers'):
            self.update_status("speakers", "Ожидание звонка\n(Динамики)")

    def on_process_stopped(self):
        print("GUI: Получен сигнал 'process_stopped'")
        self.update_status("disconnected", "SIP-телефон не найден")
        self.play_alert() 

    def on_process_running(self):
        print("GUI: Получен сигнал 'process_running'")
        self.on_call_ended()

    def closeEvent(self, event):
        self.monitor_thread.stop()
        self.monitor_thread.wait() 
        audio_manager.set_device_from_config('speakers')
        event.accept()

# --- НОВЫЙ БЛОК: Ловушка для всех необработанных ошибок ---
def log_uncaught_exceptions(ex_cls, ex, tb):
    """Записывает любую необработанную ошибку в файл."""
    text = '{}: {}:\n'.format(ex_cls.__name__, ex)
    text += ''.join(traceback.format_tb(tb))
    print(text) # Также выводим в консоль
    with open('crash_log.txt', 'a') as f:
        f.write(text)
    sys.exit(1)

sys.excepthook = log_uncaught_exceptions
# -------------------------------------------------------------

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = SipManagerApp()
    window.show()
    sys.exit(app.exec_())