import os
import json
import requests
import logging
from logging.handlers import RotatingFileHandler
from dotenv import load_dotenv

# === Загрузка переменных из .env ===
load_dotenv('.env_test')

# Расширяем путь до домашней директории для логов
LOG_DIR = os.path.expanduser(os.getenv('LOGDIR', './logs'))
os.makedirs(LOG_DIR, exist_ok=True)

# Настройка логгирования
logger = logging.getLogger('NetBox_DeviceLoader')
logger.setLevel(logging.INFO)
handler = RotatingFileHandler(
    filename=os.path.join(LOG_DIR, "netbox_loader.log"),
    maxBytes=5 * 1024 * 1024,
    backupCount=3
)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)

# Проверка обязательных переменных окружения
URL_NB = os.getenv('URLNB', '').rstrip('/')
API_TOKEN = os.getenv('API_KEY')
SWITCHES_FILE = os.getenv('SWITCHES_FILE')

if not URL_NB or not API_TOKEN or not SWITCHES_FILE:
    logger.critical("Не заданы обязательные переменные окружения (URLNB, API_KEY или SWITCHES_FILE)")
    exit(1)

HEADERS = {
    "Authorization": f"Token {API_TOKEN}",
    "Content-Type": "application/json",
    "Accept": "application/json"
}
VERIFY_SSL = False  # Измените на True, если у вас доверенный SSL-сертификат


def get_id_by_slug(resource, slug):
    """Получение ID объекта по его slug."""
    url = f"{URL_NB}/api/dcim/{resource}/?slug={slug}"
    try:
        resp = requests.get(url, headers=HEADERS, verify=VERIFY_SSL)
        resp.raise_for_status()  # Выбросит исключение при ошибках 4xx/5xx
        data = resp.json()
        results = data.get('results', [])
        if results:
            return results[0]['id']
        else:
            logger.error(f"Не найдено {resource} с slug: '{slug}'")
            return None
    except Exception as e:
        logger.error(f"Ошибка запроса {resource}/slug={slug}: {e}")
        return None

def get_id_by_name(resource, name):
    """Получение ID объекта по его имени."""
    url = f"{URL_NB}/api/dcim/{resource}/?name={name}"
    try:
        resp = requests.get(url, headers=HEADERS, verify=VERIFY_SSL)
        resp.raise_for_status()
        data = resp.json()
        results = data.get('results', [])
        if results:
            return results[0]['id']
        else:
            logger.error(f"Не найдено {resource} с name: '{name}'")
            return None
    except Exception as e:
        logger.error(f"Ошибка запроса {resource}/name={name}: {e}")
        return None

