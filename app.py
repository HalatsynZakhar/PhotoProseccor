# app.py

# Начинаем выводить логи

# --- БЛОК ПРОВЕРКИ И УСТАНОВКИ ЗАВИСИМОСТЕЙ ---
import sys
import subprocess
import importlib
import os
import time

print("="*50); print("--- Проверка и установка необходимых библиотек ---"); #... (весь блок)
# --- Инициализация installed_packages_info ---
installed_packages_info = []
for package_name in ["streamlit", "Pillow", "natsort"]:
    module_map = { "streamlit": "streamlit", "Pillow": "PIL", "natsort": "natsort" }
    module_name = module_map[package_name]
    try: importlib.import_module(module_name); print(f"[OK] {package_name} found."); installed_packages_info.append(f"{package_name} (OK)")
    except ImportError: print(f"[!] {package_name} not found. Installing..."); # ... (код установки) ...; installed_packages_info.append(f"{package_name} (Installed/Error)")
print("="*50); print("--- Проверка зависимостей завершена ---"); print("Статус пакетов:", ", ".join(installed_packages_info)); print("="*50)
needs_restart = any("(Installed" in s for s in installed_packages_info) # Проверяем, была ли установка
if needs_restart: print("\n[ВАЖНО] Были установлены новые библиотеки...")
# === КОНЕЦ БЛОКА ПРОВЕРКИ ===

# === Импорт основных библиотек ===
print("Загрузка основных модулей приложения...")
try:
    import streamlit as st
    from PIL import Image
    from io import StringIO
    import logging
    from typing import Dict, Any, Optional, Tuple, List
    import os
    import platform
    import subprocess
    import tempfile
    import json

    # Проверка наличия файлов модулей
    module_paths = {
        "config_manager.py": os.path.exists("config_manager.py"),
        "processing_workflows.py": os.path.exists("processing_workflows.py"),
        "image_utils.py": os.path.exists("image_utils.py")
    }
    
    import config_manager
    
    import processing_workflows
    
    print("Модули успешно загружены.")
except ImportError as e: 
    print(f"\n[!!! КРИТИЧЕСКАЯ ОШИБКА] Import Error: {e}"); sys.exit(1)
except Exception as e: 
    print(f"\n[!!! КРИТИЧЕСКАЯ ОШИБКА] App Import Error: {e}"); import traceback; traceback.print_exc(); sys.exit(1)

# --- Настройка логирования ---
log_stream = StringIO()
log_level = logging.DEBUG # <-- УСТАНОВИТЕ DEBUG ДЛЯ ОТЛАДКИ
logging.basicConfig(stream=log_stream, level=log_level, format='%(asctime)s - %(levelname)s - %(name)s - %(message)s', datefmt='%H:%M:%S')
log = logging.getLogger(__name__)
log.info("--- App script started, logger configured. ---") # Тестовое сообщение
log.info(f"Logging configured at level: {logging.getLevelName(log_level)}")

# --- Настройка страницы Streamlit ---
st.set_page_config(layout="wide", page_title="Обработчик Изображений")

# --- Функция для получения папки загрузки пользователя ---
def get_downloads_folder():
    """Возвращает путь к папке загрузки пользователя в зависимости от ОС"""
    # Возвращаем путь по умолчанию для пользователя
    return r"C:\Users\zakhar\Downloads"
    
    # Код ниже закомментирован, так как мы используем фиксированный путь
    """
    if platform.system() == "Windows":
        # Для Windows используем переменную окружения USERPROFILE
        user_profile = os.environ.get("USERPROFILE")
        if user_profile:
            downloads_path = os.path.join(user_profile, "Downloads")
            if os.path.exists(downloads_path):
                return downloads_path
    
    # Для других ОС или если не удалось определить папку загрузки
    return os.path.expanduser("~")
    """

# === Основной код приложения Streamlit ===

# --- Загрузка/Инициализация Настроек ---
CONFIG_FILE = "settings.json"
log.debug(f"Loading settings from {CONFIG_FILE}")
settings = config_manager.load_settings(CONFIG_FILE)

# Создаем набор настроек по умолчанию, если его нет
config_manager.create_default_preset()

# Инициализируем настройки в session_state при первом запуске
if 'current_settings' not in st.session_state:
    log.debug("Initializing current_settings in session_state.")
    st.session_state.current_settings = settings.copy()
    
    # Устанавливаем пути по умолчанию при первом запуске
    if 'paths' not in st.session_state.current_settings:
        st.session_state.current_settings['paths'] = {}
    
    # Устанавливаем путь к папке загрузки по умолчанию
    if not st.session_state.current_settings['paths'].get('input_folder_path'):
        st.session_state.current_settings['paths']['input_folder_path'] = r"C:\Users\zakhar\Downloads"
    
    # Устанавливаем пути для режима обработки отдельных файлов
    if not st.session_state.current_settings['paths'].get('output_folder_path'):
        st.session_state.current_settings['paths']['output_folder_path'] = r"C:\Users\zakhar\Downloads\out"
    
    if not st.session_state.current_settings['paths'].get('backup_folder_path'):
        st.session_state.current_settings['paths']['backup_folder_path'] = r"C:\Users\zakhar\Downloads\backup"
    
    # Устанавливаем имя файла коллажа по умолчанию
    if not st.session_state.current_settings['paths'].get('output_filename'):
        st.session_state.current_settings['paths']['output_filename'] = "collage.jpg"
    
    # Сохраняем обновленные настройки
    config_manager.save_settings(st.session_state.current_settings, CONFIG_FILE)
    log.debug("Default paths initialized and saved.")

