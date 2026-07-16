import json
from pathlib import Path


# === НАСТРОЙКА МОДЕЛИ ===
MODEL_NAME = 's5731-h48t4xc'

# Список диапазонов портов для этой модели.
# Один диапазон — это один набор портов одного типа.
RANGES = [
    # Все порты оптические
    {
        "start": 1,
        "end": 48,
        "type": "copper-1ge", 
        # Паттерны именования. %d - номер порта.
        # name_pattern_2 можно оставить пустым, если он не нужен.
        "name_pattern_1": "GigabitEthernet0/0/%d",
        "name_pattern_2": ""
    },
    {
        "start": 1,
        "end": 4,
        "type": "sfp-plus-10ge", 
        "name_pattern_1": "XGigabitEthernet0/0/%d",
        "name_pattern_2": ""
    }
]
# === КОНЕЦ НАЛАДАЕК ===


def main():
    interfaces = []
    
    for rng in RANGES:
        # Проходимся по каждому номеру порта в заданном диапазоне.
        for port_num in range(rng["start"], rng["end"] + 1):
            # Создаём интерфейс для первого паттерна.
            iface = {"name": rng["name_pattern_1"].replace("%d", str(port_num)),
                     "type": rng["type"]}
            interfaces.append(iface)
            
            # Если указан второй паттерн, создаём ещё одну запись.
            if rng["name_pattern_2"]:
                iface = {"name": rng["name_pattern_2"].replace("%d", str(port_num)),
                         "type": rng["type"]}
                interfaces.append(iface)

    template_data = {MODEL_NAME: interfaces}

    output_dir = Path("interface_templates").resolve()
    output_dir.mkdir(exist_ok=True)
    with open(output_dir / f"interface_{MODEL_NAME}.json", "w") as f:
        json.dump(template_data, f, indent=4)

    print(f"Сгенерирован шаблон для '{MODEL_NAME}'")


if __name__ == "__main__":
    main()
