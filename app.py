# app.py

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

    import config_manager
    import processing_workflows
    print("Модули успешно загружены.")
except ImportError as e: print(f"\n[!!! КРИТИЧЕСКАЯ ОШИБКА] Import Error: {e}"); sys.exit(1)
except Exception as e: print(f"\n[!!! КРИТИЧЕСКАЯ ОШИБКА] App Import Error: {e}"); import traceback; traceback.print_exc(); sys.exit(1)

# --- Настройка логирования ---
log_stream = StringIO()
log_level = logging.DEBUG # <-- УСТАНОВИТЕ DEBUG ДЛЯ ОТЛАДКИ
logging.basicConfig(stream=log_stream, level=log_level, format='%(asctime)s - %(levelname)s - %(name)s - %(message)s', datefmt='%H:%M:%S')
log = logging.getLogger(__name__)
log.info(f"Logging configured at level: {logging.getLevelName(log_level)}")

# === Основной код приложения Streamlit ===

# --- Загрузка/Инициализация Настроек ---
CONFIG_FILE = "settings.json"
log.debug(f"Loading settings from {CONFIG_FILE}")
settings = config_manager.load_settings(CONFIG_FILE)
# Инициализируем настройки в session_state при первом запуске
if 'current_settings' not in st.session_state:
    log.debug("Initializing current_settings in session_state.")
    st.session_state.current_settings = settings.copy() # Сохраняем копию

# --- Вспомогательные функции ---
def get_setting(key_path: str, default: Any = None) -> Any:
    keys = key_path.split('.')
    value = st.session_state.current_settings
    try:
        for key in keys: value = value[key]
        if isinstance(value, (list, dict)): return value.copy()
        return value
    except (KeyError, TypeError):
        # log.debug(f"Setting '{key_path}' not found, returning default: {default}")
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
        # log.debug(f"(set_setting) '{key_path}' = {value}") # Отладка
    except TypeError as e: log.error(f"Error setting '{key_path}': {e}")


# --- UI ---
st.set_page_config(layout="wide", page_title="Обработчик Изображений")
st.title("🖼️ Инструмент Обработки Изображений")
st.markdown("Пакетная обработка отдельных файлов или создание коллажей.")
st.divider()

# --- Переменная для хранения результата нажатия кнопки в этом рендере ---
# Важно: эта переменная будет False при каждом рендере, кроме того,
# который произошел СРАЗУ ПОСЛЕ нажатия кнопки.
start_button_pressed_this_run = False

