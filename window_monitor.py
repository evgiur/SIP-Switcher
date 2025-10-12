# window_monitor.py
import time
import ctypes
from ctypes import wintypes
from pywinauto.application import Application
from PyQt5.QtCore import QThread, pyqtSignal

# --- КОНСТАНТЫ ДЛЯ ПОИСКА ОКНА ---
PROCESS_NAME = 'sipphone.exe'
MAIN_WINDOW_CLASS = 'TMainForm'
TARGET_TITLE = 'Kartina sip phone'
T_MEMO_CLASS = "TMemo"
TRIGGER_TEXT = "Длительность"

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
    call_started = pyqtSignal()
    call_ended = pyqtSignal()
    process_stopped = pyqtSignal()
    process_running = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._is_running = True
        self.is_call_active = False
        self.is_process_active = False
        
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
                # Окно не найдено или недоступно
                if self.is_call_active:
                    self.is_call_active = False
                    self.call_ended.emit()

            time.sleep(0.5)

    def check_process(self):
        """
        Проверяет наличие процесса через нативный Windows API.
        Более надежный метод, чем psutil для этой задачи.
        """
        process_found = False
        
        try:
            # Создаем снимок всех процессов
            snapshot = self.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
            
            if snapshot == INVALID_HANDLE_VALUE:
                print("❌ Не удалось создать снимок процессов")
                return self.is_process_active
            
            try:
                # Инициализируем структуру
                pe32 = PROCESSENTRY32()
                pe32.dwSize = ctypes.sizeof(PROCESSENTRY32)
                
                # Получаем первый процесс
                if self.Process32First(snapshot, ctypes.byref(pe32)):
                    while True:
                        # Проверяем имя процесса
                        process_name = pe32.szExeFile.decode('utf-8', errors='ignore').lower()
                        if process_name == PROCESS_NAME.lower():
                            process_found = True
                            break
                        
                        # Переходим к следующему процессу
                        if not self.Process32Next(snapshot, ctypes.byref(pe32)):
                            break
            finally:
                # Обязательно закрываем handle
                self.CloseHandle(snapshot)
                
        except Exception as e:
            print(f"❌ Ошибка при проверке процесса: {type(e).__name__}: {e}")
            return self.is_process_active

        # Обновляем состояние процесса
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
                self.process_stopped.emit()
                print(f"❌ Процесс {PROCESS_NAME} остановлен")
            return False

    def stop(self):
        self._is_running = False