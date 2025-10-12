# window_monitor.py
import time
import psutil
from pywinauto.application import Application
from PyQt5.QtCore import QThread, pyqtSignal

# --- КОНСТАНТЫ ДЛЯ ПОИСКА ОКНА ---
PROCESS_NAME = 'sipphone.exe'
MAIN_WINDOW_CLASS = 'TMainForm'
TARGET_TITLE = 'Kartina sip phone'
T_MEMO_CLASS = "TMemo"
TRIGGER_TEXT = "Длительность"

class MonitorThread(QThread):
    # Сигналы, которые поток будет отправлять в основной GUI
    call_started = pyqtSignal()
    call_ended = pyqtSignal()
    process_stopped = pyqtSignal()
    process_running = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._is_running = True
        self.is_call_active = False
        self.is_process_active = False
        self.error_count = 0  # Счетчик последовательных ошибок
        self.max_errors = 5   # Максимальное количество ошибок подряд

    def run(self):
        while self._is_running:
            # 1. Проверяем, запущен ли процесс
            if not self.check_process():
                time.sleep(2)
                continue

            # 2. Если процесс запущен, пытаемся подключиться к окну
            try:
                app = Application(backend="win32").connect(path=PROCESS_NAME, timeout=5)
                main_window = app.window(class_name=MAIN_WINDOW_CLASS, title=TARGET_TITLE)

                # Ищем TMemo с триггерным текстом
                status_memo_found = False
                for memo in main_window.children(class_name=T_MEMO_CLASS):
                    try:
                        if TRIGGER_TEXT in memo.window_text():
                            status_memo_found = True
                            break
                    except Exception:
                        continue

                # 3. Анализируем состояние звонка
                if status_memo_found and not self.is_call_active:
                    self.is_call_active = True
                    self.call_started.emit()
                elif not status_memo_found and self.is_call_active:
                    self.is_call_active = False
                    self.call_ended.emit()

            except Exception:
                # Окно не найдено или недоступно, сбрасываем состояние звонка
                if self.is_call_active:
                    self.is_call_active = False
                    self.call_ended.emit()

            time.sleep(0.5)

    def check_process(self):
        """Проверяет, запущен ли процесс sipphone.exe с улучшенной обработкой ошибок"""
        process_found = False
        
        try:
            # Используем более надежный подход с attrs вместо info
            for proc in psutil.process_iter(['name']):
                try:
                    # Получаем имя процесса безопасным способом
                    proc_name = proc.name()
                    if proc_name == PROCESS_NAME:
                        process_found = True
                        self.error_count = 0  # Сбрасываем счетчик ошибок при успехе
                        break
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    # Игнорируем недоступные процессы
                    continue
                    
        except (OSError, WindowsError) as e:
            # Обработка системных ошибок Windows
            self.error_count += 1
            
            if self.error_count <= 3:
                # Первые несколько ошибок только логируем
                print(f"⚠️  Временная ошибка psutil ({self.error_count}/{self.max_errors}): {e}")
            elif self.error_count == self.max_errors:
                # После 5 ошибок подряд выводим предупреждение
                print(f"❌ Критическая ошибка psutil после {self.max_errors} попыток. Возможны проблемы с мониторингом.")
            
            # Возвращаем последнее известное состояние для стабильности
            return self.is_process_active
            
        except Exception as e:
            # Ловим любые другие непредвиденные ошибки
            print(f"❌ Неожиданная ошибка в check_process: {type(e).__name__}: {e}")
            return self.is_process_active

        # Обновляем состояние процесса
        if process_found:
            if not self.is_process_active:
                self.is_process_active = True
                self.process_running.emit()
                print("✅ Процесс sipphone.exe обнаружен")
            return True
        else:
            if self.is_process_active:
                self.is_process_active = False
                self.is_call_active = False
                self.process_stopped.emit()
                print("❌ Процесс sipphone.exe остановлен")
            return False

    def stop(self):
        self._is_running = False