# --- UI: Боковая Панель ---
with st.sidebar:
    st.header("⚙️ Настройки")

    # --- Выбор Режима Работы ---
    # Определяем callback ДО виджета, который его использует
    def mode_change_callback():
        log.debug(f"Mode changed via UI to: {st.session_state.processing_mode_selector_widget}")
        # Сохраняем выбранное значение в наши основные настройки тоже
        set_setting("processing_mode_selector", st.session_state.processing_mode_selector_widget)
        # Можно добавить сброс специфичных настроек другого режима при смене, если нужно

    # Используем get_setting для инициализации индекса радио-кнопки
    current_mode_setting = get_setting("processing_mode_selector", "Обработка отдельных файлов")
    mode_options = ("Обработка отдельных файлов", "Создание коллажа")
    default_mode_index = mode_options.index(current_mode_setting) if current_mode_setting in mode_options else 0

    # Виджет радио-кнопки с callback'ом
    st.radio(
        "Режим работы:",
        mode_options,
        index=default_mode_index,
        key='processing_mode_selector_widget', # Уникальный ключ для виджета
        on_change=mode_change_callback,
        help="Выберите, что нужно сделать: обработать каждый файл и сохранить отдельно, или создать коллаж из всех файлов."
    )
    # --- Значение режима для остального кода берем из session_state ---
    # Это гарантирует, что мы используем актуальное значение после возможного on_change
    processing_mode = st.session_state.processing_mode_selector_widget
    log.debug(f"Current processing_mode from widget state: {processing_mode}")

    st.divider()

    # --- Общие Настройки (Пути) ---
    st.subheader("Пути")
    set_setting('paths.input_folder_path', st.text_input("Папка с исходными файлами:", value=get_setting('paths.input_folder_path', ''), key='path_input', placeholder="C:/Users/User/Pictures/Source"))
    # --- Отображаем все поля путей, но используем только нужные в логике ---
    set_setting('paths.output_folder_path', st.text_input("Папка для результатов (Отдельные файлы):", value=get_setting('paths.output_folder_path', ''), key='path_output_ind', placeholder="C:/Users/User/Pictures/Processed"))
    set_setting('paths.backup_folder_path', st.text_input("Папка для бэкапов (Отдельные файлы, пусто = выкл):", value=get_setting('paths.backup_folder_path', ''), key='path_backup_ind', placeholder="C:/Users/User/Pictures/Backup"))
    set_setting('paths.output_filename', st.text_input("Имя файла коллажа (в папке источника):", value=get_setting('paths.output_filename', 'collage.jpg'), key='path_output_coll'))
    st.divider()

    # --- Общие Настройки Обработки (в expanders) ---
    st.subheader("Общая обработка (для отдельных файлов)")
    with st.expander("1. Предварительный ресайз", expanded=False):
        enable_preresize = st.checkbox("Включить##pre", value=get_setting('preprocessing.enable_preresize', False), key='pre_enable')
        set_setting('preprocessing.enable_preresize', enable_preresize)
        if enable_preresize:
            cols_preresize = st.columns(2)
            set_setting('preprocessing.preresize_width', cols_preresize[0].number_input("Макс. Ш (пикс)##pre", 0, value=get_setting('preprocessing.preresize_width', 2500), step=10, key='pre_w'))
            set_setting('preprocessing.preresize_height', cols_preresize[1].number_input("Макс. В (пикс)##pre", 0, value=get_setting('preprocessing.preresize_height', 2500), step=10, key='pre_h'))
        else: set_setting('preprocessing.preresize_width', 0); set_setting('preprocessing.preresize_height', 0)

    with st.expander("2. Отбеливание", expanded=False):
        enable_whitening = st.checkbox("Включить##wh", value=get_setting('whitening.enable_whitening', True), key='wh_enable')
        set_setting('whitening.enable_whitening', enable_whitening)
        if enable_whitening:
            set_setting('whitening.whitening_cancel_threshold', st.slider("Порог отмены (сумма RGB)##wh", 0, 765, value=get_setting('whitening.whitening_cancel_threshold', 550), key='wh_thresh'))

    with st.expander("3. Фон и Обрезка", expanded=False):
        enable_bg_crop = st.checkbox("Включить##bgc", value=get_setting('background_crop.enable_bg_crop', False), key='bgc_enable')
        set_setting('background_crop.enable_bg_crop', enable_bg_crop)
        if enable_bg_crop:
            set_setting('background_crop.white_tolerance', st.slider("Допуск белого фона##bgc", 0, 255, value=get_setting('background_crop.white_tolerance', 0), key='bgc_tol'))
            crop_abs = st.checkbox("Абсолютно симм. обрезка##bgc", value=get_setting('background_crop.crop_symmetric_absolute', False), key='bgc_abs')
            set_setting('background_crop.crop_symmetric_absolute', crop_abs)
            if not crop_abs:
                 crop_axes = st.checkbox("Симм. обрезка по осям##bgc", value=get_setting('background_crop.crop_symmetric_axes', False), key='bgc_axes')
                 set_setting('background_crop.crop_symmetric_axes', crop_axes)
            else: set_setting('background_crop.crop_symmetric_axes', False)
        else: set_setting('background_crop.white_tolerance', 0); set_setting('background_crop.crop_symmetric_absolute', False); set_setting('background_crop.crop_symmetric_axes', False)

    with st.expander("4. Добавление полей", expanded=False):
        enable_padding = st.checkbox("Включить##pad", value=get_setting('padding.enable_padding', False), key='pad_enable')
        set_setting('padding.enable_padding', enable_padding)
        if enable_padding:
            set_setting('padding.padding_percent', st.slider("Процент полей (%)##pad", 0.0, 50.0, value=get_setting('padding.padding_percent', 5.0), step=0.5, key='pad_perc'))
            set_setting('padding.perimeter_margin', st.number_input("Проверка периметра (пикс, 0=выкл)##pad", 0, value=get_setting('padding.perimeter_margin', 0), step=1, key='pad_margin'))
            set_setting('padding.allow_expansion', st.checkbox("Разрешить полям увеличивать размер?##pad", value=get_setting('padding.allow_expansion', True), key='pad_expand'))
        else: set_setting('padding.padding_percent', 0.0); set_setting('padding.perimeter_margin', 0); set_setting('padding.allow_expansion', False)

    st.divider()

    # --- Настройки, Специфичные для Режима ---
    # Отображаем оба блока всегда для избежания проблем с состоянием
    st.subheader("5. Настройки: Отдельные файлы")
    with st.container():
        # Используем disable, если режим не тот? Или просто оставляем видимым.
        # disable_ind = (processing_mode != "Обработка отдельных файлов") # Флаг для блокировки
        with st.expander("Переименование и удаление##ind", expanded=True):
            set_setting('individual_mode.article_name', st.text_input("Артикул (пусто = выкл)##ind", value=get_setting('individual_mode.article_name', ''), key='ind_article')) #, disabled=disable_ind))
            set_setting('individual_mode.delete_originals', st.checkbox("Удалять оригиналы?##ind", value=get_setting('individual_mode.delete_originals', False), key='ind_delete')) #, disabled=disable_ind))
            st.caption("⚠️ Удаление работает только если папки ввода и вывода РАЗНЫЕ!")
        with st.expander("Финальные трансформации##ind", expanded=True):
            st.caption("Соотношение сторон (W:H, 0=выкл)")
            cols_ratio_ind = st.columns(2)
            current_ratio_ind = get_setting('individual_mode.force_aspect_ratio', None)
            default_w_ind = float(current_ratio_ind[0]) if current_ratio_ind else 0.0; default_h_ind = float(current_ratio_ind[1]) if current_ratio_ind else 0.0
            ratio_w_ind = cols_ratio_ind[0].number_input("W##ind_ratio", 0.0, value=default_w_ind, step=0.1, key='ind_ratio_w', label_visibility="collapsed") #, disabled=disable_ind))
            ratio_h_ind = cols_ratio_ind[1].number_input("H##ind_ratio", 0.0, value=default_h_ind, step=0.1, key='ind_ratio_h', label_visibility="collapsed") #, disabled=disable_ind))
            if ratio_w_ind > 0 and ratio_h_ind > 0: set_setting('individual_mode.force_aspect_ratio', [ratio_w_ind, ratio_h_ind])
            else: set_setting('individual_mode.force_aspect_ratio', None)
            st.caption("Макс. размер (ШxВ, 0=выкл)")
            cols_max_dims_ind = st.columns(2)
            set_setting('individual_mode.max_output_width', cols_max_dims_ind[0].number_input("Ш##ind_max", 0, value=get_setting('individual_mode.max_output_width', 1500), step=50, key='ind_max_w', label_visibility="collapsed")) #, disabled=disable_ind))
            set_setting('individual_mode.max_output_height', cols_max_dims_ind[1].number_input("В##ind_max", 0, value=get_setting('individual_mode.max_output_height', 1500), step=50, key='ind_max_h', label_visibility="collapsed")) #, disabled=disable_ind))
            st.caption("Точный холст (ШxВ, 0=выкл)")
            cols_exact_dims_ind = st.columns(2)
            set_setting('individual_mode.final_exact_width', cols_exact_dims_ind[0].number_input("Ш##ind_exact", 0, value=get_setting('individual_mode.final_exact_width', 0), step=50, key='ind_exact_w', label_visibility="collapsed")) #, disabled=disable_ind))
            set_setting('individual_mode.final_exact_height', cols_exact_dims_ind[1].number_input("В##ind_exact", 0, value=get_setting('individual_mode.final_exact_height', 0), step=50, key='ind_exact_h', label_visibility="collapsed")) #, disabled=disable_ind))
        with st.expander("Формат вывода##ind", expanded=True):
            ind_format = st.selectbox("Формат:##ind", ('jpg', 'png'), index=0 if get_setting('individual_mode.output_format', 'jpg') == 'jpg' else 1, key='ind_output_format') #, disabled=disable_ind))
            set_setting('individual_mode.output_format', ind_format)
            if ind_format == 'jpg': set_setting('individual_mode.jpeg_quality', st.slider("Качество JPG:##ind", 1, 100, value=get_setting('individual_mode.jpeg_quality', 95), step=1, key='ind_jpeg_quality')) #, disabled=disable_ind))

    st.divider()
    st.subheader("6. Настройки: Создание Коллажа")
    with st.container():
        # disable_coll = (processing_mode != "Создание коллажа") # Флаг для блокировки
        with st.expander("Параметры сетки##coll", expanded=True):
            set_setting('collage_mode.forced_cols', st.number_input("Кол-во столбцов (0=авто)##coll", 0, value=get_setting('collage_mode.forced_cols', 0), step=1, key='coll_cols')) #, disabled=disable_coll))
            set_setting('collage_mode.spacing_percent', st.slider("Отступ между (%)##coll", 0.0, 20.0, value=get_setting('collage_mode.spacing_percent', 2.0), step=0.5, key='coll_space')) #, disabled=disable_coll))
        with st.expander("Пропорциональное размещение##coll", expanded=False):
             prop_enabled = st.checkbox("Включить##coll_prop", value=get_setting('collage_mode.proportional_placement', False), key='coll_prop') #, disabled=disable_coll))
             set_setting('collage_mode.proportional_placement', prop_enabled)
             if prop_enabled:
                 ratios_str = st.text_input("Коэфф. (через запятую, напр: 1,0.8,1)##coll_prop", value=", ".join(map(str, get_setting('collage_mode.placement_ratios', [1.0]))), key='coll_ratios_str') #, disabled=disable_coll))
                 try:
                     ratios_list = [float(x.strip()) for x in ratios_str.split(',') if x.strip()]
                     if not ratios_list: ratios_list = [1.0]
                     set_setting('collage_mode.placement_ratios', ratios_list)
                 except ValueError: st.error("Неверный формат!")
        with st.expander("Трансформации коллажа##coll", expanded=True):
            st.caption("Соотношение коллажа (W:H, 0=выкл)")
            cols_ratio_coll = st.columns(2)
            current_ratio_coll = get_setting('collage_mode.force_collage_aspect_ratio', None)
            default_w_coll = float(current_ratio_coll[0]) if current_ratio_coll else 0.0; default_h_coll = float(current_ratio_coll[1]) if current_ratio_coll else 0.0
            ratio_w_coll = cols_ratio_coll[0].number_input("W##coll_ratio", 0.0, value=default_w_coll, step=0.1, key='coll_ratio_w', label_visibility="collapsed") #, disabled=disable_coll))
            ratio_h_coll = cols_ratio_coll[1].number_input("H##coll_ratio", 0.0, value=default_h_coll, step=0.1, key='coll_ratio_h', label_visibility="collapsed") #, disabled=disable_coll))
            if ratio_w_coll > 0 and ratio_h_coll > 0: set_setting('collage_mode.force_collage_aspect_ratio', [ratio_w_coll, ratio_h_coll])
            else: set_setting('collage_mode.force_collage_aspect_ratio', None)
            st.caption("Макс. размер коллажа (ШxВ, 0=выкл)")
            cols_max_dims_coll = st.columns(2)
            set_setting('collage_mode.max_collage_width', cols_max_dims_coll[0].number_input("Ш##coll_max", 0, value=get_setting('collage_mode.max_collage_width', 1500), step=50, key='coll_max_w', label_visibility="collapsed")) #, disabled=disable_coll))
            set_setting('collage_mode.max_collage_height', cols_max_dims_coll[1].number_input("В##coll_max", 0, value=get_setting('collage_mode.max_collage_height', 1500), step=50, key='coll_max_h', label_visibility="collapsed")) #, disabled=disable_coll))
            st.caption("Точный холст коллажа (ШxВ, 0=выкл)")
            cols_exact_dims_coll = st.columns(2)
            set_setting('collage_mode.final_collage_exact_width', cols_exact_dims_coll[0].number_input("Ш##coll_exact", 0, value=get_setting('collage_mode.final_collage_exact_width', 0), step=50, key='coll_exact_w', label_visibility="collapsed")) #, disabled=disable_coll))
            set_setting('collage_mode.final_collage_exact_height', cols_exact_dims_coll[1].number_input("В##coll_exact", 0, value=get_setting('collage_mode.final_collage_exact_height', 0), step=50, key='coll_exact_h', label_visibility="collapsed")) #, disabled=disable_coll))
        with st.expander("Формат вывода коллажа##coll", expanded=True):
            coll_format = st.selectbox("Формат:##coll", ('jpg', 'png'), index=0 if get_setting('collage_mode.output_format', 'jpg') == 'jpg' else 1, key='coll_output_format') #, disabled=disable_coll))
            set_setting('collage_mode.output_format', coll_format)
            if coll_format == 'jpg': set_setting('collage_mode.jpeg_quality', st.slider("Качество JPG:##coll", 1, 100, value=get_setting('collage_mode.jpeg_quality', 95), step=1, key='coll_jpeg_quality')) #, disabled=disable_coll))

    # --- Кнопки Управления Настройками ---
    st.divider()
    st.subheader("Управление настройками")
    cols_buttons = st.columns(2)
    if cols_buttons[0].button("💾 Сохранить", key='save_settings_btn', use_container_width=True, help="Сохранить текущие настройки в файл settings.json"):
        save_successful = config_manager.save_settings(st.session_state.current_settings, CONFIG_FILE)
        if save_successful: st.success("Настройки сохранены!")
        else: st.error("Ошибка сохранения!")
        time.sleep(1); st.rerun()
    if cols_buttons[1].button("🔄 Сбросить", key='reset_settings_btn', use_container_width=True, help="Сбросить все настройки к значениям по умолчанию"):
        st.session_state.current_settings = config_manager.get_default_settings()
        log.info("Settings reset to defaults.")
        st.success("Настройки сброшены!")
        time.sleep(1); st.rerun()

