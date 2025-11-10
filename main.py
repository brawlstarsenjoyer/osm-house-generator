import os
import sys
import random
import logging
import time
import json
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List, Set
from dataclasses import dataclass

import requests
from tqdm import tqdm


# ============================================================================
# КОНФИГУРАЦИЯ
# ============================================================================
@dataclass
class CityBounds:
    name: str
    south: float
    north: float
    west: float
    east: float


@dataclass
class Country:
    name: str
    cities: Dict[str, CityBounds]


class Config:
    # OpenStreetMap API URLs
    OVERPASS_URL = "https://overpass-api.de/api/interpreter"
    NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"

    # Параметры
    MAX_HOUSES = 50
    REQUEST_DELAY = 1.1
    MAX_HOUSES_PER_REQUEST = 200

    # Файлы
    OUTPUT_DIR = "osm_houses"
    HOUSES_FILE = "houses_osm.txt"
    LOG_FILE = "house_osm_generator.log"

    # СТРАНЫ И ГОРОДА (НОВАЯ СТРУКТУРА)
    COUNTRIES = {
        "germany": Country("🇩🇪 Germany", {
            "berlin": CityBounds("Berlin", 52.35, 52.65, 13.15, 13.65),
            "munich": CityBounds("Munich", 48.06, 48.21, 11.45, 11.65),
            "frankfurt": CityBounds("Frankfurt", 50.00, 50.18, 8.40, 8.88),
        }),

        "france": Country("🇫🇷 France", {
            "paris": CityBounds("Paris", 48.80, 48.92, 2.20, 2.50),
            "lyon": CityBounds("Lyon", 45.73, 45.80, 4.80, 4.90),
            "marseille": CityBounds("Marseille", 43.27, 43.32, 5.35, 5.43),
            "nice": CityBounds("Nice", 43.68, 43.73, 7.24, 7.32),
            "toulouse": CityBounds("Toulouse", 43.58, 43.65, 1.41, 1.48),
        }),

        "netherlands": Country("🇳🇱 Netherlands", {
            "amsterdam": CityBounds("Amsterdam", 52.30, 52.42, 4.80, 5.00),
            "rotterdam": CityBounds("Rotterdam", 51.88, 51.94, 4.40, 4.55),
            "utrecht": CityBounds("Utrecht", 52.05, 52.13, 5.05, 5.15),
            "the_hague": CityBounds("The Hague", 52.03, 52.10, 4.27, 4.38),
        }),

        "spain": Country("🇪🇸 Spain", {
            "madrid": CityBounds("Madrid", 40.35, 40.52, -3.85, -3.55),
            "barcelona": CityBounds("Barcelona", 41.30, 41.47, 2.00, 2.25),
            "valencia": CityBounds("Valencia", 39.40, 39.53, -0.45, -0.30),
        }),

        "italy": Country("🇮🇹 Italy", {
            "rome": CityBounds("Rome", 41.80, 41.95, 12.40, 12.55),
            "milan": CityBounds("Milan", 45.43, 45.50, 9.15, 9.25),
            "naples": CityBounds("Naples", 40.82, 40.88, 14.20, 14.30),
            "turin": CityBounds("Turin", 45.04, 45.10, 7.63, 7.73),
            "florence": CityBounds("Florence", 43.76, 43.79, 11.22, 11.30),
        }),

        "austria": Country("🇦🇹 Austria", {
            "vienna": CityBounds("Vienna", 48.15, 48.27, 16.25, 16.50),
            "graz": CityBounds("Graz", 47.04, 47.11, 15.38, 15.48),
            "salzburg": CityBounds("Salzburg", 47.78, 47.82, 13.02, 13.08),
            "innsbruck": CityBounds("Innsbruck", 47.25, 47.28, 11.37, 11.42),
        }),

        "switzerland": Country("🇨🇭 Switzerland", {
            "zurich": CityBounds("Zurich", 47.35, 47.40, 8.50, 8.60),
            "geneva": CityBounds("Geneva", 46.19, 46.25, 6.10, 6.20),
            "basel": CityBounds("Basel", 47.54, 47.58, 7.56, 7.62),
            "bern": CityBounds("Bern", 46.93, 46.97, 7.40, 7.48),
        }),

        "australia": Country("🇦🇺 Australia", {
            "sydney": CityBounds("Sydney", -34.00, -33.70, 150.90, 151.30),
            "melbourne": CityBounds("Melbourne", -37.90, -37.75, 144.90, 145.10),
            "brisbane": CityBounds("Brisbane", -27.55, -27.35, 152.95, 153.15),
            "perth": CityBounds("Perth", -32.05, -31.95, 115.80, 115.95),
        }),

        "canada": Country("🇨🇦 Canada", {
            "toronto": CityBounds("Toronto", 43.60, 43.80, -79.55, -79.25),
            "vancouver": CityBounds("Vancouver", 49.25, 49.30, -123.15, -123.05),
            "montreal": CityBounds("Montreal", 45.45, 45.55, -73.70, -73.45),
            "ottawa": CityBounds("Ottawa", 45.30, 45.45, -75.85, -75.65),
        }),
    }


