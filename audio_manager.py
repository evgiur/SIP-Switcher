# audio_manager.py
import json
from comtypes import CoCreateInstance, COMMETHOD, GUID, IUnknown, CoInitialize, CoUninitialize
from ctypes import POINTER
from ctypes.wintypes import LPCWSTR, DWORD
from pycaw.pycaw import AudioUtilities, EDataFlow
from pycaw import constants as const

# Определяем необходимые GUID константы
CLSID_MMDeviceEnumerator = GUID('{BCDE0395-E52F-467C-8E3D-C4579291692E}')
CLSID_PolicyConfig = GUID('{870af99c-171d-4f9e-af0d-e63df40c2bc9}')

# Определяем интерфейс IPolicyConfig для изменения устройства по умолчанию
class IPolicyConfig(IUnknown):
    _iid_ = GUID('{f8679f50-850a-41cf-9c72-430f290290c8}')
    _methods_ = [
        COMMETHOD([], None, 'GetMixFormat'),
        COMMETHOD([], None, 'GetDeviceFormat'),
        COMMETHOD([], None, 'ResetDeviceFormat'),
        COMMETHOD([], None, 'SetDeviceFormat'),
        COMMETHOD([], None, 'GetProcessingPeriod'),
        COMMETHOD([], None, 'SetProcessingPeriod'),
        COMMETHOD([], None, 'GetShareMode'),
        COMMETHOD([], None, 'SetShareMode'),
        COMMETHOD([], None, 'GetPropertyValue'),
        COMMETHOD([], None, 'SetPropertyValue'),
        COMMETHOD([], None, 'SetDefaultEndpoint',
                  (['in'], LPCWSTR, 'deviceId'),
                  (['in'], DWORD, 'role'))
    ]

def set_default_audio_device_by_id(device_id, device_name):
    """
    Устанавливает аудиоустройство по умолчанию через Windows COM API по его ID.
    """
    print(f"\n[AUDIO] Попытка установить устройство: '{device_name}' (ID: {device_id})")
    try:
        CoInitialize()
        policy_config = CoCreateInstance(
            CLSID_PolicyConfig,
            IPolicyConfig,
            1  # CLSCTX_INPROC_SERVER
        )
        
        # Устанавливаем устройство для всех ролей, с логированием каждой попытки
        roles = {0: "Console", 1: "Multimedia", 2: "Communications"}
        for role_id, role_name in roles.items():
            try:
                policy_config.SetDefaultEndpoint(device_id, role_id)
                print(f"[AUDIO]   ✅ Успешно для роли '{role_name}'")
            except Exception as role_e:
                print(f"[AUDIO]   ❌ Ошибка для роли '{role_name}': {role_e}")
        
        print(f"[AUDIO] ✅ Успешно завершена установка '{device_name}'.")
        return True
    except Exception as e:
        print(f"[AUDIO] ❌ КРИТИЧЕСКАЯ ОШИБКА при установке устройства: {e}")
        return False
    finally:
        CoUninitialize()

def get_all_audio_devices():
    """
    Получает список всех активных устройств воспроизведения.
    Returns:
        list: Список кортежей (имя_устройства, device_id)
    """
    filtered_devices = []
    try:
        CoInitialize()
        all_devices = AudioUtilities.GetAllDevices()
        for device in all_devices:
            if device.state == const.AudioDeviceState.Active and AudioUtilities.GetEndpointDataFlow(device.id) == 'eRender':
                name = device.FriendlyName
                device_id = device.id
                filtered_devices.append((name, device_id))
    except Exception as e:
        print(f"❌ Не удалось получить список аудиоустройств: {e}")
    finally:
        CoUninitialize()
    return filtered_devices

def set_device_from_config(device_type, config_file='config.json'):
    """
    Читает ID устройства из конфига и устанавливает его.
    device_type: 'headset' или 'speakers'
    """
    print(f"[CONFIG] Загрузка устройства типа '{device_type}' из файла '{config_file}'")
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        device_info = config.get(device_type)
        if device_info and 'id' in device_info and device_info['id']:
            device_id = device_info['id']
            device_name = device_info.get('name', 'N/A')
            return set_default_audio_device_by_id(device_id, device_name)
        else:
            print(f"⚠️ Устройство типа '{device_type}' не найдено или его ID пуст в конфигурации.")
            return False
    except FileNotFoundError:
        print(f"❌ Файл конфигурации '{config_file}' не найден.")
        return False
    except Exception as e:
        print(f"❌ Ошибка чтения конфигурации или установки устройства: {e}")
        return False