# === ИЗВЛЕКАЕМ ЗНАЧЕНИЕ РЕЖИМА ПОСЛЕ ОТРИСОВКИ САЙДБАРА ===
# Это значение будет использоваться в основной области
processing_mode = st.session_state.processing_mode_selector_widget
log.debug(f"Processing mode determined for main area: {processing_mode}")


# === ОСНОВНАЯ ОБЛАСТЬ ПРИЛОЖЕНИЯ ===
# ... (Колонки col1, col2) ...
# ... (Кнопка Запустить с on_click=trigger_processing) ...
# ... (Область логов с st.text_area) ...
# ... (Логика Запуска if st.session_state.get('run_processing_flag', False):) ...
# ... (Опциональное отображение коллажа) ...
# ... (log.debug("--- End of app script render cycle ---")) ...

# === ОСНОВНАЯ ОБЛАСТЬ ПРИЛОЖЕНИЯ ===
st.divider()
col1, col2 = st.columns([3, 1])

with col2:
     st.caption(f"Выбран режим: {processing_mode}") # Используем переменную из сайдбара

with col1:
    # --- Отрисовка кнопки ---
    # При нажатии вернет True ТОЛЬКО в том рендере, когда была нажата
    if st.button(f"🚀 Запустить: {processing_mode}", type="primary", key='start_button_actual_key', use_container_width=True): # Новый ключ
        start_button_pressed_this_run = True # Устанавливаем флаг для ЭТОГО рендера
        log.info(f"--- Button '{processing_mode}' clicked! ---") # Логируем нажатие