class NbPostDevice:
    """Описывает процесс создания устройства, интерфейса, IP и MAC в NetBox."""

    def __init__(
        self,
        hostname,
        ipaddress,
        mac_address,
        model,
        siteslug,
        locationslug,
        rack,
        position,
        rack_face,
        swroleslug,
        platformslug,
        serial_number,
        status,
        interface,
        type_int,
        hardware_version,
    ):
        self.hostname = hostname
        self.ipaddress = ipaddress
        self.mac_address = mac_address
        self.model = model                    # device_type_id
        self.siteslug = siteslug              # site_id
        self.locationslug = locationslug      # location_id
        self.rack = rack                      # rack_id
        self.position = position              # формат: "U35" или просто "35"
        self.rack_face = rack_face
        self.swroleslug = swroleslug          # role_id (device_role_id)
        self.platformslug = platformslug      # platform_id
        self.serial_number = serial_number
        self.status = status
        self.interface = interface
        self.type_int = type_int
        self.hardware_version = hardware_version

    def prepare_ids(self):
        """Преобразует slug в id через NetBox API (если передан не id)."""
        
        if not isinstance(self.model, int):
            self.model = get_id_by_slug('device-types', self.model)
        if not isinstance(self.swroleslug, int):
            self.swroleslug = get_id_by_slug('device-roles', self.swroleslug)
        if not isinstance(self.siteslug, int):
            self.siteslug = get_id_by_slug('sites', self.siteslug)
        if not isinstance(self.locationslug, int):
            self.locationslug = get_id_by_slug('locations', self.locationslug)
        if not isinstance(self.rack, int):
            self.rack = get_id_by_name('racks', self.rack)
        if not isinstance(self.platformslug, int):
            self.platformslug = get_id_by_slug('platforms', self.platformslug)

    def create_device(self):
        """Создаёт устройство в NetBox."""
        payload = {
            "name": self.hostname,
            "device_type": int(self.model),
            "role": int(self.swroleslug),
            "site": int(self.siteslug),
            "location": int(self.locationslug),
            "rack": int(self.rack),
            "platform": int(self.platformslug),
            "serial": self.serial_number,
            "status": self.status,
            "position": int(str(self.position).lstrip('U')),  # "U35" → 35
            "face": self.rack_face,
            "custom_fields": {
                 "hardware_version": self.hardware_version
            },
#            "asset_tag": "",
            "comments": ""
        }
        logger.info(f"Создаём устройство: {payload}")

        resp = requests.post(
            f"{URL_NB}/api/dcim/devices/",
            headers=HEADERS,
            json=payload,
            verify=VERIFY_SSL
        )
        
        try:
            resp.raise_for_status()
            data = resp.json()
        except requests.exceptions.HTTPError as http_err:
            logger.error(f"HTTP ошибка создания устройства {self.hostname}: {http_err}. Ответ: {resp.text}")
            return None
        except ValueError:
            logger.error(f"Ошибка декодирования JSON ответа при создании устройства {self.hostname}: {resp.text}")
            return None

        device_id = data["id"]
        logger.info(f"Устройство {self.hostname} создано (ID: {device_id})")
        return device_id

    def create_interface(self, device_id):
        """Создаёт интерфейс управления для устройства."""
        payload = {
            "device": device_id,
            "name": self.interface,
            "type": self.type_int,
            "enabled": True
        }
        resp = requests.post(
            f"{URL_NB}/api/dcim/interfaces/",
            headers=HEADERS,
            json=payload,
            verify=VERIFY_SSL
        )
        
        try:
            resp.raise_for_status()
            data = resp.json()
        except requests.exceptions.HTTPError as http_err:
            logger.error(f"HTTP ошибка создания интерфейса {self.interface}: {http_err}. Ответ: {resp.text}")
            return None
        except ValueError:
            logger.error(f"Ошибка декодирования JSON ответа при создании интерфейса {self.interface}: {resp.text}")
            return None

        int_id = data["id"]
        logger.info(f"Интерфейс '{self.interface}' создан (ID: {int_id})")
        return int_id

    def assign_ip_and_mac(self, device_id, int_id):
        """Назначает интерфейсу IP и MAC, делает их основными."""
        success = True

        # IP-адрес
        payload_ip = {
            "address": self.ipaddress,
            "status": "active",
            "assigned_object_type": "dcim.interface",
            "assigned_object_id": int_id
        }
        resp_ip = requests.post(
            f"{URL_NB}/api/ipam/ip-addresses/",
            headers=HEADERS,
            json=payload_ip,
            verify=VERIFY_SSL
        )
        ip_id = None
        try:
            resp_ip.raise_for_status()
            ip_id = resp_ip.json()["id"]
            logger.info(f"IP {self.ipaddress} назначен интерфейсу {int_id}")
        except Exception as e:
            logger.error(f"Ошибка назначения IP: {e}. Ответ: {resp_ip.text}")
            success = False

        # MAC-адрес
 #       payload_mac = {
 #           "mac_address": self.mac_address.lower(),
 #           "assigned_object_type": "dcim.interface",
 #           "assigned_object_id": int_id
 #       }
 #       resp_mac = requests.post(
 #           f"{URL_NB}/api/dcim/mac-addresses/",
 #           headers=HEADERS,
 #           json=payload_mac,
 #           verify=VERIFY_SSL
 #       )
 #       mac_id = None
 #       try:
 #           resp_mac.raise_for_status()
 #           mac_id = resp_mac.json()["id"]
 #           logger.info(f"MAC {self.mac_address} назначен интерфейсу {int_id}")
 #       except Exception as e:
 #           logger.error(f"Ошибка назначения MAC: {e}. Ответ: {resp_mac.text}")
 #           success = False

        # Если назначение IP/MAC прошло успешно — делаем их основными
        if success and (ip_id or mac_id):
            self.make_primary(device_id, int_id, ip_id)

    def make_primary(self, device_id, int_id, ip_id=None ):
        """Делает назначенные IP и MAC основными."""
        # primary_ip4 для устройства
        if ip_id:
            patch_payload = {"primary_ip4": ip_id}
            resp = requests.patch(
                f"{URL_NB}/api/dcim/devices/{device_id}/",
                headers=HEADERS,
                json=patch_payload,
                verify=VERIFY_SSL
            )
            if resp.ok:
                logger.info(f"IP {ip_id} назначен как primary_ip4 для устройства {device_id}")
            else:
                logger.error(f"Ошибка установки primary_ip4: {resp.status_code}: {resp.text}")

        # primary_mac_address для интерфейса
#        if mac_id:
#            patch_payload = {"primary_mac_address": mac_id}
#            resp = requests.patch(
#                f"{URL_NB}/api/dcim/interfaces/{int_id}/",
#                headers=HEADERS,
#                json=patch_payload,
#                verify=VERIFY_SSL
#            )
#            if resp.ok:
#                logger.info(f"MAC {mac_id} назначен как primary для интерфейса {int_id}")
#            else:
#                logger.error(f"Ошибка установки primary_mac_address: {resp.status_code}: {resp.text}")#


def main():
    # Загружаем JSON с устройствами
    with open(SWITCHES_FILE, "r", encoding="utf-8") as f:
        devices = json.load(f)
    
    for device_data in devices:
        print(device_data["type_int"])
        device_obj = NbPostDevice(
            hostname=device_data["hostname"],
            ipaddress=device_data["ipaddress"],
            mac_address=device_data["mac_address"],
            model=device_data["model"],
            siteslug=device_data["siteslug"],
            locationslug=device_data["locationslug"],
            rack=device_data["rack"],
            position=device_data["position"],
            rack_face=device_data["rack_face"],
            swroleslug=device_data["swroleslug"],
            platformslug=device_data["platformslug"],
            serial_number=device_data["serial_number"],
            status=device_data["status"],
            interface=device_data["interface"],
            type_int=device_data["type_int"],
            hardware_version=device_data["hardware_version"]
        )
        try:
            device_obj.prepare_ids()
            device_id = device_obj.create_device()
            if device_id is None:
                continue
            int_id = device_obj.create_interface(device_id)
            if int_id is None:
                continue
            device_obj.assign_ip_and_mac(device_id, int_id)
        except Exception as e:
            logger.critical(f"Критическая ошибка при обработке {device_data['hostname']}: {e}", exc_info=True)


if __name__ == "__main__":
    main()
