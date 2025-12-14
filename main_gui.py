# main_gui.py
import sys
import json
import os
import traceback
import warnings
from datetime import datetime
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QLabel, QComboBox, QPushButton, QGroupBox, QMessageBox, QFileDialog, QCheckBox,
                             QSystemTrayIcon, QMenu, QAction)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QPixmap, QFont, QIcon
import pygame
from pycaw.pycaw import AudioUtilities, ISimpleAudioVolume

# Подавляем предупреждение о разрядности
warnings.filterwarnings('ignore', message='.*32-bit application should be automated.*')

# Импортируем наши модули
import audio_manager
from window_monitor import MonitorThread

CONFIG_FILE = 'config.json'
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def get_resource_path(relative_path):
    """Создает полный, надежный путь к файлу ресурса."""
    return os.path.join(BASE_DIR, relative_path)

class SipManagerApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SIP Helper")
        self.setGeometry(200, 200, 450, 600)

        # Инициализация pygame для звуковых уведомлений
        pygame.mixer.init()
        self.alert_sound = self.load_sound(get_resource_path('sounds/alert.wav'))
        self.ringtone = None  # Кастомный рингтон
        self.ringtone_channel = None  # Канал для воспроизведения рингтона
        self.is_ringtone_testing = False  # Флаг тестирования рингтона
        
        # Секундомер
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_timer)
        self.elapsed_seconds = 0
        self.answer_time = None  # Время ответа на звонок
        
        # Таймер для мигания
        self.blink_timer = QTimer()
        self.blink_timer.timeout.connect(self.blink_answer_label)
        self.blink_state = False
        
        # Процесс sipphone для управления громкостью
        self.sipphone_session = None

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.layout = QVBoxLayout(self.central_widget)

        self.init_ui()
        self.load_config()
        self.populate_devices()
        self.init_tray()
        
        self.start_monitoring()

    def init_ui(self):
        # --- Секция статуса ---
        status_group = QGroupBox("Текущий статус")
        status_layout = QVBoxLayout()
        
        # Иконка и основной статус
        main_status_layout = QHBoxLayout()
        self.status_icon_label = QLabel()
        self.status_text_label = QLabel("Ожидание...")
        self.status_text_label.setFont(QFont("Arial", 12))
        main_status_layout.addWidget(self.status_icon_label)
        main_status_layout.addWidget(self.status_text_label, 1)
        status_layout.addLayout(main_status_layout)
        
        # Направление звонка
        self.direction_label = QLabel("Направление: —")
        self.direction_label.setFont(QFont("Arial", 13, QFont.Bold))
        self.direction_label.setAlignment(Qt.AlignCenter)
        status_layout.addWidget(self.direction_label)
        
        # Время ответа
        self.answer_time_label = QLabel("")
        self.answer_time_label.setFont(QFont("Arial", 11))
        self.answer_time_label.setAlignment(Qt.AlignCenter)
        status_layout.addWidget(self.answer_time_label)
        
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
        
        # --- Секция выбора рингтона ---
        ringtone_group = QGroupBox("Настройка рингтона")
        ringtone_layout = QVBoxLayout()
        
        self.ringtone_label = QLabel("Рингтон не выбран")
        ringtone_layout.addWidget(self.ringtone_label)
        
        ringtone_buttons = QHBoxLayout()
        self.select_ringtone_btn = QPushButton("Выбрать рингтон")
        self.select_ringtone_btn.clicked.connect(self.select_ringtone)
        self.test_ringtone_btn = QPushButton("Тест")
        self.test_ringtone_btn.clicked.connect(self.test_ringtone)
        self.test_ringtone_btn.setEnabled(False)
        
        ringtone_buttons.addWidget(self.select_ringtone_btn)
        ringtone_buttons.addWidget(self.test_ringtone_btn)
        ringtone_layout.addLayout(ringtone_buttons)
        
        ringtone_group.setLayout(ringtone_layout)
        self.layout.addWidget(ringtone_group)
        
        # --- Секция дополнительных настроек ---
        settings_group = QGroupBox("Дополнительные настройки")
        settings_layout = QVBoxLayout()
        
        self.alert_checkbox = QCheckBox("Включить аварийный сигнал при закрытии SIP-телефона")
        self.alert_checkbox.setChecked(False)  # По умолчанию выключено
        settings_layout.addWidget(self.alert_checkbox)
        
        settings_group.setLayout(settings_layout)
        self.layout.addWidget(settings_group)
        
        self.layout.addStretch()

        # Загрузка иконок
        self.icons = {
            "speakers": QPixmap(get_resource_path('icons/speakers.png')),
            "headset": QPixmap(get_resource_path('icons/headset.png')),
            "disconnected": QPixmap(get_resource_path('icons/shutdown.png')),
            "ringing": QPixmap(get_resource_path('icons/headset.png'))  # Можно создать отдельную иконку
        }
        
        for name, pixmap in self.icons.items():
            if pixmap.isNull():
                print(f"⚠️ Не удалось загрузить иконку: {name}")
        
        self.update_status("disconnected", "SIP-телефон не найден")

    def init_tray(self):
        """Инициализация системного трея"""
        # Создаем иконку трея
        tray_icon_path = get_resource_path('icons/headset.png')
        if os.path.exists(tray_icon_path):
            self.tray_icon = QSystemTrayIcon(QIcon(tray_icon_path), self)
        else:
            # Если иконки нет, используем стандартную иконку приложения
            self.tray_icon = QSystemTrayIcon(self)
        
        # Создаем контекстное меню для трея
        tray_menu = QMenu()
        
        show_action = QAction("Показать/Скрыть", self)
        show_action.triggered.connect(self.toggle_window_visibility)
        tray_menu.addAction(show_action)
        
        tray_menu.addSeparator()
        
        quit_action = QAction("Выход", self)
        quit_action.triggered.connect(self.quit_application)
        tray_menu.addAction(quit_action)
        
        self.tray_icon.setContextMenu(tray_menu)
        
        # Клик по иконке трея показывает/скрывает окно
        self.tray_icon.activated.connect(self.on_tray_icon_activated)
        
        # Показываем иконку в трее
        self.tray_icon.show()
        
        print("✅ Системный трей инициализирован")
    
    def on_tray_icon_activated(self, reason):
        """Обработка клика по иконке трея"""
        if reason == QSystemTrayIcon.Trigger:  # Одинарный клик
            self.toggle_window_visibility()
    
    def toggle_window_visibility(self):
        """Переключение видимости окна"""
        if self.isVisible():
            self.hide()
            print("🔽 Окно скрыто в трей")
        else:
            self.show()
            self.setWindowState(self.windowState() & ~Qt.WindowMinimized | Qt.WindowActive)
            self.activateWindow()
            self.raise_()
            print("🔼 Окно показано из трея")

    def load_sound(self, path):
        if os.path.exists(path):
            try:
                return pygame.mixer.Sound(path)
            except Exception as e:
                print(f"⚠️ Ошибка загрузки звука {path}: {e}")
                return None
        print(f"⚠️ Звуковой файл не найден: {path}")
        return None

    def select_ringtone(self):
        """Выбор кастомного рингтона"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, 
            "Выберите рингтон", 
            "", 
            "Аудио файлы (*.wav *.mp3 *.ogg);;Все файлы (*.*)"
        )
        
        if file_path:
            try:
                self.ringtone = pygame.mixer.Sound(file_path)
                self.ringtone_label.setText(f"Рингтон: {os.path.basename(file_path)}")
                self.test_ringtone_btn.setEnabled(True)
                
                # Сохраняем путь в конфиг
                config = self.load_config()
                config['ringtone'] = file_path
                with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                    json.dump(config, f, indent=4, ensure_ascii=False)
                    
                print(f"✅ Рингтон установлен: {file_path}")
            except Exception as e:
                QMessageBox.warning(self, "Ошибка", f"Не удалось загрузить рингтон:\n{e}")

    def test_ringtone(self):
        """Тестирование рингтона (toggle)"""
        if self.ringtone:
            if self.is_ringtone_testing:
                # Останавливаем воспроизведение
                self.stop_ringtone()
                self.is_ringtone_testing = False
                self.test_ringtone_btn.setText("Тест")
                print("🔕 Тестирование рингтона остановлено")
            else:
                # Запускаем воспроизведение (один раз, без loop)
                self.stop_ringtone()
                self.ringtone_channel = self.ringtone.play()
                self.is_ringtone_testing = True
                self.test_ringtone_btn.setText("Стоп")
                print("🔔 Тестирование рингтона запущено")
                
                # Устанавливаем таймер для автоматического возврата кнопки
                # после окончания воспроизведения
                if self.ringtone_channel:
                    duration = int(self.ringtone.get_length() * 1000)  # в миллисекундах
                    QTimer.singleShot(duration, self.on_test_ringtone_finished)
    
    def on_test_ringtone_finished(self):
        """Вызывается когда тестовый рингтон закончил воспроизведение"""
        if self.is_ringtone_testing:
            self.is_ringtone_testing = False
            self.test_ringtone_btn.setText("Тест")
            print("✅ Тестирование рингтона завершено")

    def play_ringtone(self):
        """Воспроизведение рингтона в цикле"""
        if self.ringtone:
            self.stop_ringtone()
            self.ringtone_channel = self.ringtone.play(loops=-1)  # Бесконечный цикл
            print("🔔 Воспроизведение кастомного рингтона")

    def stop_ringtone(self):
        """Остановка рингтона"""
        if self.ringtone_channel:
            self.ringtone_channel.stop()
            self.ringtone_channel = None
            print("🔕 Рингтон остановлен")
        
        # Сбрасываем флаг и кнопку тестирования если рингтон был в режиме теста
        if self.is_ringtone_testing:
            self.is_ringtone_testing = False
            self.test_ringtone_btn.setText("Тест")

    def mute_sipphone(self):
        """Заглушает звук sipphone.exe"""
        try:
            sessions = AudioUtilities.GetAllSessions()
            for session in sessions:
                if session.Process and session.Process.name() == "sipphone.exe":
                    volume = session._ctl.QueryInterface(ISimpleAudioVolume)
                    current_mute = volume.GetMute()
                    if not current_mute:  # Только если еще не заглушен
                        volume.SetMute(1, None)
                        self.sipphone_session = session
                        print("🔇 Звук sipphone.exe заглушен")
                    return True
        except Exception as e:
            print(f"⚠️ Не удалось заглушить sipphone: {e}")
        return False

    def unmute_sipphone(self):
        """Включает звук sipphone.exe"""
        try:
            if self.sipphone_session:
                volume = self.sipphone_session._ctl.QueryInterface(ISimpleAudioVolume)
                volume.SetMute(0, None)
                print("🔊 Звук sipphone.exe включен")
                self.sipphone_session = None
        except Exception as e:
            print(f"⚠️ Не удалось включить звук sipphone: {e}")

    def start_timer(self):
        """Запуск секундомера"""
        self.elapsed_seconds = 0
        self.answer_time = None
        self.blink_timer.stop()  # Останавливаем мигание если было
        self.timer.start(1000)  # Обновление каждую секунду

    def stop_timer(self):
        """Остановка секундомера"""
        self.timer.stop()
        self.blink_timer.stop()

    def update_timer(self):
        """Обновление отображения секундомера"""
        self.elapsed_seconds += 1
        
        # Определяем цвет и нужно ли мигание
        if self.elapsed_seconds <= 12:
            color = "#4CAF50"  # Зеленый
            self.blink_timer.stop()
            self.answer_time_label.setText(f"Время ожидания: {self.elapsed_seconds} сек")
            self.answer_time_label.setStyleSheet(f"color: {color}; font-weight: bold;")
        elif self.elapsed_seconds <= 15:
            color = "#F44336"  # Красный
            # Запускаем мигание если еще не запущено
            if not self.blink_timer.isActive():
                self.blink_timer.start(500)  # Мигание каждые 500мс
            self.answer_time_label.setText(f"Время ожидания: {self.elapsed_seconds} сек")
        else:
            # После 15 секунд продолжаем красным без мигания
            color = "#F44336"
            self.blink_timer.stop()
            self.answer_time_label.setText(f"Время ожидания: {self.elapsed_seconds} сек")
            self.answer_time_label.setStyleSheet(f"color: {color}; font-weight: bold;")
    
    def blink_answer_label(self):
        """Мигание надписи времени ответа"""
        self.blink_state = not self.blink_state
        if self.blink_state:
            self.answer_time_label.setStyleSheet("color: #F44336; font-weight: bold;")  # Красный
        else:
            self.answer_time_label.setStyleSheet("color: transparent; font-weight: bold;")  # Прозрачный
        self.answer_time_label.setText(f"Время ожидания: {self.elapsed_seconds} сек")

    def play_alert(self):
        if self.alert_sound:
            self.alert_sound.play()

    def update_status(self, icon_key, text):
        """Обновляет статус с иконкой и текстом"""
        if icon_key in self.icons and not self.icons[icon_key].isNull():
            scaled_pixmap = self.icons[icon_key].scaled(64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.status_icon_label.setPixmap(scaled_pixmap)
        else:
            print(f"⚠️ Иконка '{icon_key}' недоступна")
        self.status_text_label.setText(text)
        print(f"[STATUS] {icon_key}: {text}")

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
        
        # Загружаем рингтон из конфига
        if 'ringtone' in config and config['ringtone']:
            try:
                self.ringtone = pygame.mixer.Sound(config['ringtone'])
                self.ringtone_label.setText(f"Рингтон: {os.path.basename(config['ringtone'])}")
                self.test_ringtone_btn.setEnabled(True)
            except Exception as e:
                print(f"⚠️ Не удалось загрузить сохраненный рингтон: {e}")
        
        # Загружаем настройку аварийного сигнала
        if 'alert_on_close' in config:
            self.alert_checkbox.setChecked(config['alert_on_close'])
        else:
            self.alert_checkbox.setChecked(False)  # По умолчанию выключено

    def load_config(self):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def save_config(self):
        config = self.load_config()  # Сохраняем существующие настройки (например, ringtone)
        config.update({
            "headset": {
                "name": self.headset_combo.currentText(),
                "id": self.headset_combo.currentData()
            },
            "speakers": {
                "name": self.speakers_combo.currentText(),
                "id": self.speakers_combo.currentData()
            },
            "alert_on_close": self.alert_checkbox.isChecked()
        })
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
        
        QMessageBox.information(self, "Сохранено", "Настройки сохранены.")
        self.on_call_ended()

    def start_monitoring(self):
        self.monitor_thread = MonitorThread()
        self.monitor_thread.call_started.connect(self.on_call_started)
        self.monitor_thread.call_ended.connect(self.on_call_ended)
        self.monitor_thread.process_stopped.connect(self.on_process_stopped)
        self.monitor_thread.process_running.connect(self.on_process_running)
        self.monitor_thread.incoming_call.connect(self.on_incoming_call)
        self.monitor_thread.outgoing_call.connect(self.on_outgoing_call)
        self.monitor_thread.call_answered.connect(self.on_call_answered)
        self.monitor_thread.start()

    def on_incoming_call(self, direction):
        """Обработка входящего звонка"""
        print(f"GUI: Входящий звонок - {direction}")
        
        # КРИТИЧНО: Сначала глушим sipphone
        self.mute_sipphone()
        
        # Небольшая задержка для гарантии применения mute
        import time
        time.sleep(0.05)
        
        # Затем включаем кастомный рингтон
        self.play_ringtone()
        
        # Обновляем GUI с цветовой индикацией направления
        self.update_status("ringing", "Входящий звонок...")
        
        # Устанавливаем цвет в зависимости от направления
        if direction == "tv_tech":
            color = "#4CAF50"  # Зеленый
            direction_text = "tv_tech"
        elif direction == "tv_order":
            color = "#F44336"  # Красный
            direction_text = "tv_order"
        elif direction == "tv_pay_tech":
            color = "#2196F3"  # Синий (можно изменить при необходимости)
            direction_text = "tv_pay_tech"
        else:
            color = "#9E9E9E"  # Серый для неизвестного
            direction_text = direction if direction else "Неизвестно"
        
        self.direction_label.setText(f"Направление: {direction_text}")
        self.direction_label.setStyleSheet(f"color: {color}; font-weight: bold;")
        
        # Запускаем секундомер
        self.start_timer()
        
        # Если окно скрыто в трее, показываем его
        if not self.isVisible():
            self.show()
        
        # Активируем окно
        self.setWindowState(self.windowState() & ~Qt.WindowMinimized | Qt.WindowActive)
        self.activateWindow()
        self.raise_()

    def on_outgoing_call(self):
        """Обработка исходящего звонка"""
        print("GUI: Исходящий звонок")
        
        # При исходящем звонке НЕ воспроизводим рингтон
        # Сразу переключаем на гарнитуру
        if audio_manager.set_device_from_config('headset'):
            self.update_status("headset", "Исходящий звонок\n(Гарнитура)")
        
        self.direction_label.setText("Направление: Исходящий")
        self.direction_label.setStyleSheet("color: #FF9800; font-weight: bold;")  # Оранжевый

    def on_call_answered(self):
        """Обработка момента ответа на звонок"""
        print("GUI: Звонок принят")
        
        # Останавливаем рингтон
        self.stop_ringtone()
        self.unmute_sipphone()
        
        # Фиксируем время ответа в секундах
        self.stop_timer()
        
        # Определяем цвет в зависимости от времени ответа
        if self.elapsed_seconds <= 12:
            color = "#4CAF50"  # Зеленый
        else:
            color = "#F44336"  # Красный (12-15 и больше)
        
        self.answer_time_label.setText(f"Время ответа: {self.elapsed_seconds} сек")
        self.answer_time_label.setStyleSheet(f"color: {color}; font-weight: bold;")

    def on_call_started(self):
        """Активный разговор"""
        print("GUI: Получен сигнал 'call_started'")
        if audio_manager.set_device_from_config('headset'):
            self.update_status("headset", "Активен звонок\n(Гарнитура)")

    def on_call_ended(self):
        """Звонок завершен"""
        print("GUI: Получен сигнал 'call_ended'")
        
        # Останавливаем рингтон и таймер
        self.stop_ringtone()
        self.unmute_sipphone()
        self.stop_timer()
        
        # Сбрасываем отображение
        self.direction_label.setText("Направление: —")
        self.direction_label.setStyleSheet("")
        self.answer_time_label.setText("")
        self.answer_time_label.setStyleSheet("")
        
        if audio_manager.set_device_from_config('speakers'):
            self.update_status("speakers", "Ожидание звонка\n(Динамики)")

    def on_process_stopped(self):
        print("GUI: Получен сигнал 'process_stopped'")
        self.stop_ringtone()
        self.stop_timer()
        self.update_status("disconnected", "SIP-телефон не найден")
        self.direction_label.setText("Направление: —")
        
        # Воспроизводим аварийный сигнал только если настройка включена
        if self.alert_checkbox.isChecked():
            self.play_alert()

    def on_process_running(self):
        print("GUI: Получен сигнал 'process_running'")
        self.on_call_ended()

    def closeEvent(self, event):
        """При закрытии окна (X) сворачиваем в трей вместо выхода"""
        event.ignore()
        self.hide()
        self.tray_icon.showMessage(
            "SIP Helper",
            "Приложение свернуто в трей. Для выхода используйте контекстное меню.",
            QSystemTrayIcon.Information,
            2000
        )
        print("🔽 Окно свернуто в трей")
    
    def quit_application(self):
        """Полный выход из приложения"""
        print("👋 Выход из приложения")
        self.stop_ringtone()
        self.unmute_sipphone()
        self.timer.stop()
        self.blink_timer.stop()
        self.monitor_thread.stop()
        self.monitor_thread.wait()
        audio_manager.set_device_from_config('speakers')
        self.tray_icon.hide()
        QApplication.quit()

def log_uncaught_exceptions(ex_cls, ex, tb):
    """Записывает любую необработанную ошибку в файл."""
    text = '{}: {}:\n'.format(ex_cls.__name__, ex)
    text += ''.join(traceback.format_tb(tb))
    print(text)
    with open('crash_log.txt', 'a') as f:
        f.write(text)
    sys.exit(1)

sys.excepthook = log_uncaught_exceptions

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = SipManagerApp()
    window.show()
    sys.exit(app.exec_())