st.divider()
# --- Область для Логов ---
st.subheader("Логи выполнения:")
with st.expander("Показать/скрыть лог", expanded=True):
    # Просто отображаем текущее содержимое буфера
    st.text_area("Лог:", value=log_stream.getvalue(), height=400, key='log_output_display_area', disabled=True, label_visibility="collapsed")

# --- Логика Запуска (Выполняется только если кнопка была нажата в этом рендере) ---
if start_button_pressed_this_run:
    log.info(f"--- Start button was pressed this run. Starting validation... ---")
    # Очищаем лог ПЕРЕД запуском (предыдущий уже отобразился)
    log_stream.seek(0)
    log_stream.truncate(0)
    log.info(f"--- Log cleared. Validating paths for mode '{processing_mode}' ---") # Новое стартовое сообщение

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
        if paths_ok and get_setting('individual_mode.delete_originals') and input_path and output_path_ind and os.path.normcase(abs_input_path) == os.path.normcase(abs_output_path_ind):
             st.warning("Удаление оригиналов не будет выполнено (папка ввода и вывода совпадают).", icon="⚠️")
             log.warning("Original deletion will be skipped (paths are same).")

    elif processing_mode == "Создание коллажа":
        output_filename_coll = get_setting('paths.output_filename', '')
        if not output_filename_coll: validation_errors.append("Не указано имя файла для сохранения коллажа!"); paths_ok = False
        elif input_path and paths_ok:
             full_coll_path = os.path.join(abs_input_path, output_filename_coll)
             if os.path.isdir(full_coll_path): validation_errors.append(f"Имя файла коллажа '{output_filename_coll}' указывает на папку!"); paths_ok = False

    # --- ЗАПУСК или ВЫВОД ОШИБОК ---
    if not paths_ok:
        log.warning("--- Path validation FAILED. Processing aborted. ---")
        for error_msg in validation_errors:
            st.error(error_msg, icon="❌")
            log.error(f"Validation Error: {error_msg}")
        st.warning("Обработка не запущена из-за ошибок в настройках путей.", icon="⚠️")
        # ВАЖНО: НЕ вызываем rerun здесь, ошибки и лог уже отображены
    else:
        # Пути в порядке, ЗАПУСКАЕМ обработку
        log.info(f"--- Path validation successful. Starting processing workflow... ---")
        # ВАЖНО: НЕ вызываем rerun здесь

        with st.spinner(f"Выполняется обработка в режиме '{processing_mode}'... Пожалуйста, подождите."):
            try:
                current_run_settings = st.session_state.current_settings.copy()
                log.debug(f"Passing settings to workflow: {current_run_settings}")

                if processing_mode == "Обработка отдельных файлов":
                    processing_workflows.run_individual_processing(**current_run_settings)
                elif processing_mode == "Создание коллажа":
                    processing_workflows.run_collage_processing(**current_run_settings)

                log.info("--- Processing workflow finished successfully. ---")
                st.success("Обработка успешно завершена!", icon="✅")

            except Exception as e:
                log.critical(f"!!! WORKFLOW EXECUTION FAILED: {e}", exc_info=True)
                st.error(f"Произошла критическая ошибка во время обработки: {e}", icon="🔥")
            # finally: # Блок finally не нужен, если нет rerun
            #     pass

        # ВАЖНО: После завершения spinner и try/except, скрипт просто заканчивается.
        # Обновление логов и предпросмотр произойдут при СЛЕДУЮЩЕМ рендере (любом действии пользователя).
        # Чтобы обновить лог СРАЗУ после завершения, НУЖЕН rerun.
        # Если хотите немедленного обновления лога - раскомментируйте следующую строку:
        # st.rerun()
        log.info("--- Processing block finished. UI update will happen on next interaction or rerun. ---")


# --- Опциональное отображение коллажа ---
if processing_mode == "Создание коллажа":
    # ... (код отображения коллажа без изменений) ...
    coll_input_path = get_setting('paths.input_folder_path','')
    coll_filename = get_setting('paths.output_filename','')
    if coll_input_path and coll_filename and os.path.isdir(coll_input_path):
        coll_full_path = os.path.join(coll_input_path, coll_filename)
        if os.path.isfile(coll_full_path):
            st.divider(); st.subheader("Предпросмотр коллажа:")
            try:
                preview_key = f"collage_preview_{int(os.path.getmtime(coll_full_path))}"
                st.image(coll_full_path, use_container_width=True, key=preview_key)
            except Exception as img_e: st.warning(f"... {img_e}"); log.warning(f"... {img_e}")


log.debug("--- End of app script render cycle ---")