# window_monitor.py
import time
import psutil
from pywinauto.application import Application
from PyQt5.QtCore import QThread, pyqtSignal

# --- КОНСТАНТЫ ДЛЯ ПОИСКА ОКНА ---
PROCESS_NAME = 'sipphone.exe'
MAIN_WINDOW_CLASS = 'TMainForm'
TARGET_TITLE = 'Kartina sip phone' # Убедитесь, что заголовок верный
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
                        continue # Игнорируем ошибки чтения с отдельных элементов

                # 3. Анализируем состояние звонка
                if status_memo_found and not self.is_call_active:
                    self.is_call_active = True
                    self.call_started.emit() # Отправляем сигнал: "Звонок начался!"
                elif not status_memo_found and self.is_call_active:
                    self.is_call_active = False
                    self.call_ended.emit() # Отправляем сигнал: "Звонок закончился!"

            except Exception:
                # Окно не найдено или недоступно, сбрасываем состояние звонка
                if self.is_call_active:
                    self.is_call_active = False
                    self.call_ended.emit()

            time.sleep(0.5)

    def check_process(self):
        """Проверяет, запущен ли процесс sipphone.exe (ИСПРАВЛЕННАЯ ВЕРСИЯ 2)"""
        process_found = False
        # --- НАЧАЛО ИЗМЕНЕНИЙ ---
        try:
            # Этап 1: Перебираем процессы
            for proc in psutil.process_iter(['name']):
                # Этап 2: Обрабатываем каждый отдельный процесс
                try:
                    if proc.info['name'] == PROCESS_NAME:
                        process_found = True
                        break # Нашли, выходим из цикла
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    # Игнорируем процессы, которые уже завершились или к которым нет доступа
                    continue
        except OSError as e:
            # Ловим ошибку, если psutil.process_iter() сам по себе не сработал
            print(f"⚠️  Ошибка psutil.process_iter: {e}. Повторная попытка через несколько секунд...")
            # В случае сбоя возвращаем предыдущее известное состояние, чтобы избежать ложных срабатываний
            return self.is_process_active
        # --- КОНЕЦ ИЗМЕНЕНИЙ ---

        if process_found:
            if not self.is_process_active:
                self.is_process_active = True
                self.process_running.emit()
            return True
        else:
            if self.is_process_active:
                self.is_process_active = False
                self.is_call_active = False # Если процесс упал, звонок тоже завершен
                self.process_stopped.emit() # Отправляем сигнал: "Процесс остановлен!"
            return False

    def stop(self):
        self._is_running = False