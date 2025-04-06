# config_manager.py

import json
import os
import logging
from typing import Dict, Any, Optional, Tuple, List # Для type hints
from pathlib import Path

log = logging.getLogger(__name__)

def get_default_settings() -> Dict[str, Any]:
    """
    Возвращает словарь с настройками по умолчанию для приложения.
    """
    # Получаем путь к папке "Загрузки" пользователя
    try:
        downloads_path = str(Path.home() / "Downloads")
        default_input = downloads_path
        default_output = os.path.join(downloads_path, "out")
        default_backup = os.path.join(downloads_path, "backup")
    except:
        default_input = ""
        default_output = ""
        default_backup = ""

    defaults = {
        # --- Пути ---
        "paths": {
            "input_folder_path": default_input,     # Путь к папке источника
            "output_folder_path": default_output,    # Путь для результатов (режим отдельных файлов)
            "backup_folder_path": default_backup,    # Путь для бэкапов (режим отдельных файлов)
            "output_filename": "collage.jpg"         # Имя файла коллажа (режим коллажа)
        },

        # --- Общие настройки обработки (применяются в обоих режимах к отдельным файлам) ---
        "preprocessing": {
            "enable_preresize": False,      # Включить предв. ресайз?
            "preresize_width": 2500,        # Макс. ширина предв. ресайза (0=выкл)
            "preresize_height": 2500,       # Макс. высота предв. ресайза (0=выкл)
        },
        "whitening": {
            "enable_whitening": True,           # Включить отбеливание?
            "whitening_cancel_threshold": 550,  # Порог отмены (0-765)
        },
        "background_crop": {
            "enable_bg_crop": False,        # Включить удаление фона и обрезку?
            "white_tolerance": 0,           # Допуск белого (0-255)
            "crop_symmetric_absolute": False, # Абсолютная симметрия обрезки?
            "crop_symmetric_axes": False,   # Симметрия по осям (если absolute=False)?
        },
        "padding": {
            "enable_padding": False,        # Включить добавление полей?
            "padding_percent": 5.0,         # Процент полей (0=выкл)
            "perimeter_margin": 0,          # Проверка периметра для полей (пикс, 0=выкл)
            "allow_expansion": True,        # Разрешить полям увеличивать размер?
        },

        # --- Настройки режима "Обработка отдельных файлов" ---
        "individual_mode": {
            "article_name": "",             # Артикул для переименования (пусто=выкл)
            "delete_originals": False,      # Удалять оригиналы?
            "force_aspect_ratio": None,     # Принуд. соотношение (None или [W, H], напр., [1, 1])
            "max_output_width": 1500,       # Макс. ширина конечного файла (0=выкл)
            "max_output_height": 1500,      # Макс. высота конечного файла (0=выкл)
            "final_exact_width": 0,         # Точная ширина холста (0=выкл)
            "final_exact_height": 0,        # Точная высота холста (0=выкл)
            "output_format": "jpg",         # Формат ('jpg' или 'png')
            "jpg_background_color": [255, 255, 255], # Фон JPG [R, G, B]
            "jpeg_quality": 95,             # Качество JPG (1-100)
        },

        # --- Настройки режима "Создание коллажа" ---
        "collage_mode": {
            "proportional_placement": False,# Включить пропорц. масштабирование?
            "placement_ratios": [1.0],      # Коэффициенты масштаба [1.0, 0.8, 1.0]
            "forced_cols": 0,               # Кол-во столбцов (0=авто)
            "spacing_percent": 2.0,         # Отступ между изображениями (%)
            "force_collage_aspect_ratio": None, # Соотношение для коллажа (None или [W, H])
            "max_collage_width": 1500,      # Макс. ширина коллажа (0=выкл)
            "max_collage_height": 1500,     # Макс. высота коллажа (0=выкл)
            "final_collage_exact_width": 0, # Точная ширина холста коллажа (0=выкл)
            "final_collage_exact_height": 0,# Точная высота холста коллажа (0=выкл)
            "output_format": "jpg",         # Формат коллажа ('jpg' или 'png')
            "jpg_background_color": [255, 255, 255], # Фон коллажа JPG [R, G, B]
            "jpeg_quality": 95,             # Качество коллажа JPG (1-100)
        }
    }
    # Важно: JSON не поддерживает кортежи, поэтому цвета и соотношения сторон
    # лучше хранить как списки [R, G, B] или [W, H].
    # None остается None.
    return defaults

