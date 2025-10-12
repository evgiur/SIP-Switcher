# window_monitor.py
import time
import ctypes
import warnings
import re
from ctypes import wintypes
from pywinauto.application import Application
from PyQt5.QtCore import QThread, pyqtSignal

# Подавляем предупреждение о разрядности Python/приложения
warnings.filterwarnings('ignore', message='.*32-bit application should be automated.*')

# --- КОНСТАНТЫ ДЛЯ ПОИСКА ОКНА ---
PROCESS_NAME = 'sipphone.exe'
MAIN_WINDOW_CLASS = 'TMainForm'
TARGET_TITLE = 'Kartina sip phone'
T_MEMO_CLASS = "TMemo"
TRIGGER_CALL = "Вызов"
TRIGGER_DURATION = "Длительность"

# Направления звонков
DIRECTIONS = ["tv_tech", "tv_order", "tv_pay_tech"]

# Windows API константы
TH32CS_SNAPPROCESS = 0x00000002
INVALID_HANDLE_VALUE = -1

# Структуры для Windows API
class PROCESSENTRY32(ctypes.Structure):
    _fields_ = [
        ('dwSize', wintypes.DWORD),
        ('cntUsage', wintypes.DWORD),
        ('th32ProcessID', wintypes.DWORD),
        ('th32DefaultHeapID', ctypes.POINTER(wintypes.ULONG)),
        ('th32ModuleID', wintypes.DWORD),
        ('cntThreads', wintypes.DWORD),
        ('th32ParentProcessID', wintypes.DWORD),
        ('pcPriClassBase', wintypes.LONG),
        ('dwFlags', wintypes.DWORD),
        ('szExeFile', wintypes.CHAR * 260)
    ]

class MonitorThread(QThread):
    call_started = pyqtSignal()  # Звонок принят (появилась "Длительность")
    call_ended = pyqtSignal()
    process_stopped = pyqtSignal()
    process_running = pyqtSignal()
    incoming_call = pyqtSignal(str)  # Входящий вызов с направлением (tv_tech, tv_order и т.д.)
    call_answered = pyqtSignal()  # Звонок принят (переход от "Вызов" к "Длительность")

    def __init__(self):
        super().__init__()
        self._is_running = True
        self.is_call_active = False
        self.is_process_active = False
        self.is_incoming_call = False  # Входящий звонок (есть "Вызов")
        self.current_direction = None  # Текущее направление звонка
        
        # Загружаем Windows API функции
        self.kernel32 = ctypes.windll.kernel32
        self.CreateToolhelp32Snapshot = self.kernel32.CreateToolhelp32Snapshot
        self.Process32First = self.kernel32.Process32First
        self.Process32Next = self.kernel32.Process32Next
        self.CloseHandle = self.kernel32.CloseHandle

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

                # Если окно свернуто, разворачиваем его временно для чтения данных
                was_minimized = main_window.is_minimized()
                if was_minimized:
                    from ctypes import windll
                    SW_SHOWNOACTIVATE = 4
                    windll.user32.ShowWindow(main_window.handle, SW_SHOWNOACTIVATE)
                    time.sleep(0.1)

                # Ищем TMemo с триггерными текстами
                memo_text = ""
                for memo in main_window.children(class_name=T_MEMO_CLASS):
                    try:
                        text = memo.window_text()
                        if TRIGGER_CALL in text or TRIGGER_DURATION in text:
                            memo_text = text
                            break
                    except Exception:
                        continue

                # Возвращаем окно в свернутое состояние, если оно было свернуто
                if was_minimized:
                    SW_MINIMIZE = 6
                    windll.user32.ShowWindow(main_window.handle, SW_MINIMIZE)

                # 3. Анализируем состояние звонка
                self.analyze_call_state(memo_text)

            except Exception as e:
                print(f"⚠️ Временная ошибка доступа к окну: {e}")

            time.sleep(0.5)

    def analyze_call_state(self, memo_text):
        """Анализирует текст из TMemo и определяет состояние звонка"""
        has_incoming = TRIGGER_CALL in memo_text
        has_duration = TRIGGER_DURATION in memo_text
        
        # Определяем направление звонка
        direction = None
        if has_incoming or has_duration:
            for dir_name in DIRECTIONS:
                if dir_name in memo_text:
                    direction = dir_name
                    break
        
        # Логика состояний:
        
        # 1. Входящий звонок (есть "Вызов", нет "Длительность")
        if has_incoming and not has_duration:
            if not self.is_incoming_call:
                self.is_incoming_call = True
                self.current_direction = direction
                print(f"📞 ВХОДЯЩИЙ ВЫЗОВ: {direction}")
                self.incoming_call.emit(direction if direction else "Неизвестно")
        
        # 2. Звонок принят (был "Вызов", появилась "Длительность")
        elif has_duration:
            # Если это переход от входящего к активному
            if self.is_incoming_call and not self.is_call_active:
                self.is_incoming_call = False
                self.is_call_active = True
                print(f"✅ ЗВОНОК ПРИНЯТ: {self.current_direction}")
                self.call_answered.emit()
                self.call_started.emit()
            # Если звонок уже был активен, просто продолжаем
            elif not self.is_call_active:
                self.is_call_active = True
                self.current_direction = direction
                self.call_started.emit()
        
        # 3. Звонок завершен (нет ни "Вызов", ни "Длительность")
        else:
            if self.is_incoming_call:
                # Входящий звонок был пропущен/отменен
                print("❌ ВЫЗОВ ПРОПУЩЕН/ОТМЕНЕН")
                self.is_incoming_call = False
                self.current_direction = None
                self.call_ended.emit()
            elif self.is_call_active:
                # Активный звонок завершен
                print("📴 ЗВОНОК ЗАВЕРШЕН")
                self.is_call_active = False
                self.current_direction = None
                self.call_ended.emit()

    def check_process(self):
        """
        Проверяет наличие процесса через нативный Windows API.
        """
        process_found = False
        
        try:
            snapshot = self.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
            
            if snapshot == INVALID_HANDLE_VALUE:
                print("❌ Не удалось создать снимок процессов")
                return self.is_process_active
            
            try:
                pe32 = PROCESSENTRY32()
                pe32.dwSize = ctypes.sizeof(PROCESSENTRY32)
                
                if self.Process32First(snapshot, ctypes.byref(pe32)):
                    while True:
                        process_name = pe32.szExeFile.decode('utf-8', errors='ignore').lower()
                        if process_name == PROCESS_NAME.lower():
                            process_found = True
                            break
                        
                        if not self.Process32Next(snapshot, ctypes.byref(pe32)):
                            break
            finally:
                self.CloseHandle(snapshot)
                
        except Exception as e:
            print(f"❌ Ошибка при проверке процесса: {type(e).__name__}: {e}")
            return self.is_process_active

        if process_found:
            if not self.is_process_active:
                self.is_process_active = True
                self.process_running.emit()
                print(f"✅ Процесс {PROCESS_NAME} обнаружен")
            return True
        else:
            if self.is_process_active:
                self.is_process_active = False
                self.is_call_active = False
                self.is_incoming_call = False
                self.current_direction = None
                self.process_stopped.emit()
                print(f"❌ Процесс {PROCESS_NAME} остановлен")
            return False

    def stop(self):
        self._is_running = False