# Инициализируем флаг для отслеживания изменений
if 'settings_changed' not in st.session_state:
    st.session_state.settings_changed = False

# Инициализируем текущий активный набор
if 'active_preset' not in st.session_state:
    st.session_state.active_preset = "Настройки по умолчанию"

# --- Вспомогательные функции ---
def get_setting(key_path: str, default: Any = None) -> Any:
    keys = key_path.split('.')
    value = st.session_state.current_settings
    try:
        for key in keys: value = value[key]
        if isinstance(value, (list, dict)): return value.copy()
        return value
    except (KeyError, TypeError):
        if isinstance(default, (list, dict)): return default.copy()
        return default

def set_setting(key_path: str, value: Any):
    keys = key_path.split('.')
    d = st.session_state.current_settings
    try:
        for key in keys[:-1]:
            if key not in d or not isinstance(d[key], dict): d[key] = {}
            d = d[key]
        d[keys[-1]] = value.copy() if isinstance(value, (list, dict)) else value
        st.session_state.settings_changed = True  # Отмечаем, что настройки изменились
    except TypeError as e: log.error(f"Error setting '{key_path}': {e}")

# === ОСНОВНАЯ ОБЛАСТЬ ПРИЛОЖЕНИЯ ===
# --- UI: Боковая Панель ---
with st.sidebar:
    # === Режим работы ===
    st.header("🎯 Режим работы")

    # Проверяем, есть ли сохраненный режим обработки
    if "saved_processing_mode" in st.session_state:
        # Если есть сохраненный режим, используем его для следующего рендера
        initial_mode = st.session_state.saved_processing_mode
        # Удаляем сохраненный режим, чтобы он не использовался повторно
        del st.session_state.saved_processing_mode
    else:
        # Если нет сохраненного режима, используем текущий или значение по умолчанию
        initial_mode = st.session_state.get("processing_mode_selector_widget", "Обработка отдельных файлов")

    # Создаем виджет выбора режима
    processing_mode = st.selectbox(
        "Выберите режим обработки:",
        ["Обработка отдельных файлов", "Создание коллажей"],
        key="processing_mode_selector_widget",
        index=0 if initial_mode == "Обработка отдельных файлов" else 1
    )
    st.caption("Режим обработки")
    st.divider()

    # === Управление наборами ===
    st.header("📦 Управление наборами")
    available_presets = config_manager.get_available_presets()
    if not available_presets:
        available_presets = ["Настройки по умолчанию"]
    
    # Генерация имени по умолчанию для нового набора
    def get_default_preset_name():
        existing_presets = config_manager.get_available_presets()
        counter = 1
        while f"Набор {counter}" in existing_presets:
            counter += 1
        return f"Набор {counter}"
    
    # Создаем колонки для выбора пресета и кнопки удаления
    preset_col1, preset_col2 = st.columns([4, 1])
    with preset_col1:
        selected_preset = st.selectbox("Активный набор настроек", available_presets, 
                                      index=available_presets.index(st.session_state.active_preset) if st.session_state.active_preset in available_presets else 0,
                                      key="preset_selector")
    with preset_col2:
        st.write("") # Добавляем отступ сверху
        can_delete = selected_preset != "Настройки по умолчанию"
        if can_delete:
            if st.button("🗑️ Удалить", key="delete_preset_button", help=f"Удалить набор '{selected_preset}'"):
                if config_manager.delete_settings_preset(selected_preset):
                    if st.session_state.active_preset == selected_preset:
                        st.session_state.active_preset = "Настройки по умолчанию"
                        default_settings = config_manager.load_settings_preset("Настройки по умолчанию")
                        if default_settings:
                            st.session_state.current_settings = default_settings
                    st.success(f"Набор '{selected_preset}' удален")
                    st.rerun()
                else:
                    st.error("Ошибка удаления набора")
        else:
            st.button("🗑️ Удалить", key="delete_preset_button_disabled", disabled=True, 
                     help="Нельзя удалить набор по умолчанию")
    
    st.caption("Активный набор настроек")
    
    # Загрузка настроек при смене набора
    if selected_preset != st.session_state.active_preset:
        preset_settings = config_manager.load_settings_preset(selected_preset)
        if preset_settings:
            st.session_state.current_settings = preset_settings
            st.session_state.active_preset = selected_preset
            # Сохраняем режим в отдельной переменной для следующего рендера
            if "processing_mode_selector" in preset_settings:
                st.session_state.saved_processing_mode = preset_settings["processing_mode_selector"]
            st.session_state.settings_changed = True
            st.success(f"Загружен набор '{selected_preset}'")
            st.rerun()
        else:
            st.error(f"Ошибка загрузки набора '{selected_preset}'")
    
    # Переименование набора
    rename_col1, rename_col2 = st.columns([4, 1]) # Возвращаем 4:1, как у selectbox'а и кнопки удаления
    with rename_col1:
        new_name = st.text_input("Переименовать набор:", 
                                value=selected_preset, 
                                key="rename_preset",
                                disabled=selected_preset == "Настройки по умолчанию")
    with rename_col2:
        st.write("") # Добавляем отступ сверху
        if st.button("✏️ Переим.", 
                    disabled=selected_preset == "Настройки по умолчанию",
                    help="Переименовать текущий набор настроек"):
            if config_manager.rename_settings_preset(selected_preset, new_name):
                st.session_state.active_preset = new_name
                st.success(f"Набор переименован в '{new_name}'")
                st.rerun()
    
    # Создание нового набора
    create_col1, create_col2 = st.columns([4, 1]) # Возвращаем 4:1
    with create_col1:
        default_name = get_default_preset_name()
        new_preset_name = st.text_input("Название нового набора:", 
                                       key="new_preset_name",
                                       placeholder=default_name)
    with create_col2:
        st.write("") # Добавляем отступ сверху
        if st.button("➕ Создать", 
                    help="Создать новый набор настроек"):
            # Если поле пустое, используем имя по умолчанию
            preset_name = new_preset_name if new_preset_name else default_name
            if config_manager.save_settings_preset(st.session_state.current_settings, preset_name):
                st.session_state.active_preset = preset_name
                st.success(f"Создан новый набор '{preset_name}'")
                st.rerun()
            else:
                st.error("Ошибка создания набора")
    
    st.divider()

    # === Новая кнопка: Сброс всех профилей ===
    if 'reset_profiles_confirmation_pending' not in st.session_state:
        st.session_state.reset_profiles_confirmation_pending = False

    if st.button("🗑️ Сбросить все профили", key="reset_all_profiles_button", help="Удалить все пользовательские наборы настроек", disabled=st.session_state.reset_profiles_confirmation_pending):
        st.warning("Вы уверены, что хотите удалить ВСЕ пользовательские профили настроек? Останется только профиль 'Настройки по умолчанию'. Это действие нельзя отменить.", icon="⚠️")
        st.session_state.reset_profiles_confirmation_pending = True
        st.rerun()

    if st.session_state.reset_profiles_confirmation_pending:
        prof_confirm_col1, prof_confirm_col2 = st.columns(2)
        with prof_confirm_col1:
            if st.button("Да, удалить профили", key="confirm_reset_profiles", type="primary"):
                try:
                    deleted_count = config_manager.delete_all_custom_presets()
                    if deleted_count is not None:
                         st.success(f"Удалено пользовательских профилей: {deleted_count}. Активным установлен профиль 'Настройки по умолчанию'.")
                         # Переключаемся на дефолтный пресет
                         default_settings = config_manager.load_settings_preset("Настройки по умолчанию")
                         if default_settings:
                             st.session_state.current_settings = default_settings
                         st.session_state.active_preset = "Настройки по умолчанию"
                         st.session_state.settings_changed = True # Отмечаем для сохранения основного файла
                    else:
                         st.error("Ошибка при удалении профилей.")
                    
                    st.session_state.reset_profiles_confirmation_pending = False
                    st.rerun()

                except Exception as e:
                    st.error(f"Ошибка при удалении профилей: {str(e)}")
                    st.session_state.reset_profiles_confirmation_pending = False
                    st.rerun()
        with prof_confirm_col2:
             if st.button("Отмена", key="cancel_reset_profiles"):
                st.info("Удаление профилей отменено.")
                st.session_state.reset_profiles_confirmation_pending = False
                st.rerun()

    st.divider()

    # === Пути ===
    st.header("📂 Пути")
    
    # Получаем путь к папке загрузки для плейсхолдера
    downloads_folder = get_downloads_folder()
    
    # --- Папка с исходными файлами ---
    st.write("Папка с исходными файлами:")
    input_path = st.text_input(
        "Путь к исходным файлам",
        value=get_setting('paths.input_folder_path', ''),
        key='path_input_sidebar',
        placeholder=downloads_folder,
        label_visibility="collapsed"
    )
    set_setting('paths.input_folder_path', input_path)
    # Проверка пути
    if input_path:
        abs_input_path = os.path.abspath(input_path)
        if os.path.isdir(abs_input_path):
            st.caption(f"✅ Папка найдена: {abs_input_path}", unsafe_allow_html=True)
        else:
            st.caption(f"❌ Папка не найдена: {abs_input_path}", unsafe_allow_html=True)
    else:
        st.caption("ℹ️ Путь не указан.", unsafe_allow_html=True)


    if processing_mode == "Обработка отдельных файлов":
        # --- Папка для результатов ---
        st.write("Папка для результатов:")
        output_path = st.text_input(
            "Путь для результатов",
            value=get_setting('paths.output_folder_path', ''),
            key='path_output_ind_sidebar',
            placeholder=os.path.join(downloads_folder, "out"),
            label_visibility="collapsed"
        )
        set_setting('paths.output_folder_path', output_path)
        # Проверка пути
        if output_path:
            abs_output_path = os.path.abspath(output_path)
            # Для папки вывода не обязательно проверять существование, 
            # но можно предупредить, если указан файл
            if os.path.exists(abs_output_path) and not os.path.isdir(abs_output_path):
                 st.caption(f"❌ Указан файл, а не папка: {abs_output_path}", unsafe_allow_html=True)
            # Можно добавить код для создания папки, если ее нет, при старте обработки
            else: # Если путь не существует или это папка
                 st.caption(f"ℹ️ Путь для сохранения: {abs_output_path}", unsafe_allow_html=True)
        else:
            st.caption("ℹ️ Путь не указан.", unsafe_allow_html=True)
        
        # --- Папка для бэкапов ---
        st.write("Папка для бэкапов (пусто = выкл):")
        backup_path = st.text_input(
            "Путь для бэкапов",
            value=get_setting('paths.backup_folder_path', ''),
            key='path_backup_ind_sidebar',
            placeholder=os.path.join(downloads_folder, "backup"),
            label_visibility="collapsed"
        )
        set_setting('paths.backup_folder_path', backup_path)
        # Проверка пути
        if backup_path:
            abs_backup_path = os.path.abspath(backup_path)
            if os.path.exists(abs_backup_path) and not os.path.isdir(abs_backup_path):
                 st.caption(f"❌ Указан файл, а не папка: {abs_backup_path}", unsafe_allow_html=True)
            else:
                 st.caption(f"ℹ️ Путь для бэкапов: {abs_backup_path}", unsafe_allow_html=True)
        else:
            st.caption("ℹ️ Бэкап отключен.", unsafe_allow_html=True)
            
    else: # Режим создания коллажа
        # --- Имя файла коллажа ---
        st.write("Имя файла коллажа (в папке источника):")
        collage_filename = st.text_input(
            "Имя файла коллажа", 
            value=get_setting('paths.output_filename', 'collage.jpg'), 
            key='path_output_coll_sidebar',
            label_visibility="collapsed"
        )
        set_setting('paths.output_filename', collage_filename)
        if collage_filename:
            # Проверка имени файла (базовая)
            if os.path.sep in collage_filename or collage_filename in (".", ".."):
                 st.caption(f"❌ Некорректное имя файла.", unsafe_allow_html=True)
            else:
                 st.caption(f"ℹ️ Имя файла: {collage_filename}", unsafe_allow_html=True)
        else:
             st.caption(f"❌ Имя файла не указано.", unsafe_allow_html=True)
    
    # Кнопка сброса путей
    if st.button("🔄 Сбросить пути", key="reset_paths", help="Сбросить пути к настройкам по умолчанию"):
        # Используем дефолтные настройки из config_manager
        default_settings_full = config_manager.get_default_settings()
        if default_settings_full and "paths" in default_settings_full:
            default_paths = default_settings_full["paths"]
            # Устанавливаем каждый путь из дефолтных настроек как ТЕКУЩЕЕ ЗНАЧЕНИЕ
            set_setting('paths.input_folder_path', default_paths.get('input_folder_path', ''))
            set_setting('paths.output_folder_path', default_paths.get('output_folder_path', ''))
            set_setting('paths.backup_folder_path', default_paths.get('backup_folder_path', ''))
            set_setting('paths.output_filename', default_paths.get('output_filename', 'collage.jpg'))
            st.session_state.settings_changed = True # Убедимся, что изменения отмечены для сохранения
            st.success("Пути сброшены к значениям по умолчанию!")
            st.rerun() # Перезапуск для отображения новых значений в полях
        else:
            st.error("Не удалось загрузить пути по умолчанию из config_manager.")
    
    # === Кнопка сброса всех настроек ===
    # Инициализируем состояние подтверждения, если его нет
    if 'reset_confirmation_pending' not in st.session_state:
        st.session_state.reset_confirmation_pending = False

    if st.button("🔄 Сбросить ВСЁ (настройки и профили)", key="reset_all_settings", help="Сбросить текущие настройки к значениям по умолчанию И удалить все пользовательские профили настроек.", disabled=st.session_state.reset_confirmation_pending):
        st.warning("Вы уверены, что хотите сбросить ВСЕ настройки и удалить ВСЕ пользовательские профили? Это действие нельзя отменить.", icon="🔥")
        st.session_state.reset_confirmation_pending = True
        st.rerun()

    if st.session_state.reset_confirmation_pending:
        confirm_col1, confirm_col2 = st.columns(2)
        
        with confirm_col1:
            if st.button("Да, сбросить ВСЁ", key="confirm_reset", type="primary"):
                try:
                    # 1. Удаляем все пользовательские профили
                    deleted_count = config_manager.delete_all_custom_presets()
                    if deleted_count is None:
                         # Ошибка при удалении профилей, прерываем сброс
                         st.error("Ошибка при удалении профилей. Полный сброс прерван.")
                         st.session_state.reset_confirmation_pending = False
                         st.rerun()
                         # Выход из блока try, чтобы не продолжать
                         raise Exception("Profile deletion failed") 
                    
                    log.info(f"Deleted {deleted_count} custom presets during full reset.")

                    # 2. Загружаем настройки по умолчанию
                    default_settings = config_manager.load_settings_preset("Настройки по умолчанию")
                    if default_settings:
                        # 3. Полностью заменяем текущие настройки настройками по умолчанию
                        st.session_state.current_settings = default_settings.copy()
                        
                        # 4. Сбрасываем активный пресет на "Настройки по умолчанию"
                        st.session_state.active_preset = "Настройки по умолчанию"
                        
                        # 5. Сбрасываем режим обработки
                        st.session_state.processing_mode_selector_widget = "Обработка отдельных файлов"
                        st.session_state.saved_processing_mode = "Обработка отдельных файлов"
                        
                        # 6. Отмечаем, что настройки изменились (для автосохранения)
                        st.session_state.settings_changed = True
                        
                        # 7. Сохраняем основной файл настроек
                        if config_manager.save_settings(st.session_state.current_settings, CONFIG_FILE):
                            st.success("Полный сброс выполнен! Настройки и профили сброшены.")
                        else:
                            st.error("Ошибка сохранения основных настроек после сброса.")
                    else:
                        st.error("Ошибка загрузки настроек по умолчанию во время сброса.")
                        
                    # Сбрасываем флаг подтверждения и перезапускаем
                    st.session_state.reset_confirmation_pending = False
                    st.rerun()

                except Exception as e:
                    # Проверяем, было ли это исключение из-за ошибки удаления профиля
                    if "Profile deletion failed" not in str(e):
                        st.error(f"Ошибка при полном сбросе: {str(e)}")
                    st.session_state.reset_confirmation_pending = False
                    st.rerun()
        
        with confirm_col2:
            if st.button("Отмена", key="cancel_reset"):
                st.info("Полный сброс отменен.")
                st.session_state.reset_confirmation_pending = False
                st.rerun()

    st.divider()

    # === Размеры ===
    st.header("📏 Размеры")
    
    # Предварительный ресайз
    with st.expander("1. Предварительный ресайз", expanded=False):
        enable_preresize = st.checkbox("Включить", value=get_setting('preprocessing.enable_preresize', False), key='pre_enable')
        set_setting('preprocessing.enable_preresize', enable_preresize)
        if enable_preresize:
            set_setting('preprocessing.preresize_width', st.number_input("Макс. Ш (пикс)", 0, value=get_setting('preprocessing.preresize_width', 2500), step=10, key='pre_w'))
            set_setting('preprocessing.preresize_height', st.number_input("Макс. В (пикс)", 0, value=get_setting('preprocessing.preresize_height', 2500), step=10, key='pre_h'))
        else:
            set_setting('preprocessing.preresize_width', 0)
            set_setting('preprocessing.preresize_height', 0)
    
    # Финальные размеры
    with st.expander("2. Финальные размеры", expanded=False):
        if processing_mode == "Обработка отдельных файлов":
            st.caption("Соотношение сторон (W:H, 0=выкл)")
            current_ratio = get_setting('individual_mode.force_aspect_ratio', None)
            default_w = float(current_ratio[0]) if current_ratio else 0.0
            default_h = float(current_ratio[1]) if current_ratio else 0.0
            ratio_w = st.number_input("W", 0.0, value=default_w, step=0.1, key='ind_ratio_w')
            ratio_h = st.number_input("H", 0.0, value=default_h, step=0.1, key='ind_ratio_h')
            if ratio_w > 0 and ratio_h > 0:
                set_setting('individual_mode.force_aspect_ratio', [ratio_w, ratio_h])
            else:
                set_setting('individual_mode.force_aspect_ratio', None)
            
            st.caption("Макс. размер (ШxВ, 0=выкл)")
            set_setting('individual_mode.max_output_width', st.number_input("Ш", 0, value=get_setting('individual_mode.max_output_width', 1500), step=50, key='ind_max_w'))
            set_setting('individual_mode.max_output_height', st.number_input("В", 0, value=get_setting('individual_mode.max_output_height', 1500), step=50, key='ind_max_h'))
            
            st.caption("Точный холст (ШxВ, 0=выкл)")
            set_setting('individual_mode.final_exact_width', st.number_input("Ш", 0, value=get_setting('individual_mode.final_exact_width', 0), step=50, key='ind_exact_w'))
            set_setting('individual_mode.final_exact_height', st.number_input("В", 0, value=get_setting('individual_mode.final_exact_height', 0), step=50, key='ind_exact_h'))
        else:
            st.caption("Соотношение коллажа (W:H, 0=выкл)")
            current_ratio = get_setting('collage_mode.force_collage_aspect_ratio', None)
            default_w = float(current_ratio[0]) if current_ratio else 0.0
            default_h = float(current_ratio[1]) if current_ratio else 0.0
            ratio_w = st.number_input("W", 0.0, value=default_w, step=0.1, key='coll_ratio_w')
            ratio_h = st.number_input("H", 0.0, value=default_h, step=0.1, key='coll_ratio_h')
            if ratio_w > 0 and ratio_h > 0:
                set_setting('collage_mode.force_collage_aspect_ratio', [ratio_w, ratio_h])
            else:
                set_setting('collage_mode.force_collage_aspect_ratio', None)
            
            st.caption("Макс. размер коллажа (ШxВ, 0=выкл)")
            set_setting('collage_mode.max_collage_width', st.number_input("Ш", 0, value=get_setting('collage_mode.max_collage_width', 1500), step=50, key='coll_max_w'))
            set_setting('collage_mode.max_collage_height', st.number_input("В", 0, value=get_setting('collage_mode.max_collage_height', 1500), step=50, key='coll_max_h'))
            
            st.caption("Точный холст коллажа (ШxВ, 0=выкл)")
            set_setting('collage_mode.final_collage_exact_width', st.number_input("Ш", 0, value=get_setting('collage_mode.final_collage_exact_width', 0), step=50, key='coll_exact_w'))
            set_setting('collage_mode.final_collage_exact_height', st.number_input("В", 0, value=get_setting('collage_mode.final_collage_exact_height', 0), step=50, key='coll_exact_h'))
    
    st.divider()

    # === Яркость и контрастность ===
    st.header("✨ Яркость и контрастность")
    with st.expander("Настройки яркости и контрастности", expanded=False):
        enable_adjustments = st.checkbox("Включить", value=get_setting('image_adjustments.enable_adjustments', False), key='adj_enable')
        set_setting('image_adjustments.enable_adjustments', enable_adjustments)
        if enable_adjustments:
            set_setting('image_adjustments.brightness', st.slider("Яркость", -100, 100, value=get_setting('image_adjustments.brightness', 0), key='adj_brightness'))
            set_setting('image_adjustments.contrast', st.slider("Контрастность", -100, 100, value=get_setting('image_adjustments.contrast', 0), key='adj_contrast'))
    
    st.divider()

    # === Фон и обрезка ===
    st.header("🎨 Фон и обрезка")
    with st.expander("Настройки фона и обрезки", expanded=False):
        enable_bg_crop = st.checkbox("Включить", value=get_setting('background_crop.enable_bg_crop', False), key='bgc_enable')
        set_setting('background_crop.enable_bg_crop', enable_bg_crop)
        if enable_bg_crop:
            set_setting('background_crop.white_tolerance', st.slider("Допуск белого фона", 0, 255, value=get_setting('background_crop.white_tolerance', 0), key='bgc_tol'))
            check_perimeter = st.checkbox("Проверять периметр", value=get_setting('background_crop.check_perimeter', True), key='bgc_perimeter')
            set_setting('background_crop.check_perimeter', check_perimeter)
            crop_abs = st.checkbox("Абсолютно симм. обрезка", value=get_setting('background_crop.crop_symmetric_absolute', False), key='bgc_abs')
            set_setting('background_crop.crop_symmetric_absolute', crop_abs)
            if not crop_abs:
                crop_axes = st.checkbox("Симм. обрезка по осям", value=get_setting('background_crop.crop_symmetric_axes', False), key='bgc_axes')
                set_setting('background_crop.crop_symmetric_axes', crop_axes)
            else:
                set_setting('background_crop.crop_symmetric_axes', False)
        else:
            set_setting('background_crop.white_tolerance', 0)
            set_setting('background_crop.check_perimeter', True)
            set_setting('background_crop.crop_symmetric_absolute', False)
            set_setting('background_crop.crop_symmetric_axes', False)
    
    st.divider()

    # === Добавление полей ===
    st.header("📐 Добавление полей")
    with st.expander("Настройки полей", expanded=False):
        enable_padding = st.checkbox("Включить", value=get_setting('padding.enable_padding', False), key='pad_enable')
        set_setting('padding.enable_padding', enable_padding)
        if enable_padding:
            set_setting('padding.padding_percent', st.slider("Процент полей (%)", 0.0, 50.0, value=get_setting('padding.padding_percent', 5.0), step=0.5, key='pad_perc'))
            set_setting('padding.perimeter_margin', st.number_input("Проверка периметра (пикс, 0=выкл)", 0, value=get_setting('padding.perimeter_margin', 0), step=1, key='pad_margin'))
            set_setting('padding.allow_expansion', st.checkbox("Разрешить полям увеличивать размер?", value=get_setting('padding.allow_expansion', True), key='pad_expand'))
        else:
            set_setting('padding.padding_percent', 0.0)
            set_setting('padding.perimeter_margin', 0)
            set_setting('padding.allow_expansion', False)

    # === Настройки режима "Обработка отдельных файлов" ===
    if processing_mode == "Обработка отдельных файлов":
        st.header("⚙️ Обработка файлов")
        with st.expander("Параметры вывода и переименования", expanded=True):
            # Артикул для переименования
            set_setting('individual_mode.article_name', 
                         st.text_input("Артикул для переименования (пусто=выкл)", 
                                       value=get_setting('individual_mode.article_name', ''), 
                                       key='ind_article'))
            
            # Удаление оригиналов
            set_setting('individual_mode.delete_originals', 
                         st.checkbox("Удалять оригиналы после обработки?", 
                                     value=get_setting('individual_mode.delete_originals', False), 
                                     key='ind_delete_orig'))
            st.warning("ВНИМАНИЕ: Используйте удаление оригиналов с осторожностью!", icon="⚠️")
            
            # Настройки вывода для отдельных файлов
            st.caption("Параметры вывода (отдельные файлы)")
            output_format_ind = st.selectbox("Формат вывода", 
                                             options=["jpg", "png"],
                                             index=["jpg", "png"].index(get_setting('individual_mode.output_format', 'jpg')),
                                             key='ind_format')
            set_setting('individual_mode.output_format', output_format_ind)
            
            if output_format_ind == 'jpg':
                set_setting('individual_mode.jpeg_quality', 
                             st.slider("Качество JPG", 
                                       min_value=1, 
                                       max_value=100, 
                                       value=get_setting('individual_mode.jpeg_quality', 95), 
                                       key='ind_quality'))
                bg_color_str_ind = ",".join(map(str, get_setting('individual_mode.jpg_background_color', [255,255,255])))
                new_bg_color_str_ind = st.text_input("Фон JPG (R,G,B)", value=bg_color_str_ind, key='ind_bg')
                try:
                    new_bg_color_ind = list(map(int, new_bg_color_str_ind.split(',')))
                    if len(new_bg_color_ind) == 3 and all(0 <= c <= 255 for c in new_bg_color_ind):
                        set_setting('individual_mode.jpg_background_color', new_bg_color_ind)
                    else:
                        st.caption("❌ Неверный формат цвета (нужно R,G,B)")
                except ValueError:
                     st.caption("❌ Неверный формат цвета (нужно R,G,B)")
        st.divider()

    
    # === Настройки коллажа (только для режима коллажа) ===
    if processing_mode == "Создание коллажей":
        st.header("🖼️ Настройки коллажа")
        with st.expander("Параметры вывода и переименования", expanded=True):
            # Формат вывода
            output_format_coll = st.selectbox("Формат вывода", 
                                             options=["jpg", "png"],
                                             index=["jpg", "png"].index(get_setting('collage_mode.output_format', 'jpg')),
                                             key='coll_format')
            set_setting('collage_mode.output_format', output_format_coll)
            
            if output_format_coll == 'jpg':
                set_setting('collage_mode.jpeg_quality', 
                             st.slider("Качество JPG", 
                                       min_value=1, 
                                       max_value=100, 
                                       value=get_setting('collage_mode.jpeg_quality', 95), 
                                       key='coll_quality'))
                # Используем get_setting для получения цвета фона коллажа
                bg_color_str_coll = ",".join(map(str, get_setting('collage_mode.jpg_background_color', [255,255,255])))
                new_bg_color_str_coll = st.text_input("Фон JPG коллажа (R,G,B)", value=bg_color_str_coll, key='coll_bg') # Разные ключи для разных режимов
                try:
                    new_bg_color_coll = list(map(int, new_bg_color_str_coll.split(',')))
                    if len(new_bg_color_coll) == 3 and all(0 <= c <= 255 for c in new_bg_color_coll):
                        set_setting('collage_mode.jpg_background_color', new_bg_color_coll)
                    else:
                        st.caption("❌ Неверный формат цвета (нужно R,G,B)")
                except ValueError:
                     st.caption("❌ Неверный формат цвета (нужно R,G,B)")
            
        st.divider()