def load_settings(filepath: str) -> Dict[str, Any]:
    """
    Загружает настройки из JSON-файла.
    Если файл не найден или поврежден, возвращает настройки по умолчанию.
    Объединяет загруженные настройки с дефолтными, чтобы гарантировать наличие всех ключей.
    """
    defaults = get_default_settings()
    if not os.path.exists(filepath):
        log.warning(f"Settings file not found: '{filepath}'. Using default settings.")
        return defaults

    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            loaded_settings = json.load(f)
            log.info(f"Settings loaded successfully from: '{filepath}'")

            # --- Объединение с дефолтными ---
            # Это гарантирует, что все ключи из defaults будут присутствовать,
            # даже если их нет в файле (например, после обновления).
            # Значения из loaded_settings перезапишут значения из defaults.
            # Используем рекурсивное обновление для вложенных словарей.
            def update_recursive(d, u):
                for k, v in u.items():
                    if isinstance(v, dict):
                        d[k] = update_recursive(d.get(k, {}), v)
                    else:
                        # Преобразуем списки обратно в кортежи для цветов/соотношений, если нужно
                        # (Хотя, возможно, удобнее работать со списками везде)
                        # if k in ["jpg_background_color", "force_aspect_ratio", "force_collage_aspect_ratio"] and isinstance(v, list):
                        #    d[k] = tuple(v)
                        # else:
                        #    d[k] = v
                        d[k] = v # Оставляем как загрузилось (скорее всего списки)
                return d

            merged_settings = update_recursive(defaults.copy(), loaded_settings)
            return merged_settings

    except json.JSONDecodeError as e:
        log.error(f"Error decoding JSON from settings file '{filepath}': {e}. Using default settings.", exc_info=True)
        return defaults
    except Exception as e:
        log.error(f"Failed to load settings from '{filepath}': {e}. Using default settings.", exc_info=True)
        return defaults

def save_settings(settings_dict: Dict[str, Any], filepath: str) -> bool:
    """
    Сохраняет переданный словарь настроек в JSON-файл.
    Возвращает True при успехе, False при ошибке.
    """
    try:
        # Создаем директорию, если она не существует
        dirpath = os.path.dirname(filepath)
        if dirpath and not os.path.exists(dirpath):
            os.makedirs(dirpath)
            log.info(f"Created directory for settings file: '{dirpath}'")

        with open(filepath, 'w', encoding='utf-8') as f:
            # Используем indent для читаемости файла
            json.dump(settings_dict, f, indent=4, ensure_ascii=False)
        log.info(f"Settings saved successfully to: '{filepath}'")
        return True
    except Exception as e:
        log.error(f"Failed to save settings to '{filepath}': {e}", exc_info=True)
        return False

def save_settings_preset(settings: Dict, preset_name: str) -> bool:
    """Сохраняет набор настроек с указанным именем."""
    try:
        presets_dir = "settings_presets"
        if not os.path.exists(presets_dir):
            os.makedirs(presets_dir)
        
        preset_file = os.path.join(presets_dir, f"{preset_name}.json")
        with open(preset_file, 'w', encoding='utf-8') as f:
            json.dump(settings, f, indent=4, ensure_ascii=False)
        return True
    except Exception as e:
        logging.error(f"Error saving settings preset: {e}")
        return False

