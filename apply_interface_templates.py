import os
import json
import logging
import requests
from dotenv import load_dotenv
from logging.handlers import RotatingFileHandler


# === НАСТРОЙКА ЛОГИРОВАНИЯ И ЗАГРУЗКИ ПЕРЕМЕННЫХ ===

load_dotenv('.env_test')  # Загружаем переменные из файла .env_test

LOG_DIR = os.path.expanduser(os.getenv('LOGDIR', './logs'))
os.makedirs(LOG_DIR, exist_ok=True)

logger = None
def setup_logging():
    """Настраивает файловый логгер."""
    global logger
    logger = logging.getLogger('NetBox_TemplateLoader')
    logger.setLevel(logging.INFO)  # INFO — чтобы видеть все действия скрипта

    handler = RotatingFileHandler(
        filename=os.path.join(LOG_DIR, "netbox_template_loader.log"),
        maxBytes=5 * 1024 * 1024,
        backupCount=3
    )
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
setup_logging()

# Загрузка переменных окружения
URL_NB = os.getenv('URLNB').rstrip('/')  # ВАЖНО! Без слэша в конце!
API_TOKEN = os.getenv('API_KEY')
VERIFY_SSL = False  # Для локальной базы без SSL-сертификата
INTERFACES_FILE = os.getenv('INTERFACES_FILE')

HEADERS = {
    "Authorization": f"Token {API_TOKEN}",
    "Content-Type": "application/json",
    "Accept": "application/json"
}


# === ОСНОВНОЙ КЛАСС ===

class NbTemplateApplier:
    """
    Класс для применения шаблонов портов к устройствам в NetBox.
    Работает со строковыми типами интерфейсов вместо числовых ID.
    """

    def __init__(self):
        # Статический словарь соответствия типов.
        # Значения должны совпадать со значением ключа 'value' в ответе API по конкретному порту.
        self.type_map = {
            "virtual": "virtual",          
            "copper-1ge": "1000base-t",  
            "sfp-plus-10ge": "10gbase-x-sfpp",
            "10gbase-sr": "10gbase-x-sfpp", 
            "qsfp-plus-40ge": "40gbase-x-qsfpp",
            # Если будут другие типы портов, добавьте их здесь.
        
        }

    def get_devices_by_model(self, model_slugs):
        """
        Возвращает список ID всех устройств указанных моделей.
        Параметр принимает список slug-моделей (строки).
        """
        devices = []

        for slug in model_slugs:
            url = f"{URL_NB}/api/dcim/devices/?limit=0&device_type={slug}"
            resp = requests.get(url, headers=HEADERS, verify=VERIFY_SSL).json()

            if not resp["results"]:
                logger.warning(f"Модель '{slug}' не найдена или у неё нет устройств.")
                continue

            device_ids = [dev["id"] for dev in resp["results"]]
            devices.extend(device_ids)

        return devices

    def patch_or_create_interfaces(self, device_id, template):
        """
        Применяет шаблон портов к устройству.

        Алгоритм:
         1. Получает список существующих интерфейсов этого устройства.
         2. Для каждого порта из шаблона проверяет его наличие.
             a) Если порт существует -> обновляет его тип и включает.
             b) Если порта нет -> создаёт новый интерфейс.
        """

        # ⚙️ Получаем ВСЕ текущие интерфейсы устройства за один запрос.
        url_ints = f"{URL_NB}/api/dcim/interfaces/?device_id={device_id}&limit=0"
        existing_ifaces = {}

        try:
            resp = requests.get(url_ints, headers=HEADERS, verify=VERIFY_SSL).json()
            # Делаем маппинг имён портов (в нижнем регистре!) к их ID.
            existing_ifaces = {iface["name"].lower(): iface["id"] for iface in resp["results"]}
        except Exception as e:
            logger.error(f"[{device_id}] Ошибка при получении списка интерфейсов: {e}")
            return {"created": 0, "updated": 0}

        created_count = 0
        updated_count = 0

        # Перебираем каждый порт из нашего JSON-шаблона.
        for iface_data in template:
            name = iface_data["name"]
            type_slug = iface_data["type"]

            payload = {
                "enabled": True,               # Включаем порт
                "type": self.type_map[type_slug],  # Устанавливаем нужный тип
               # "description": f"Created by template '{type_slug}'"  # Комментарий
            }

            int_id = existing_ifaces.get(name.lower())
            
            # Порт уже создан устройством автоматически.
            if int_id is not None:
                # Патчим только тип и статус.
                patch_url = f"{URL_NB}/api/dcim/interfaces/{int_id}/"
                try:
                    resp_patch = requests.patch(patch_url, json=payload, headers=HEADERS, verify=VERIFY_SSL)
                    resp_patch.raise_for_status()  # Поднимет исключение, если ошибка сервера
                    updated_count += 1
                    logger.info(f"[{device_id}] Обновлён существующий интерфейс '{name}': {type_slug}")
                except Exception as e:
                    logger.error(f"[{device_id}] Ошибка обновления интерфейса '{name}': {e}. Ответ: {resp_patch.text}")

            # Порт отсутствует, создаём его вручную.
            else:
                # Полная информация для создания нового порта.
                payload.update({
                    "device": device_id,
                    "name": name
                })
                create_url = f"{URL_NB}/api/dcim/interfaces/"
                try:
                    resp_create = requests.post(create_url, json=payload, headers=HEADERS, verify=VERIFY_SSL)
                    resp_create.raise_for_status()
                    new_id = resp_create.json()["id"]
                    created_count += 1
                    logger.info(f"[{device_id}] Создан новый интерфейс '{name}': {type_slug}")
                except Exception as e:
                    logger.error(f"[{device_id}] Ошибка создания интерфейса '{name}': {e}. Ответ: {resp_create.text}")

        return {"created": created_count, "updated": updated_count}



if __name__ == "__main__":
    applier = NbTemplateApplier()

    # ✅ ВАЖНО! Загружаем наши шаблоны из JSON-файла.
    with open(f"{INTERFACES_FILE}", encoding="utf-8") as f:
        templates = json.load(f)

    # Список моделей, к которым мы хотим применить шаблоны.
    models_to_update = [
        "s5731-h48t4xc"  # Ваша тестовая модель
        # "другая-модель", "ещё-одна-модель" — добавляйте сюда новые модели
    ]

    total_created = 0
    total_updated = 0

    # Находим все устройства выбранных моделей.
    all_device_ids = applier.get_devices_by_model(models_to_update)

    logger.info("\n=== Начало обработки ===")
    logger.info(f"Найдено всего устройств: {len(all_device_ids)}")

    # Перебираем каждое устройство.
    for device_id in all_device_ids:
        # Определяем модель текущего устройства.
        dev_url = f"{URL_NB}/api/dcim/devices/{device_id}/"
        resp_dev = requests.get(dev_url, headers=HEADERS, verify=VERIFY_SSL).json()
        hostname = resp_dev["name"]
        model_slug = resp_dev["device_type"]["model"]

        # Находим соответствующий шаблон.
        template = templates.get(model_slug.lower())  # Сравниваем со слугом!
        if template is None:
            logger.warning(f"Устройство '{hostname}' ({model_slug}) не имеет шаблона.")
            continue

        result = applier.patch_or_create_interfaces(device_id, template)
        total_created += result["created"]
        total_updated += result["updated"]

    logger.info("\n=== Итог: ===")
    logger.info(f"Создано новых интерфейсов: {total_created}")
    logger.info(f"Обновлено: {total_updated}")