# === ОСНОВНАЯ ОБЛАСТЬ ПРИЛОЖЕНИЯ ===
# --- UI ---
st.title("🖼️ Инструмент Обработки Изображений")
st.markdown("Пакетная обработка отдельных файлов или создание коллажей.")
st.divider()

# === ИЗВЛЕКАЕМ ЗНАЧЕНИЕ РЕЖИМА ПОСЛЕ ОТРИСОВКИ САЙДБАРА ===
# Это значение будет использоваться в основной области
if "processing_mode_selector_widget" not in st.session_state:
    st.session_state.processing_mode_selector_widget = "Обработка отдельных файлов"

# Проверяем, есть ли сохраненный режим обработки
if "saved_processing_mode" in st.session_state:
    # Если есть сохраненный режим, используем его для следующего рендера
    st.session_state.processing_mode_selector_widget = st.session_state.saved_processing_mode
    # Удаляем сохраненный режим, чтобы он не использовался повторно
    del st.session_state.saved_processing_mode

processing_mode = st.session_state.processing_mode_selector_widget
log.debug(f"Processing mode determined for main area: {processing_mode}")

# === ОСНОВНАЯ ОБЛАСТЬ ПРИЛОЖЕНИЯ ===
st.divider()
col1, col2 = st.columns([3, 1])