def load_settings_preset(preset_name: str) -> Optional[Dict]:
    """Загружает набор настроек по имени."""
    try:
        preset_file = os.path.join("settings_presets", f"{preset_name}.json")
        if not os.path.exists(preset_file):
            return None
        
        with open(preset_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logging.error(f"Error loading settings preset: {e}")
        return None

def get_available_presets() -> List[str]:
    """Возвращает список доступных наборов настроек."""
    try:
        presets_dir = "settings_presets"
        if not os.path.exists(presets_dir):
            return []
        
        presets = [f.replace('.json', '') for f in os.listdir(presets_dir) 
                  if f.endswith('.json')]
        return sorted(presets)
    except Exception as e:
        logging.error(f"Error getting presets list: {e}")
        return []

def delete_settings_preset(preset_name: str) -> bool:
    """Удаляет набор настроек по имени."""
    try:
        preset_file = os.path.join("settings_presets", f"{preset_name}.json")
        if os.path.exists(preset_file):
            os.remove(preset_file)
            return True
        return False
    except Exception as e:
        logging.error(f"Error deleting settings preset: {e}")
        return False

def get_default_preset_settings() -> Dict:
    """Возвращает настройки по умолчанию для нового набора."""
    return {
        "processing_mode_selector": "Обработка отдельных файлов",
        "paths": {
            "input_folder_path": "",
            "output_folder_path": "",
            "backup_folder_path": "",
            "output_filename": "collage.jpg"
        },
        "preprocessing": {
            "enable_preresize": False,
            "preresize_width": 2500,
            "preresize_height": 2500
        },
        "whitening": {
            "enable_whitening": True,
            "whitening_cancel_threshold": 550
        },
        "background_crop": {
            "enable_bg_crop": False,
            "white_tolerance": 0,
            "crop_symmetric_absolute": False,
            "crop_symmetric_axes": False
        },
        "padding": {
            "enable_padding": False,
            "padding_percent": 5.0,
            "perimeter_margin": 0,
            "allow_expansion": True
        },
        "individual_mode": {
            "article_name": "",
            "delete_originals": False,
            "force_aspect_ratio": None,
            "max_output_width": 1500,
            "max_output_height": 1500,
            "final_exact_width": 0,
            "final_exact_height": 0,
            "output_format": "jpg",
            "jpeg_quality": 95
        },
        "collage_mode": {
            "forced_cols": 0,
            "spacing_percent": 2.0,
            "proportional_placement": False,
            "placement_ratios": [1.0],
            "force_collage_aspect_ratio": None,
            "max_collage_width": 1500,
            "max_collage_height": 1500,
            "final_collage_exact_width": 0,
            "final_collage_exact_height": 0,
            "output_format": "jpg",
            "jpeg_quality": 95
        }
    }

def create_default_preset() -> bool:
    """Создает набор настроек по умолчанию, если он еще не существует."""
    try:
        presets_dir = "settings_presets"
        if not os.path.exists(presets_dir):
            os.makedirs(presets_dir)
        
        default_preset_file = os.path.join(presets_dir, "Настройки по умолчанию.json")
        if not os.path.exists(default_preset_file):
            with open(default_preset_file, 'w', encoding='utf-8') as f:
                json.dump(get_default_preset_settings(), f, indent=4, ensure_ascii=False)
            return True
        return False
    except Exception as e:
        logging.error(f"Error creating default preset: {e}")
        return False

def rename_settings_preset(old_name: str, new_name: str) -> bool:
    """Переименовывает набор настроек."""
    try:
        if old_name == "Настройки по умолчанию":
            return False
            
        old_file = os.path.join("settings_presets", f"{old_name}.json")
        new_file = os.path.join("settings_presets", f"{new_name}.json")
        
        if not os.path.exists(old_file) or os.path.exists(new_file):
            return False
            
        # Загружаем настройки из старого файла
        with open(old_file, 'r', encoding='utf-8') as f:
            settings = json.load(f)
            
        # Сохраняем в новый файл
        with open(new_file, 'w', encoding='utf-8') as f:
            json.dump(settings, f, indent=4, ensure_ascii=False)
            
        # Удаляем старый файл
        os.remove(old_file)
        return True
    except Exception as e:
        logging.error(f"Error renaming settings preset: {e}")
        return False

def delete_all_custom_presets() -> Optional[int]:
    """Удаляет все файлы пресетов из папки 'settings_presets', кроме 'Настройки по умолчанию.json'.
    Возвращает количество удаленных файлов или None в случае ошибки.
    """
    presets_dir = "settings_presets"
    default_preset_filename = "Настройки по умолчанию.json"
    deleted_count = 0
    try:
        if not os.path.exists(presets_dir):
            log.info("Presets directory doesn't exist, nothing to delete.")
            return 0 # Папки нет, значит 0 удалено
        
        for filename in os.listdir(presets_dir):
            if filename.endswith('.json') and filename != default_preset_filename:
                file_path = os.path.join(presets_dir, filename)
                try:
                    os.remove(file_path)
                    log.info(f"Deleted preset file: {file_path}")
                    deleted_count += 1
                except Exception as e_inner:
                    log.error(f"Failed to delete preset file '{file_path}': {e_inner}")
                    # Продолжаем удалять остальные, но вернем None в конце
                    return None # Если хотя бы один файл удалить не удалось, считаем операцию неуспешной
        
        log.info(f"Successfully deleted {deleted_count} custom preset files.")
        return deleted_count

    except Exception as e:
        log.error(f"Error deleting custom presets: {e}", exc_info=True)
        return None

# Пример использования (не будет выполняться при импорте)
if __name__ == "__main__":
    # Настройка базового логирования для теста
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    log.info("Testing config_manager...")
    settings_file = "test_settings.json"

    # 1. Получить дефолтные
    defaults = get_default_settings()
    print("\n--- Default Settings ---")
    # print(json.dumps(defaults, indent=4))

    # 2. Попробовать загрузить (файла еще нет)
    print(f"\n--- Loading from non-existent file ({settings_file}) ---")
    loaded1 = load_settings(settings_file)
    # print(json.dumps(loaded1, indent=4))
    assert loaded1 == defaults # Должны вернуться дефолтные

    # 3. Изменить что-то и сохранить
    print(f"\n--- Modifying and saving to {settings_file} ---")
    loaded1["paths"]["input_folder_path"] = "/new/input/path"
    loaded1["whitening"]["enable_whitening"] = False
    loaded1["collage_mode"]["jpeg_quality"] = 85
    save_successful = save_settings(loaded1, settings_file)
    assert save_successful

    # 4. Загрузить из сохраненного файла
    print(f"\n--- Loading from existing file ({settings_file}) ---")
    loaded2 = load_settings(settings_file)
    # print(json.dumps(loaded2, indent=4))
    assert loaded2["paths"]["input_folder_path"] == "/new/input/path"
    assert loaded2["whitening"]["enable_whitening"] is False
    assert loaded2["collage_mode"]["jpeg_quality"] == 85
    assert "individual_mode" in loaded2 # Проверка, что остальные ключи тоже есть

    # 5. Проверка сброса (получение дефолтных)
    print("\n--- Getting defaults again (for reset simulation) ---")
    reset_settings = get_default_settings()
    assert reset_settings["whitening"]["enable_whitening"] is True # Убедимся, что вернулись к дефолту

    # 6. Тест поврежденного файла (если возможно создать вручную)
    # try:
    #     with open("corrupted_settings.json", "w") as f: f.write("{invalid json")
    #     print("\n--- Loading from corrupted file ---")
    #     loaded3 = load_settings("corrupted_settings.json")
    #     assert loaded3 == defaults
    # finally:
    #     if os.path.exists("corrupted_settings.json"): os.remove("corrupted_settings.json")

    # Очистка тестового файла
    if os.path.exists(settings_file):
        os.remove(settings_file)
        log.info(f"Cleaned up test file: {settings_file}")

    log.info("config_manager tests finished.")