# ============================================================================
# OpenStreetMap API КЛИЕНТ
# ============================================================================
class OSMAPIClient:
    """Клиент для OpenStreetMap APIs (Overpass + Nominatim)"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'HouseGenerator-OSM/2.0 (contact@your-email.com)',
            'Accept': 'application/json',
        })
        self.overpass_url = Config.OVERPASS_URL
        self.nominatim_url = Config.NOMINATIM_URL
        self.request_count = 0
        self.error_count = 0

    def _make_request(self, url: str, params: dict = None, data: str = None,
                      max_retries: int = 2) -> Optional[Dict[str, Any]]:
        """Универсальный метод запроса с повторными попытками"""
        for attempt in range(max_retries):
            try:
                self.request_count += 1

                if data:
                    response = self.session.post(url, data=data, timeout=15)
                else:
                    response = self.session.get(url, params=params, timeout=15)

                response.raise_for_status()

                if response.status_code == 429:
                    wait = 10 * (attempt + 1)
                    logging.warning(f"⚠️ Превышен лимит! Ждем {wait} сек...")
                    time.sleep(wait)
                    continue

                return response.json()

            except requests.exceptions.RequestException as e:
                logging.warning(f"⚠️ Ошибка сети (попытка {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(3 * (attempt + 1))
            except Exception as e:
                logging.error(f"❌ Неожиданная ошибка: {e}")
                break

        self.error_count += 1
        return None

    def get_residential_buildings(self, city: CityBounds, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Получает жилые дома через Overpass API
        """
        query = f"""
        [out:json][timeout:30];
        (
          nwr["building"="residential"]["addr:housenumber"]({city.south},{city.west},{city.north},{city.east});
          nwr["building"="apartments"]["addr:housenumber"]({city.south},{city.west},{city.north},{city.east});
          nwr["building"="house"]["addr:housenumber"]({city.south},{city.west},{city.north},{city.east});
        );
        out center {limit};
        >;
        out skel qt;
        """

        logging.info(f"📡 Запрос к Overpass API: {city.name} (limit={limit})")
        data = self._make_request(self.overpass_url, data=query)

        if not data or 'elements' not in data:
            logging.warning(f"❌ Пустой ответ Overpass для {city.name}")
            return []

        buildings = []
        for element in data['elements']:
            try:
                tags = element.get('tags', {})

                if not tags.get('addr:housenumber') or not tags.get('addr:street'):
                    continue

                if element['type'] == 'node':
                    lat, lng = element['lat'], element['lon']
                elif 'center' in element:
                    lat, lng = element['center']['lat'], element['center']['lon']
                else:
                    continue

                address_parts = []
                if 'addr:street' in tags:
                    address_parts.append(tags['addr:street'])
                if 'addr:housenumber' in tags:
                    address_parts.append(tags['addr:housenumber'])
                if 'addr:postcode' in tags:
                    address_parts.append(tags['addr:postcode'])
                if 'addr:city' in tags:
                    address_parts.append(tags['addr:city'])

                address = ', '.join(filter(None, address_parts))

                buildings.append({
                    'address': address,
                    'lat': lat,
                    'lng': lng,
                    'osm_id': element['id'],
                    'building_type': tags.get('building', 'N/A'),
                    'levels': tags.get('building:levels', 'N/A'),
                })

            except Exception as e:
                logging.debug(f"⚠️ Ошибка парсинга здания: {e}")
                continue

        logging.info(f"✅ Найдено {len(buildings)} жилых домов")
        return buildings