with col2:
     st.caption(f"Выбран режим: {processing_mode}") # Используем переменную из сайдбара

with col1:
    # --- Отрисовка кнопки ---
    # При нажатии вернет True ТОЛЬКО в том рендере, когда была нажата
    if st.button(f"🚀 Запустить: {processing_mode}", type="primary", key='start_button_actual_key', use_container_width=True): # Новый ключ
        log.info(f"--- Button '{processing_mode}' CLICKED! Attempting to start processing logic. ---")
        print(f"--- APP.PY PRINT: Button '{processing_mode}' CLICKED! ---")

        # === ДОБАВЛЕНО ДЛЯ ОТЛАДКИ ===
        # st.info("Кнопка нажата, начинаем проверку путей...", icon="⏳")
        # ==============================

        # --- Логика Запуска (теперь ВНУТРИ if st.button) ---
        log.info(f"--- Starting validation... ---")
        # Очищаем лог ПЕРЕД запуском
        log_stream.seek(0)
        log_stream.truncate(0)
        log.info(f"--- Log cleared. Validating paths for mode '{processing_mode}' ---")

        # --- ПРОВЕРКА ПУТЕЙ ---
        paths_ok = True
        validation_errors = []
        input_path = get_setting('paths.input_folder_path', '')
        abs_input_path = os.path.abspath(input_path) if input_path else ''
        if not input_path or not os.path.isdir(abs_input_path):
            validation_errors.append(f"Папка с исходными файлами не найдена или не указана: '{input_path}'")
            paths_ok = False

        if processing_mode == "Обработка отдельных файлов":
            output_path_ind = get_setting('paths.output_folder_path', '')
            abs_output_path_ind = os.path.abspath(output_path_ind) if output_path_ind else ''
            if not output_path_ind: validation_errors.append("Не указана папка для результатов!"); paths_ok = False
            # Проверка совпадения путей при удалении
            safe_to_delete_check = True
            if get_setting('individual_mode.delete_originals', False):
                 if not input_path or not output_path_ind or os.path.normcase(abs_input_path) == os.path.normcase(abs_output_path_ind):
                      safe_to_delete_check = False
                      st.warning("Удаление оригиналов не будет выполнено (папка ввода/вывода не указаны или совпадают).", icon="⚠️")
                      log.warning("Original deletion will be skipped (paths invalid or same).")

        elif processing_mode == "Создание коллажа":
            output_filename_coll = get_setting('paths.output_filename', '')
            if not output_filename_coll: validation_errors.append("Не указано имя файла для сохранения коллажа!"); paths_ok = False
            elif input_path and paths_ok: # Проверяем, что input_path валидна
                 full_coll_path = os.path.join(abs_input_path, output_filename_coll)
                 if os.path.isdir(full_coll_path): validation_errors.append(f"Имя файла коллажа '{output_filename_coll}' указывает на папку!"); paths_ok = False

        # --- ЗАПУСК или ВЫВОД ОШИБОК --- 
        if not paths_ok:
            log.warning("--- Path validation FAILED. Processing aborted. ---")
            for error_msg in validation_errors:
                st.error(error_msg, icon="❌")
                log.error(f"Validation Error: {error_msg}")
            st.warning("Обработка не запущена из-за ошибок в настройках путей.", icon="⚠️")
        else:
            # === ДОБАВЛЕНО ДЛЯ ОТЛАДКИ ===
            # st.info("Проверка путей пройдена, запускаем обработку...", icon="✅")
            # ==============================

            # Пути в порядке, ЗАПУСКАЕМ обработку
            log.info(f"--- Path validation successful. Starting processing workflow... ---")
            
            with st.spinner(f"Выполняется обработка в режиме '{processing_mode}'... Пожалуйста, подождите."):
                 try:
                     current_run_settings = st.session_state.current_settings.copy()
                     log.debug(f"Passing settings to workflow (raw): {current_run_settings}")
                     
                     # === УДАЛЯЕМ ОТЛАДОЧНЫЙ ВЫВОД ===
                     # log.info(f"CHECKING MODE before branch: processing_mode = '{processing_mode}' (Type: {type(processing_mode)})" )
                     # print(f"--- APP.PY PRINT CHECK: Mode is '{processing_mode}' ---")
                     # ==============================
                     
                     if processing_mode == "Обработка отдельных файлов":
                         log.info("Branch: Обработка отдельных файлов")
                         log.debug(f"Calling run_individual_processing...")
                         processing_workflows.run_individual_processing(**current_run_settings)
                         log.info("Finished run_individual_processing call.")

                     elif processing_mode == "Создание коллажа":
                         log.info("Branch: Создание коллажа")
                         log.debug(f"Collage Settings (pre-call): {json.dumps(current_run_settings.get('collage_mode',{}), indent=2)}")
                         
                         # Проверка путей перед запуском коллажа
                         input_path = get_setting('paths.input_folder_path', '')
                         output_filename = get_setting('paths.output_filename', '')
                         abs_input_path = os.path.abspath(input_path) if input_path else ''
                         
                         log.info(f"Pre-call check: Input path = '{abs_input_path}', Output filename = '{output_filename}'")
                         
                         # Проверка прав доступа к папке для записи
                         if not os.access(abs_input_path, os.W_OK):
                             error_msg = f"Нет прав на запись в папку с исходными файлами: '{abs_input_path}'"
                             log.error(error_msg)
                             raise PermissionError(error_msg)
                         
                         # Попытка создать тестовый файл в директории
                         test_file_path = os.path.join(abs_input_path, "_test_write_permission.txt")
                         try:
                             with open(test_file_path, 'w') as f:
                                 f.write("Test write permission")
                             os.remove(test_file_path)
                             log.info(f"Test file created and removed successfully in '{abs_input_path}'")
                         except Exception as e:
                             error_msg = f"Не удалось создать тестовый файл в '{abs_input_path}': {e}"
                             log.error(error_msg)
                             raise PermissionError(error_msg)
                         
                         # !!! ТЕСТОВАЯ ОШИБКА ЗАКОММЕНТИРОВАНА !!!
                         
                         print("--- APP.PY PRINT: BEFORE calling run_collage_processing ---") 
                         
                         try:
                             processing_workflows.run_collage_processing(**current_run_settings)
                         except Exception as collage_error:
                             # Пробуем выполнить прямое создание коллажа
                             try:
                                 # Получаем список файлов в папке источника
                                 image_files = [f for f in os.listdir(abs_input_path) 
                                             if os.path.isfile(os.path.join(abs_input_path, f)) 
                                             and f.lower().endswith(('.png', '.jpg', '.jpeg'))]
                                 
                                 if image_files:
                                     # Создаем очень простой коллаж из первого изображения
                                     from PIL import Image
                                     first_image_path = os.path.join(abs_input_path, image_files[0])
                                     simple_collage_path = os.path.join(abs_input_path, "emergency_direct_collage.jpg")
                                     
                                     img = Image.open(first_image_path)
                                     
                                     # Просто сохраняем в новый файл как есть
                                     img.save(simple_collage_path, "JPEG", quality=95)
                             except Exception as direct_err:
                                 pass # Молча проглатываем ошибку отображения ошибки
                             
                             # Перебрасываем оригинальную ошибку для дальнейшей обработки
                             raise collage_error
                         
                         print("--- APP.PY PRINT: AFTER calling run_collage_processing ---") 
                         log.info("Finished run_collage_processing call.")
                     
                     # Общий success после try
                     log.info("--- Processing workflow finished successfully (within try block). ---")
                     st.success("Обработка успешно завершена!", icon="✅") 

                 except Exception as e:
                     log.critical(f"!!! WORKFLOW EXECUTION FAILED (Caught in app.py): {e}", exc_info=True)
                     print(f"--- APP.PY PRINT: CAUGHT EXCEPTION: {type(e).__name__}: {e} ---") 
                     
                     try:
                         # Показываем исключение в UI
                         st.exception(e)
                     except Exception as ui_error:
                         pass # Молча проглатываем ошибку отображения ошибки
                     
                     # Дополнительная проверка после исключения
                     pass # Блок finally остается для структуры

st.divider()
# --- Область для Логов ---
st.subheader("Логи выполнения:")
if st.button("�� Обновить лог", key="refresh_log_button"):
    # Просто перезапускаем скрипт, чтобы text_area обновился
    st.rerun()
    
with st.expander("Показать/скрыть лог", expanded=True):
    # Просто отображаем текущее содержимое буфера
    st.text_area("Лог:", value=log_stream.getvalue(), height=400, key='log_output_display_area', disabled=True, label_visibility="collapsed")

# Добавляем лог в конце скрипта
log.info("--- End of app.py execution cycle --- ")
# print("--- PRINT: End of app.py execution cycle ---") # Можно добавить для доп. проверки

# Автосохранение настроек при любом изменении
if st.session_state.settings_changed:
    if config_manager.save_settings(st.session_state.current_settings, CONFIG_FILE):
        log.debug("Settings auto-saved successfully")
    else:
        log.error("Error auto-saving settings")
    st.session_state.settings_changed = False