# ============================================================================
# МЕНЕДЖЕР ДОМОВ
# ============================================================================
class HousesManager:
    """Управление файлом с адресами домов"""

    def __init__(self):
        self.output_dir = Path(Config.OUTPUT_DIR)
        self.output_dir.mkdir(exist_ok=True)
        self.houses_file = self.output_dir / Config.HOUSES_FILE
        self.existing_addresses: Set[str] = set()

        with open(self.houses_file, 'w', encoding='utf-8') as f:
            f.write("Date | Country | City | Address | Latitude | Longitude | OSM_ID | Building_Type | Levels\n")
            f.write("=" * 100 + "\n")

        logging.info("📂 Файл с домами очищен при запуске")

    def add_house(self, country: str, city: str, data: Dict[str, Any]) -> bool:
        """Добавляет адрес дома в файл"""
        try:
            address = data['address']
            if not address or address in self.existing_addresses:
                logging.debug(f"❌ Дом пустой или существует: {address[:50]}...")
                return False

            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            clean_address = address.replace('|', ',')
            line = f"{timestamp} | {country} | {city} | {clean_address} | {data['lat']:.6f} | {data['lng']:.6f} | {data['osm_id']} | {data['building_type']} | {data['levels']}\n"

            with open(self.houses_file, 'a', encoding='utf-8') as f:
                f.write(line)

            self.existing_addresses.add(address)
            logging.info(f"🏠 Дом сохранен: {clean_address[:60]}...")
            return True
        except Exception as e:
            logging.error(f"❌ Ошибка записи дома: {e}")
            return False

    def get_stats(self) -> Dict[str, int]:
        """Возвращает статистику по домам"""
        try:
            with open(self.houses_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                return {"total": max(0, len(lines) - 2)}
        except:
            return {"total": 0}


# ============================================================================
# ГЛАВНЫЙ ГЕНЕРАТОР
# ============================================================================
class HouseOSMGenerator:
    """Генератор адресов жилых домов через OpenStreetMap"""

    def __init__(self):
        logging.info("=" * 70)
        logging.info("🚀 ИНИЦИАЛИЗАЦИЯ OSM ГЕНЕРАТОРА (БЕЗ API-КЛЮЧЕЙ)")
        logging.info("=" * 70)

        self.client = OSMAPIClient()
        self.houses_manager = HousesManager()

        logging.info("✅ Генератор готов")
        logging.info("⚠️ Помните: 1 запрос/сек к OSM API!")

    def generate_houses(self, country_key: str, city_key: str, count: int = 10) -> bool:
        """Генерирует адреса жилых домов в выбранном городе"""
        country = Config.COUNTRIES.get(country_key.lower())
        if not country:
            logging.error(f"❌ Страна '{country_key}' не найдена")
            return False

        city = country.cities.get(city_key.lower())
        if not city:
            logging.error(f"❌ Город '{city_key}' не найден")
            return False

        print(f"\n{'=' * 70}")
        print(f"🏠 ПОИСК ЖИЛЫХ ДОМОВ В: {country.name} → {city.name.upper()}")
        print(f"Метод: OpenStreetMap Overpass API")
        print(f"{'=' * 70}")
        logging.info(f"Запрошено {count} домов для {city.name}")

        buildings = self.client.get_residential_buildings(city, limit=count * 2)

        if not buildings:
            print(f"\n❌ В городе {city.name} не найдено жилых домов с адресами")
            return False

        random.shuffle(buildings)

        print(f"\n🎯 Сохранение найденных домов...")

        generated = 0
        with tqdm(total=min(count, len(buildings)), desc="Сохранено", unit="дом") as pbar:
            for building in buildings:
                if generated >= count:
                    break

                if not building['address']:
                    continue

                if self.houses_manager.add_house(country.name, city.name, building):
                    generated += 1
                    pbar.update(1)

                time.sleep(0.1)

        print(f"\n📊 Статистика запросов: {self.client.request_count} (ошибок: {self.client.error_count})")

        if generated > 0:
            print(f"\n✅ Успешно найдено и сохранено {generated} жилых домов")
            logging.info(f"Генерация завершена: {generated} домов")
            print(f"📂 Файл: {self.houses_manager.houses_file.absolute()}")
            return True
        else:
            print(f"\n❌ Не удалось сохранить дома (все дубликаты или пустые)")
            return False


# ============================================================================
# UI (ОБНОВЛЕН - ДВУХЭТАПНЫЙ ВЫБОР)
# ============================================================================
class UIManager:
    def __init__(self, generator: HouseOSMGenerator):
        self.generator = generator

    def display_countries(self) -> None:
        print("\n" + "=" * 70)
        print("🌍 ДОСТУПНЫЕ СТРАНЫ:")
        print("=" * 70)

        countries = sorted(Config.COUNTRIES.items())
        for i, (key, country) in enumerate(countries, 1):
            print(f"{i:2d}. {country.name} ({len(country.cities)} городов)")

        print(f"\n 0. Выход | stats - статистика")
        print("=" * 70)

    def display_cities(self, country_key: str) -> None:
        country = Config.COUNTRIES.get(country_key)
        if not country:
            return

        print("\n" + "=" * 70)
        print(f"🏙️ ГОРОДА В {country.name.upper()}:")
        print("=" * 70)

        cities = sorted(country.cities.items())
        for i, (key, city) in enumerate(cities, 1):
            print(f"{i:2d}. {city.name}")

        print(f"\n 0. Назад | back - вернуться к выбору страны")
        print("=" * 70)

    def show_stats(self) -> None:
        stats = self.generator.houses_manager.get_stats()
        print("\n" + "=" * 70)
        print("📊 СТАТИСТИКА ДОМОВ (OSM):")
        print("=" * 70)
        print(f"🏠 Всего сохранено: {stats['total']}")
        print(f"📄 Файл: {self.generator.houses_manager.houses_file.absolute()}")
        print("=" * 70)

    def run(self) -> None:
        current_country = None

        while True:
            if not current_country:
                self.display_countries()
                choice = input("\n🌍 Выберите страну: ").strip().lower()

                if choice in ['0', 'exit', 'quit', 'q', 'выход']:
                    print("\n👋 До свидания!")
                    break

                if choice == 'stats':
                    self.show_stats()
                    input("\nНажмите Enter...")
                    continue

                if choice.isdigit():
                    countries = sorted(Config.COUNTRIES.keys())
                    country_index = int(choice) - 1

                    if 0 <= country_index < len(countries):
                        current_country = countries[country_index]
                        continue

                print("\n❌ Неверный выбор. Попробуйте снова.")
            else:
                self.display_cities(current_country)
                choice = input(f"\n🏙️ Выберите город ({Config.COUNTRIES[current_country].name}): ").strip().lower()

                if choice in ['0', 'back', 'назад']:
                    current_country = None
                    continue

                if choice.isdigit():
                    country = Config.COUNTRIES[current_country]
                    cities = sorted(country.cities.keys())
                    city_index = int(choice) - 1

                    if 0 <= city_index < len(cities):
                        city_key = cities[city_index]

                        try:
                            count = input("\n🔢 Сколько адресов? [10]: ").strip()
                            count = int(count) if count else 10
                            if count < 1 or count > 100:
                                print("⚠️ Диапазон: 1-100")
                                count = 10
                        except:
                            count = 10

                        success = self.generator.generate_houses(current_country, city_key, count=count)

                        if not success:
                            print("\n❌ Проблемы с поиском. Проверьте логи.")

                        input("\nНажмите Enter для продолжения...")
                        continue

                print("\n❌ Неверный выбор. Попробуйте снова.")


# ============================================================================
# НАСТРОЙКА ЛОГИРОВАНИЯ
# ============================================================================
def setup_logging():
    """Настройка логирования"""
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / Config.LOG_FILE

    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    file_handler = logging.FileHandler(log_path, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)

    logging.info("=" * 70)
    logging.info("ЛОГИРОВАНИЕ НАСТРОЕНО")
    logging.info(f"Файл: {log_path.absolute()}")
    logging.info("=" * 70)


# ============================================================================
# ТОЧКА ВХОДА
# ============================================================================
def main() -> None:
    """Главная функция"""
    print("\n" + "=" * 70)
    print("🏠 OSM ГЕНЕРАТОР ЖИЛЫХ ДОМОВ v2.3 (БЕЗ API-КЛЮЧЕЙ)")
    print("=" * 70)

    try:
        import requests
        from tqdm import tqdm
        print("✅ Все библиотеки установлены")
    except ImportError as e:
        print(f"❌ ОШИБКА: {e}")
        print("\n📦 Установите: pip install requests tqdm")
        sys.exit(1)

    setup_logging()

    print("\n🆓 ВНИМАНИЕ:")
    print("Используется OpenStreetMap API (бесплатно)")
    print("Метод: Overpass API (building=residential)")
    print("Политика: 1 запрос/сек (автоматически)")

    try:
        generator = HouseOSMGenerator()
        print("✅ Генератор создан")
    except Exception as e:
        logging.error(f"Ошибка инициализации: {e}", exc_info=True)
        print(f"❌ Критическая ошибка: {e}")
        sys.exit(1)

    ui = UIManager(generator)

    print("\n" + "=" * 70)
    print("✅ ВСЕ СИСТЕМЫ ГОТОВЫ!")
    print("💡 Качество OSM данных различается по регионам")
    print("💡 Рекомендуется начать с 10-20 домов")
    print("=" * 70)

    ui.run()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n👋 Программа завершена пользователем")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Критическая ошибка: {e}")
        logging.critical(f"Ошибка: {e}", exc_info=True)
        sys.exit(1)