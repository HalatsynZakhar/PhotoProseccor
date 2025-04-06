# processing_workflows.py
import time
import os
import shutil
import math
import logging
import traceback
import gc # Для сборки мусора при MemoryError
from typing import Dict, Any, Optional, Tuple, List

# Используем абсолютный импорт (если все файлы в одной папке)
import image_utils
import config_manager # Может понадобиться для дефолтных значений в редких случаях

try:
    from natsort import natsorted
except ImportError:
    logging.warning("Библиотека natsort не найдена. Сортировка будет стандартной.")
    natsorted = sorted

from PIL import Image, UnidentifiedImageError, ImageFile, ImageDraw, ImageFont
ImageFile.LOAD_TRUNCATED_IMAGES = True

log = logging.getLogger(__name__) # Используем логгер, настроенный в app.py

# ==============================================================================
# === ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ДЛЯ ОБРАБОТКИ ИЗОБРАЖЕНИЙ (ШАГИ КОНВЕЙЕРА) ===
# ==============================================================================
# Эти функции инкапсулируют отдельные шаги обработки, вызываемые из
# run_individual_processing или _process_image_for_collage.

def _apply_preresize(img, preresize_width, preresize_height):
    """(Helper) Применяет предварительное уменьшение размера, сохраняя пропорции."""
    if not img or (preresize_width <= 0 and preresize_height <= 0):
        return img
    # ... (код функции _apply_preresize из предыдущего ответа, с log.*) ...
    prw = preresize_width if preresize_width > 0 else float('inf')
    prh = preresize_height if preresize_height > 0 else float('inf')
    ow, oh = img.size
    if ow <= 0 or oh <= 0 or (ow <= prw and oh <= prh):
        return img
    ratio = 1.0
    if ow > prw: ratio = min(ratio, prw / ow)
    if oh > prh: ratio = min(ratio, prh / oh)
    if ratio >= 1.0: return img
    nw = max(1, int(round(ow * ratio)))
    nh = max(1, int(round(oh * ratio)))
    log.info(f"  > Pre-resizing image from {ow}x{oh} to {nw}x{nh}")
    resized_img = None
    try:
        resized_img = img.resize((nw, nh), Image.Resampling.LANCZOS)
        if resized_img is not img: image_utils.safe_close(img)
        return resized_img
    except Exception as e:
        log.error(f"  ! Error during pre-resize to {nw}x{nh}: {e}")
        image_utils.safe_close(resized_img)
        return img

def _apply_force_aspect_ratio(img, aspect_ratio_tuple):
    """(Helper) Вписывает изображение в холст с заданным соотношением сторон."""
    if not img or not aspect_ratio_tuple: return img
    # ... (код функции _apply_force_aspect_ratio из предыдущего ответа, с log.*) ...
    if not (isinstance(aspect_ratio_tuple, (tuple, list)) and len(aspect_ratio_tuple) == 2): return img
    try:
        target_w_ratio, target_h_ratio = map(float, aspect_ratio_tuple)
        if target_w_ratio <= 0 or target_h_ratio <= 0: return img
    except (ValueError, TypeError): return img
    current_w, current_h = img.size
    if current_w <= 0 or current_h <= 0: return img
    target_aspect = target_w_ratio / target_h_ratio
    current_aspect = current_w / current_h
    if abs(current_aspect - target_aspect) < 0.001: return img
    log.info(f"  > Applying force aspect ratio {target_w_ratio}:{target_h_ratio}")
    if current_aspect > target_aspect: canvas_w, canvas_h = current_w, max(1, int(round(current_w / target_aspect)))
    else: canvas_w, canvas_h = max(1, int(round(current_h * target_aspect))), current_h
    canvas = None; img_rgba = None
    try:
        canvas = Image.new('RGBA', (canvas_w, canvas_h), (0, 0, 0, 0))
        paste_x, paste_y = (canvas_w - current_w) // 2, (canvas_h - current_h) // 2
        img_rgba = img if img.mode == 'RGBA' else img.convert('RGBA')
        canvas.paste(img_rgba, (paste_x, paste_y), mask=img_rgba)
        if img_rgba is not img: image_utils.safe_close(img_rgba)
        image_utils.safe_close(img)
        log.debug(f"    New size after aspect ratio: {canvas.size}")
        return canvas
    except Exception as e:
        log.error(f"  ! Error applying force aspect ratio: {e}")
        image_utils.safe_close(canvas)
        if img_rgba is not img: image_utils.safe_close(img_rgba)
        return img

def _apply_max_dimensions(img, max_width, max_height):
    """(Helper) Уменьшает изображение, если оно больше максимальных размеров."""
    if not img or (max_width <= 0 and max_height <= 0): return img
    # ... (код функции _apply_max_dimensions из предыдущего ответа, с log.*) ...
    max_w = max_width if max_width > 0 else float('inf')
    max_h = max_height if max_height > 0 else float('inf')
    ow, oh = img.size
    if ow <= 0 or oh <= 0 or (ow <= max_w and oh <= max_h): return img
    ratio = 1.0
    if ow > max_w: ratio = min(ratio, max_w / ow)
    if oh > max_h: ratio = min(ratio, max_h / oh)
    if ratio >= 1.0: return img
    nw, nh = max(1, int(round(ow * ratio))), max(1, int(round(oh * ratio)))
    log.info(f"  > Resizing to fit max dimensions: {ow}x{oh} -> {nw}x{nh}")
    resized_img = None
    try:
        resized_img = img.resize((nw, nh), Image.Resampling.LANCZOS)
        if resized_img is not img: image_utils.safe_close(img)
        return resized_img
    except Exception as e:
        log.error(f"  ! Error during max dimensions resize to {nw}x{nh}: {e}")
        image_utils.safe_close(resized_img)
        return img

def _apply_final_canvas_or_prepare(img, exact_width, exact_height, output_format, jpg_background_color):
    """(Helper) Применяет холст точного размера ИЛИ подготавливает режим для сохранения."""
    if not img: return None
    # ... (код функции _apply_final_canvas_or_prepare из предыдущего ответа, с log.*) ...
    ow, oh = img.size
    if ow <= 0 or oh <= 0: log.error("! Cannot process zero-size image for final step."); return None
    perform_final_canvas = exact_width > 0 and exact_height > 0
    if perform_final_canvas:
        log.info(f"  > Applying final canvas {exact_width}x{exact_height}")
        target_w, target_h = exact_width, exact_height
        final_canvas = None; resized_content = None; img_rgba_content = None; content_to_paste = None
        try:
            ratio = min(target_w / ow, target_h / oh) if ow > 0 and oh > 0 else 1.0
            content_nw, content_nh = max(1, int(round(ow * ratio))), max(1, int(round(oh * ratio)))
            resized_content = img.resize((content_nw, content_nh), Image.Resampling.LANCZOS)
            target_mode = 'RGBA' if output_format == 'png' else 'RGB'
            bg_color = (0, 0, 0, 0) if target_mode == 'RGBA' else tuple(jpg_background_color)
            final_canvas = Image.new(target_mode, (target_w, target_h), bg_color)
            paste_x, paste_y = (target_w - content_nw) // 2, (target_h - content_nh) // 2
            paste_mask = None; content_to_paste = resized_content
            if resized_content.mode in ('RGBA', 'LA', 'PA'):
                 img_rgba_content = resized_content.convert('RGBA')
                 paste_mask = img_rgba_content
                 content_to_paste = img_rgba_content.convert('RGB') if target_mode == 'RGB' else img_rgba_content
            elif target_mode == 'RGB' and resized_content.mode != 'RGB': content_to_paste = resized_content.convert('RGB')
            elif target_mode == 'RGBA' and resized_content.mode != 'RGBA': content_to_paste = resized_content.convert('RGBA')
            final_canvas.paste(content_to_paste, (paste_x, paste_y), mask=paste_mask)
            log.debug(f"    Final canvas created. Size: {final_canvas.size}, Mode: {final_canvas.mode}")
            image_utils.safe_close(img); image_utils.safe_close(resized_content)
            if img_rgba_content and img_rgba_content is not content_to_paste: image_utils.safe_close(img_rgba_content)
            if content_to_paste is not resized_content: image_utils.safe_close(content_to_paste)
            return final_canvas
        except Exception as e:
            log.error(f"  ! Error applying final canvas: {e}")
            image_utils.safe_close(final_canvas); image_utils.safe_close(resized_content)
            if img_rgba_content and img_rgba_content is not content_to_paste: image_utils.safe_close(img_rgba_content)
            if content_to_paste is not resized_content: image_utils.safe_close(content_to_paste)
            return img
    else: # Prepare mode for saving without final canvas
        log.debug("  > Final canvas disabled. Preparing mode for saving.")
        target_mode = 'RGBA' if output_format == 'png' else 'RGB'
        if img.mode == target_mode: log.debug(f"    Image already in target mode {target_mode}."); return img
        elif target_mode == 'RGBA':
            converted_img = None
            try: log.debug(f"    Converting {img.mode} -> RGBA"); converted_img = img.convert('RGBA'); image_utils.safe_close(img); return converted_img
            except Exception as e: log.error(f"    ! Failed to convert to RGBA: {e}"); image_utils.safe_close(converted_img); return img
        else: # target_mode == 'RGB'
            rgb_image = None; temp_rgba = None; image_to_paste = img; paste_mask = None
            try:
                log.info(f"    Preparing {img.mode} -> RGB with background {jpg_background_color}.")
                rgb_image = Image.new("RGB", img.size, tuple(jpg_background_color))
                if img.mode in ('RGBA', 'LA'): paste_mask = img
                elif img.mode == 'PA': temp_rgba = img.convert('RGBA'); paste_mask = temp_rgba; image_to_paste = temp_rgba
                rgb_image.paste(image_to_paste, (0, 0), mask=paste_mask)
                if temp_rgba is not img: image_utils.safe_close(temp_rgba)
                image_utils.safe_close(img)
                log.debug(f"    Prepared RGB image. Size: {rgb_image.size}")
                return rgb_image
            except Exception as e:
                log.error(f"    ! Failed preparing RGB background: {e}. Trying simple convert.")
                image_utils.safe_close(rgb_image); image_utils.safe_close(temp_rgba)
                converted_img = None
                try: log.debug("    Attempting simple RGB conversion as fallback."); converted_img = img.convert('RGB'); image_utils.safe_close(img); return converted_img
                except Exception as e_conv: log.error(f"    ! Simple RGB conversion failed: {e_conv}"); image_utils.safe_close(converted_img); return img


def _save_image(img, output_path, output_format, jpeg_quality):
    """(Helper) Сохраняет изображение в указанном формате с опциями."""
    if not img: log.error("! Cannot save None image."); return False
    
    log.info(f"_save_image called with output_path={output_path}, format={output_format}")
    
    if img.size[0] <= 0 or img.size[1] <= 0: 
        log.error(f"! Cannot save zero-size image {img.size} to {output_path}")
        return False
    
    log.info(f"  > Saving image to {output_path} (Format: {output_format.upper()})")
    log.debug(f"    Image details before save: Mode={img.mode}, Size={img.size}")
    
    output_dir = os.path.dirname(output_path)
    if not os.path.isdir(output_dir):
        log.error(f"  ! Output directory does not exist: {output_dir}")
        try:
            os.makedirs(output_dir, exist_ok=True)
            log.info(f"Created output directory: {output_dir}")
        except Exception as e:
            log.error(f"Failed to create output directory: {e}")
            return False
    
    if not os.access(output_dir, os.W_OK):
        log.error(f"  ! No write permission for output directory: {output_dir}")
        return False
    
    log.debug(f"    Output directory exists and seems writable: {output_dir}")
    
    save_options = {"optimize": True}
    img_to_save = img
    must_close_img_to_save = False
    
    if output_format == 'jpg':
        format_name = "JPEG"
        save_options["quality"] = int(jpeg_quality)
        save_options["subsampling"] = 0
        save_options["progressive"] = True
        if img.mode != 'RGB':
            log.warning(f"    Mode is {img.mode}, converting to RGB for JPEG save.")
            try: # Добавим try-except на случай ошибки конвертации
                img_to_save = img.convert('RGB')
                must_close_img_to_save = True
            except Exception as convert_err:
                 log.error(f"  ! Failed to convert image to RGB for JPEG save: {convert_err}")
                 return False # Не можем сохранить, если конвертация не удалась
    elif output_format == 'png':
        format_name = "PNG"
        save_options["compress_level"] = 6
        if img.mode != 'RGBA':
            log.warning(f"    Mode is {img.mode}, converting to RGBA for PNG save.")
            try: # Добавим try-except
                img_to_save = img.convert('RGBA')
                must_close_img_to_save = True
            except Exception as convert_err:
                 log.error(f"  ! Failed to convert image to RGBA for PNG save: {convert_err}")
                 return False
    else: 
        log.error(f"! Unsupported output format for saving: {output_format}")
        if must_close_img_to_save: image_utils.safe_close(img_to_save) # Закрываем временный объект, если создали
        return False

    # --- ПЕРВАЯ ПОПЫТКА: Стандартное сохранение ---
    save_success = False
    file_size_after_save = -1
    try:
        log.info(f"  > First attempt: Standard save for {os.path.basename(output_path)}")
        img_to_save.save(output_path, format_name, **save_options)
        if os.path.isfile(output_path):
            try: file_size_after_save = os.path.getsize(output_path)
            except Exception: file_size_after_save = -2
            if file_size_after_save > 0:
                save_success = True
                log.info(f"  > Standard save SUCCESSFUL. File exists: True, Size: {file_size_after_save} bytes")
            else:
                 log.warning(f"  > Standard save completed, but file size is {file_size_after_save}. Marking as FAILED.")
        else:
             log.warning(f"  > Standard save completed, but file not found immediately after save. Marking as FAILED.")

    except Exception as e:
        log.error(f"  ! Error during standard save: {e}")
    
    # --- ВТОРАЯ ПОПЫТКА: Сохранение во временную папку ---
    if not save_success:
        file_size_after_save = -1
        temp_path = None
        try:
            import tempfile
            temp_dir = tempfile.gettempdir()
            temp_filename = f"temp_img_save_{int(time.time())}_{os.path.basename(output_path)}"
            temp_path = os.path.join(temp_dir, temp_filename)
            
            log.info(f"  > Second attempt: Saving to temp file {temp_path}")
            
            img_to_save.save(temp_path, format_name, **save_options)
            
            if os.path.isfile(temp_path):
                log.info(f"  > Temp file saved successfully. Copying to final destination: {output_path}")
                import shutil
                shutil.copy2(temp_path, output_path)
                if os.path.isfile(output_path):
                    try: file_size_after_save = os.path.getsize(output_path)
                    except Exception: file_size_after_save = -2
                    if file_size_after_save > 0:
                        save_success = True
                        log.info(f"  > Temp file copy SUCCESSFUL. File exists: True, Size: {file_size_after_save} bytes")
                    else:
                        log.warning(f"  > Temp file copy completed, but final file size is {file_size_after_save}. Marking as FAILED.")
                else:
                    log.warning(f"  > Temp file copy completed, but final file not found. Marking as FAILED.")
            else:
                log.error(f"  ! Temp file not created at {temp_path}")
        except Exception as e:
            log.error(f"  ! Error during temp file save/copy: {e}")
        finally:
             if temp_path and os.path.exists(temp_path):
                try: os.remove(temp_path)
                except Exception as del_err:
                     log.warning(f"  ! Could not delete temp file {temp_path}: {del_err}")
    
    # --- ТРЕТЬЯ ПОПЫТКА: Прямая запись в байтовый поток ---
    if not save_success:
        file_size_after_save = -1
        try:
            log.info(f"  > Third attempt: BytesIO save and write")
            from io import BytesIO
            img_byte_arr = BytesIO()
            img_to_save.save(img_byte_arr, format=format_name, **save_options)
            img_byte_arr.seek(0)
            with open(output_path, 'wb') as f:
                f.write(img_byte_arr.getvalue())
            if os.path.isfile(output_path):
                try: file_size_after_save = os.path.getsize(output_path)
                except Exception: file_size_after_save = -2
                if file_size_after_save > 0:
                    save_success = True
                    log.info(f"  > BytesIO save SUCCESSFUL. File exists: True, Size: {file_size_after_save} bytes")
                else:
                    log.warning(f"  > BytesIO save completed, but file size is {file_size_after_save}. Marking as FAILED.")
            else:
                 log.warning(f"  > BytesIO save completed, but file not found. Marking as FAILED.")
        except Exception as e:
            log.error(f"  ! Error during BytesIO save: {e}")
    
    if must_close_img_to_save: image_utils.safe_close(img_to_save)
    
    if not save_success:
        log.error(f"  ! All save attempts failed for {output_path}")
        if os.path.isfile(output_path):
            try:
                size = os.path.getsize(output_path)
                if size <= 0:
                     log.warning(f"    Removing zero-byte file artifact: {output_path}")
                     os.remove(output_path)
            except Exception: pass 
        return False
    
    return True 

# ==============================================================================
# === ОСНОВНАЯ ФУНКЦИЯ: ОБРАБОТКА ОТДЕЛЬНЫХ ФАЙЛОВ =============================
# ==============================================================================

def run_individual_processing(**all_settings: Dict[str, Any]):
    """
    Оркестрирует обработку отдельных файлов: поиск, цикл, вызов image_utils,
    сохранение, переименование, удаление.
    Принимает все настройки как один словарь.
    """
    log.info("--- Starting Individual File Processing ---")
    start_time = time.time()

    # --- 1. Извлечение и Валидация Параметров ---
    log.debug("Extracting settings for individual mode...")
    try:
        paths_settings = all_settings.get('paths', {})
        prep_settings = all_settings.get('preprocessing', {})
        white_settings = all_settings.get('whitening', {})
        bgc_settings = all_settings.get('background_crop', {})
        pad_settings = all_settings.get('padding', {})
        ind_settings = all_settings.get('individual_mode', {})

        input_path = paths_settings.get('input_folder_path')
        output_path = paths_settings.get('output_folder_path')
        backup_folder_path = paths_settings.get('backup_folder_path')

        article_name = ind_settings.get('article_name') # Может быть '' или None
        delete_originals = ind_settings.get('delete_originals', False)
        output_format = str(ind_settings.get('output_format', 'jpg')).lower()
        jpeg_quality = int(ind_settings.get('jpeg_quality', 95))
        jpg_background_color = ind_settings.get('jpg_background_color', [255, 255, 255])
        force_aspect_ratio = ind_settings.get('force_aspect_ratio') # None или [W, H]
        max_output_width = int(ind_settings.get('max_output_width', 0))
        max_output_height = int(ind_settings.get('max_output_height', 0))
        final_exact_width = int(ind_settings.get('final_exact_width', 0))
        final_exact_height = int(ind_settings.get('final_exact_height', 0))

        enable_preresize = prep_settings.get('enable_preresize', False)
        preresize_width = int(prep_settings.get('preresize_width', 0)) if enable_preresize else 0
        preresize_height = int(prep_settings.get('preresize_height', 0)) if enable_preresize else 0

        enable_whitening = white_settings.get('enable_whitening', False)
        whitening_cancel_threshold = int(white_settings.get('whitening_cancel_threshold', 550))

        enable_bg_crop = bgc_settings.get('enable_bg_crop', False)
        white_tolerance = int(bgc_settings.get('white_tolerance', 0)) if enable_bg_crop else None # None если выключено
        crop_symmetric_absolute = bool(bgc_settings.get('crop_symmetric_absolute', False)) if enable_bg_crop else False
        crop_symmetric_axes = bool(bgc_settings.get('crop_symmetric_axes', False)) if enable_bg_crop else False

        enable_padding = pad_settings.get('enable_padding', False)
        padding_percent = float(pad_settings.get('padding_percent', 0.0)) if enable_padding else 0.0
        perimeter_margin = int(pad_settings.get('perimeter_margin', 0)) if enable_padding else 0
        allow_expansion = bool(pad_settings.get('allow_expansion', True)) if enable_padding else False

        # Дополнительная валидация
        if output_format not in ['jpg', 'png']:
            raise ValueError(f"Unsupported output format: {output_format}")
        if not input_path or not output_path:
            raise ValueError("Input or Output path is missing.")

        # Конвертация в кортежи где нужно
        valid_jpg_bg = tuple(jpg_background_color) if isinstance(jpg_background_color, list) else (255, 255, 255)
        valid_aspect_ratio = tuple(force_aspect_ratio) if force_aspect_ratio else None

        log.debug("Settings extracted successfully.")

    except (KeyError, ValueError, TypeError) as e:
        log.critical(f"Error processing settings: {e}. Aborting.", exc_info=True)
        return

    # --- 2. Подготовка Путей и Папок ---
    abs_input_path = os.path.abspath(input_path)
    abs_output_path = os.path.abspath(output_path)
    abs_backup_path = os.path.abspath(backup_folder_path) if backup_folder_path and str(backup_folder_path).strip() else None

    if not os.path.isdir(abs_input_path):
        log.error(f"Input path is not a valid directory: {abs_input_path}"); return

    backup_enabled = False
    if abs_backup_path:
        if abs_backup_path == abs_input_path or abs_backup_path == abs_output_path:
             log.warning(f"Backup path is same as input/output. Disabling backup.")
        else:
             try:
                 if not os.path.exists(abs_backup_path): os.makedirs(abs_backup_path); log.info(f"Created backup dir: {abs_backup_path}")
                 elif not os.path.isdir(abs_backup_path): log.error(f"Backup path not a directory: {abs_backup_path}");
                 else: backup_enabled = True # Папка существует и это директория
             except Exception as e: log.error(f"Error creating backup dir {abs_backup_path}: {e}")

    safe_to_delete = abs_input_path != abs_output_path
    effective_delete_originals = delete_originals and safe_to_delete
    if delete_originals and not safe_to_delete: log.warning("Deletion disabled: input/output paths are same.")

    try: # Создание папки результатов
        if not os.path.exists(abs_output_path): os.makedirs(abs_output_path); log.info(f"Created output dir: {abs_output_path}")
        elif not os.path.isdir(abs_output_path): log.error(f"Output path not a directory: {abs_output_path}"); return
    except Exception as e: log.error(f"Error creating output dir {abs_output_path}: {e}"); return

    # --- 3. Логирование Параметров ---
    log.info("--- Processing Parameters (Individual Mode) ---")
    log.info(f"Input Path: {abs_input_path}")
    log.info(f"Output Path: {abs_output_path}")
    log.info(f"Backup Path: {abs_backup_path if backup_enabled else 'Disabled'}")
    log.info(f"Article (Renaming): {article_name or 'Disabled'}")
    log.info(f"Delete Originals: {effective_delete_originals}")
    log.info(f"Output Format: {output_format.upper()}")
    if output_format == 'jpg': log.info(f"  JPG Bg: {valid_jpg_bg}, Quality: {jpeg_quality}")
    log.info("-" * 10 + " Steps " + "-" * 10)
    log.info(f"1. Preresize: {'Enabled' if enable_preresize else 'Disabled'} (W:{preresize_width}, H:{preresize_height})")
    log.info(f"2. Whitening: {'Enabled' if enable_whitening else 'Disabled'} (Thresh:{whitening_cancel_threshold})")
    log.info(f"3. BG Removal/Crop: {'Enabled' if enable_bg_crop else 'Disabled'} (Tol:{white_tolerance})")
    if enable_bg_crop: log.info(f"  Crop Symmetry: Abs={crop_symmetric_absolute}, Axes={crop_symmetric_axes}")
    log.info(f"4. Padding: {'Enabled' if enable_padding else 'Disabled'} (%:{padding_percent}, Margin:{perimeter_margin}, Expand:{allow_expansion})")
    log.info(f"5. Force Aspect Ratio: {str(valid_aspect_ratio) or 'Disabled'}")
    log.info(f"6. Max Dimensions: W:{max_output_width or 'N/A'}, H:{max_output_height or 'N/A'}")
    log.info(f"7. Final Exact Canvas: W:{final_exact_width or 'N/A'}, H:{final_exact_height or 'N/A'}")
    log.info("-" * 25)

    # --- 4. Поиск Файлов ---
    try:
        all_entries = os.listdir(abs_input_path)
        SUPPORTED_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.bmp', '.gif', '.tiff', '.webp', '.tif')
        files_unsorted = [f for f in all_entries if os.path.isfile(os.path.join(abs_input_path, f)) and not f.startswith(("__temp_", ".")) and f.lower().endswith(SUPPORTED_EXTENSIONS)]
        files = natsorted(files_unsorted)
        log.info(f"Found {len(files)} files to process.")
        if not files: return
    except Exception as e: log.error(f"Error reading input directory {abs_input_path}: {e}"); return

    # --- 5. Инициализация для Цикла ---
    processed_files_count = 0; skipped_files_count = 0; error_files_count = 0
    source_files_to_potentially_delete = []
    processed_output_file_map = {} # {final_output_path: original_basename}
    output_ext = f".{output_format}"

    # --- 6. Основной Цикл Обработки ---
    total_files = len(files)
    for file_index, file in enumerate(files):
        source_file_path = os.path.join(abs_input_path, file)
        log.info(f"--- [{file_index + 1}/{total_files}] Processing: {file} ---")
        img_current = None
        original_basename = os.path.splitext(file)[0]
        success_flag = False # Успех для текущего файла

        try:
            # 6.1. Бекап
            if backup_enabled:
                try: shutil.copy2(source_file_path, os.path.join(abs_backup_path, file)); log.debug("  > Backup created.")
                except Exception as backup_err: log.error(f"  ! Backup failed for {file}: {backup_err}")

            # 6.2. Открытие
            try:
                with Image.open(source_file_path) as img_opened:
                    img_opened.load()
                    img_current = img_opened.copy()
                    log.debug(f"  > Opened. Orig size: {img_current.size}, Mode: {img_current.mode}")
            except UnidentifiedImageError: log.error(f"  ! Cannot identify image: {file}"); skipped_files_count += 1; continue
            except FileNotFoundError: log.error(f"  ! File not found during open: {file}"); skipped_files_count += 1; continue
            except Exception as open_err: log.error(f"  ! Error opening {file}: {open_err}", exc_info=True); error_files_count += 1; continue
            if not img_current or img_current.size[0] <= 0 or img_current.size[1] <= 0:
                log.error(f"  ! Image empty/zero size after open: {file}"); error_files_count += 1; image_utils.safe_close(img_current); continue

            # --- Конвейер Обработки ---
            step_counter = 1
            log.debug(f"  Step {step_counter}: Pre-resize")
            if enable_preresize: img_current = _apply_preresize(img_current, preresize_width, preresize_height)
            if not img_current: raise ValueError("Image became None after pre-resize.")
            step_counter += 1

            log.debug(f"  Step {step_counter}: Whitening")
            if enable_whitening:
                 img_original = img_current
                 img_current = image_utils.whiten_image_by_darkest_perimeter(img_current, whitening_cancel_threshold)
                 if img_current is not img_original: log.debug("    Whitening applied.")
            if not img_current: raise ValueError("Image became None after whitening.")
            step_counter += 1

            # Периметр (только если нужно для полей)
            perimeter_is_white = False
            if enable_padding and perimeter_margin > 0:
                 log.debug(f"  Step {step_counter}.{1}: Perimeter check")
                 current_perimeter_tolerance = white_tolerance if enable_bg_crop else 0
                 perimeter_is_white = image_utils.check_perimeter_is_white(img_current, current_perimeter_tolerance, perimeter_margin)
            step_counter += 1 # Считаем как шаг, даже если проверка не делалась

            pre_crop_width, pre_crop_height = img_current.size

            log.debug(f"  Step {step_counter}: BG Removal / Crop (Enabled: {enable_bg_crop})")
            cropped_image_dimensions = img_current.size # Запомним размер ДО
            if enable_bg_crop:
                img_original = img_current
                img_current = image_utils.remove_white_background(img_current, white_tolerance)
                if not img_current: raise ValueError("Image became None after background removal.")
                if img_current is not img_original: log.debug("    Background removed/converted.")

                img_original = img_current # Обновляем для сравнения после обрезки
                img_current = image_utils.crop_image(img_current, crop_symmetric_axes, crop_symmetric_absolute)
                if not img_current: raise ValueError("Image became None after cropping.")
                if img_current is not img_original: log.debug("    Cropping applied.")
                cropped_image_dimensions = img_current.size # Обновляем размер ПОСЛЕ обрезки
            step_counter += 1

            log.debug(f"  Step {step_counter}: Padding (Enabled: {enable_padding})")
            apply_padding = False
            if enable_padding:
                 condition_perimeter = (perimeter_margin <= 0 or perimeter_is_white)
                 if condition_perimeter:
                     current_w, current_h = cropped_image_dimensions
                     if current_w > 0 and current_h > 0 and padding_percent > 0:
                          padding_pixels = int(round(max(current_w, current_h) * (padding_percent / 100.0)))
                          if padding_pixels > 0:
                               potential_padded_w = current_w + 2 * padding_pixels
                               potential_padded_h = current_h + 2 * padding_pixels
                               size_check_passed = (potential_padded_w <= pre_crop_width and potential_padded_h <= pre_crop_height)
                               if allow_expansion or size_check_passed: apply_padding = True; log.debug("    Padding will be applied.")
                               else: log.debug("    Padding skipped (size check failed and expansion disabled)")
                          else: log.debug("    Padding skipped (zero pixels)")
                     else: log.debug("    Padding skipped (zero size)")
                 else: log.debug("    Padding skipped (perimeter check failed)")

            if apply_padding:
                img_original = img_current
                img_current = image_utils.add_padding(img_current, padding_percent, bg_color=(0, 0, 0, 0))
                if not img_current: raise ValueError("Image became None after padding.")
                if img_current is not img_original: log.info(f"    Padding applied. New size: {img_current.size}")
            step_counter += 1

            log.debug(f"  Step {step_counter}: Force Aspect Ratio")
            if valid_aspect_ratio: img_current = _apply_force_aspect_ratio(img_current, valid_aspect_ratio)
            if not img_current: raise ValueError("Image became None after force aspect ratio.")
            step_counter += 1

            log.debug(f"  Step {step_counter}: Max Dimensions")
            if max_output_width > 0 or max_output_height > 0: img_current = _apply_max_dimensions(img_current, max_output_width, max_output_height)
            if not img_current: raise ValueError("Image became None after max dimensions.")
            step_counter += 1

            log.debug(f"  Step {step_counter}: Final Canvas / Prepare")
            img_current = _apply_final_canvas_or_prepare(img_current, final_exact_width, final_exact_height, output_format, valid_jpg_bg)
            if not img_current: raise ValueError("Image became None after final canvas/prepare step.")
            step_counter += 1

            # 6.3. Сохранение
            log.debug(f"  Step {step_counter}: Saving")
            temp_output_filename = f"{original_basename}{output_ext}"
            final_output_path = os.path.join(abs_output_path, temp_output_filename)
            save_successful = _save_image(img_current, final_output_path, output_format, jpeg_quality)

            if save_successful:
                processed_files_count += 1
                success_flag = True
                processed_output_file_map[final_output_path] = original_basename
                if os.path.exists(source_file_path) and source_file_path not in source_files_to_potentially_delete:
                     source_files_to_potentially_delete.append(source_file_path)
            else:
                error_files_count += 1
                log.error(f"Failed to save processed file: {file}")

        # --- Обработка Ошибок для Файла ---
        except MemoryError as e:
             log.critical(f"!!! MEMORY ERROR processing {file}: {e}. Attempting GC.", exc_info=True)
             error_files_count += 1; gc.collect(); success_flag = False
        except ValueError as e: # Ловим наши ошибки None
             log.error(f"!!! PROCESSING error for {file}: {e}", exc_info=False) # Не нужен полный трейсбек
             error_files_count += 1; success_flag = False
        except Exception as e:
             log.critical(f"!!! UNEXPECTED error processing {file}: {e}", exc_info=True)
             error_files_count += 1; success_flag = False
        finally:
            image_utils.safe_close(img_current) # Закрываем в любом случае
            if not success_flag and source_file_path in source_files_to_potentially_delete:
                 try: source_files_to_potentially_delete.remove(source_file_path); log.warning(f"  Removed {os.path.basename(source_file_path)} from deletion list due to error.")
                 except ValueError: pass
            log.info(f"--- Finished processing: {file} {'(Success)' if success_flag else '(Failed)'} ---")


    # --- 7. Финальные Действия (Статистика, Удаление, Переименование) ---
    log.info("\n" + "=" * 30)
    log.info("--- Final Summary ---")
    log.info(f"Successfully processed: {processed_files_count}")
    log.info(f"Skipped (unreadable/not found): {skipped_files_count}")
    log.info(f"Errors during processing/saving: {error_files_count}")
    log.info(f"Total analyzed: {processed_files_count + skipped_files_count + error_files_count} / {total_files}")
    total_time = time.time() - start_time
    log.info(f"Total processing time: {total_time:.2f} seconds")

    # 7.1. Удаление оригиналов
    if effective_delete_originals and source_files_to_potentially_delete:
        log.info(f"\n--- Deleting {len(source_files_to_potentially_delete)} original files from '{abs_input_path}' ---")
        removed_count = 0; remove_errors = 0
        for file_to_remove in list(source_files_to_potentially_delete):
            try:
                if os.path.exists(file_to_remove): os.remove(file_to_remove); removed_count += 1; log.debug(f"  Deleted: {os.path.basename(file_to_remove)}")
                else: log.warning(f"  File to delete not found: {os.path.basename(file_to_remove)}")
            except Exception as remove_error: log.error(f"  Error deleting {os.path.basename(file_to_remove)}: {remove_error}"); remove_errors += 1
        log.info(f"  -> Successfully deleted: {removed_count}. Deletion errors: {remove_errors}.")
        source_files_to_potentially_delete.clear()
    elif delete_originals: log.info("\n--- Deletion of originals skipped (check paths or successful processing). ---")
    else: log.info("\n--- Deletion of originals disabled. ---")

    # 7.2. Переименование
    enable_renaming_actual = bool(article_name and str(article_name).strip())
    if enable_renaming_actual and processed_output_file_map:
        log.info(f"\n--- Renaming {len(processed_output_file_map)} files in '{abs_output_path}' using article '{article_name}' ---")
        files_to_rename = list(processed_output_file_map.items()) # [(path, orig_basename), ...]
        if not files_to_rename: log.info("  No files available for renaming stage.")
        else:
            # ... (Полный код переименования с двумя этапами и логированием, как в предыдущем ответе) ...
            try: sorted_files_for_rename = natsorted(files_to_rename, key=lambda item: item[1])
            except Exception as sort_err: log.error(f"! Error sorting for renaming: {sort_err}"); sorted_files_for_rename = files_to_rename
            temp_rename_map = {}; rename_step1_errors = 0; temp_prefix = f"__temp_{os.getpid()}_"; log.info("  Step 1: Renaming to temporary names...")
            for i, (current_path, original_basename) in enumerate(sorted_files_for_rename):
                temp_filename = f"{temp_prefix}{i}_{original_basename}{output_ext}"; temp_path = os.path.join(abs_output_path, temp_filename)
                try: log.debug(f"    '{os.path.basename(current_path)}' -> '{temp_filename}'"); os.rename(current_path, temp_path); temp_rename_map[temp_path] = original_basename
                except Exception as rename_error: log.error(f"  ! Temp rename error for '{os.path.basename(current_path)}': {rename_error}"); rename_step1_errors += 1
            if rename_step1_errors > 0: log.warning(f"  ! Temp renaming errors: {rename_step1_errors}")
            log.info("  Step 2: Renaming to final names...")
            rename_step2_errors = 0; renamed_final_count = 0; occupied_final_names = set()
            existing_temp_paths = [p for p, ob in temp_rename_map.items() if os.path.exists(p)]
            if not existing_temp_paths: log.warning("  ! No temporary files found for final renaming.")
            else:
                all_temp_files_sorted = sorted(existing_temp_paths)
                found_exact_match = False; exact_match_orig_name = None
                for temp_p in all_temp_files_sorted:
                     orig_bn = temp_rename_map.get(temp_p)
                     if orig_bn and orig_bn.lower() == str(article_name).lower(): found_exact_match = True; exact_match_orig_name = orig_bn; log.info(f"    * Found exact match for '{article_name}' (original: '{orig_bn}')."); break
                if not found_exact_match: log.info(f"    * Exact match for '{article_name}' not found.")
                base_name_assigned = False; numeric_counter = 1
                for temp_path in all_temp_files_sorted:
                    original_basename = temp_rename_map.get(temp_path, "unknown_original")
                    target_filename = None; target_path = None; assign_base = False
                    is_exact_match = original_basename.lower() == str(article_name).lower()
                    if is_exact_match and not base_name_assigned: assign_base = True; log.debug(f"    Assigning base name '{article_name}' to exact match '{original_basename}'.")
                    elif not found_exact_match and not base_name_assigned: assign_base = True; log.debug(f"    Assigning base name '{article_name}' to first file '{original_basename}'.")
                    if assign_base:
                        target_filename = f"{article_name}{output_ext}"; target_path = os.path.join(abs_output_path, target_filename); norm_target_path = os.path.normcase(target_path)
                        if norm_target_path in occupied_final_names or (os.path.exists(target_path) and os.path.normcase(temp_path) != norm_target_path): log.warning(f"    ! Conflict: Base name '{target_filename}' exists/occupied. Numbering."); assign_base = False
                        else: base_name_assigned = True
                    if not assign_base:
                        while True:
                            target_filename = f"{article_name}_{numeric_counter}{output_ext}"; target_path = os.path.join(abs_output_path, target_filename); norm_target_path = os.path.normcase(target_path)
                            if norm_target_path not in occupied_final_names and not (os.path.exists(target_path) and os.path.normcase(temp_path) != norm_target_path): break
                            numeric_counter += 1
                        numeric_counter += 1
                    try: log.debug(f"    '{os.path.basename(temp_path)}' -> '{target_filename}'"); os.rename(temp_path, target_path); renamed_final_count += 1; occupied_final_names.add(os.path.normcase(target_path))
                    except Exception as rename_error: log.error(f"    ! Final renaming error '{os.path.basename(temp_path)}' -> '{target_filename}': {rename_error}"); rename_step2_errors += 1
            log.info(f"  -> Files renamed: {renamed_final_count}. Step 2 errors: {rename_step2_errors}.")
            try:
                remaining_temp = [f for f in os.listdir(abs_output_path) if f.startswith(temp_prefix) and os.path.isfile(os.path.join(abs_output_path, f))]
                if remaining_temp: log.warning(f"  ! Temp files might remain: {remaining_temp}")
            except Exception as list_err: log.error(f"! Could not check for remaining temp files: {list_err}")
    elif enable_renaming_actual: log.info("\n--- Renaming skipped: No files successfully processed. ---")
    else: log.info("\n--- Renaming disabled. ---")

    log.info("=" * 30)
    log.info("--- Individual File Processing Function Finished ---")


# ==============================================================================
# === ОСНОВНАЯ ФУНКЦИЯ: СОЗДАНИЕ КОЛЛАЖА =======================================
# ==============================================================================

def _process_image_for_collage(image_path: str, prep_settings, white_settings, bgc_settings, pad_settings) -> Optional[Image.Image]:
    """
    (Helper) Обрабатывает ОДНО изображение для коллажа, используя image_utils.
    Возвращает объект PIL.Image (RGBA) или None при ошибке.
    """
    log.debug(f"-- Processing for collage: {os.path.basename(image_path)}")
    img_current = None
    # ... (код функции _process_image_for_collage из предыдущего ответа) ...
    try:
        enable_preresize = prep_settings.get('enable_preresize', False)
        preresize_width = int(prep_settings.get('preresize_width', 0)) if enable_preresize else 0
        preresize_height = int(prep_settings.get('preresize_height', 0)) if enable_preresize else 0
        enable_whitening = white_settings.get('enable_whitening', False)
        whitening_cancel_threshold = int(white_settings.get('whitening_cancel_threshold', 550))
        enable_bg_crop = bgc_settings.get('enable_bg_crop', False)
        white_tolerance = int(bgc_settings.get('white_tolerance', 0)) if enable_bg_crop else None
        crop_symmetric_absolute = bool(bgc_settings.get('crop_symmetric_absolute', False)) if enable_bg_crop else False
        crop_symmetric_axes = bool(bgc_settings.get('crop_symmetric_axes', False)) if enable_bg_crop else False
        enable_padding = pad_settings.get('enable_padding', False)
        padding_percent = float(pad_settings.get('padding_percent', 0.0)) if enable_padding else 0.0
        perimeter_margin = int(pad_settings.get('perimeter_margin', 0)) if enable_padding else 0 # Не используется в логике ниже, но извлекаем
        allow_expansion = bool(pad_settings.get('allow_expansion', True)) if enable_padding else False

        # 1. Открытие и конвертация
        try:
            with Image.open(image_path) as img_opened: img_opened.load(); img_current = img_opened.convert('RGBA')
        except Exception as e: log.error(f"    ! Open/convert error: {e}"); return None
        if not img_current or img_current.size[0]<=0: log.error("    ! Zero size after open."); return None
        log.debug(f"    Opened RGBA Size: {img_current.size}")

        # 2. Пре-ресайз
        if enable_preresize: img_current = _apply_preresize(img_current, preresize_width, preresize_height)
        if not img_current: return None

        # 3. Отбеливание
        if enable_whitening: img_current = image_utils.whiten_image_by_darkest_perimeter(img_current, whitening_cancel_threshold)
        if not img_current: return None

        pre_crop_width, pre_crop_height = img_current.size

        # 4 & 5. Фон/Обрезка
        cropped_image_dimensions = img_current.size
        if enable_bg_crop:
            img_current = image_utils.remove_white_background(img_current, white_tolerance)
            if not img_current: return None
            img_current = image_utils.crop_image(img_current, crop_symmetric_axes, crop_symmetric_absolute)
            if not img_current: return None
            cropped_image_dimensions = img_current.size
            log.debug(f"    Size after BG/Crop: {cropped_image_dimensions}")

        # 6. Поля
        apply_padding = False
        if enable_padding:
             current_w, current_h = cropped_image_dimensions
             if current_w > 0 and current_h > 0 and padding_percent > 0:
                  padding_pixels = int(round(max(current_w, current_h) * (padding_percent / 100.0)))
                  if padding_pixels > 0:
                       potential_padded_w = current_w + 2 * padding_pixels; potential_padded_h = current_h + 2 * padding_pixels
                       size_check_passed = (potential_padded_w <= pre_crop_width and potential_padded_h <= pre_crop_height)
                       if allow_expansion or size_check_passed: apply_padding = True
                       else: log.debug("    Padding skipped (size check failed & expansion disabled)")
                  else: log.debug("    Padding skipped (zero pixels)")
             else: log.debug("    Padding skipped (zero size)")

        if apply_padding:
            img_original = img_current
            img_current = image_utils.add_padding(img_current, padding_percent, bg_color=(0, 0, 0, 0))
            if not img_current: return None
            log.debug(f"    Padding applied. New size: {img_current.size}")

        # 7. Проверка RGBA
        if img_current.mode != 'RGBA':
             try: img_tmp = img_current.convert("RGBA"); image_utils.safe_close(img_current); img_current = img_tmp
             except Exception as e: log.error(f"    ! Final RGBA conversion failed: {e}"); return None

        log.debug(f"-- Finished processing for collage: {os.path.basename(image_path)}")
        return img_current

    except Exception as e:
        log.critical(f"!!! UNEXPECTED error in _process_image_for_collage for {os.path.basename(image_path)}: {e}", exc_info=True)
        image_utils.safe_close(img_current)
        return None


def run_collage_processing(**all_settings: Dict[str, Any]):
    """
    Создает коллаж из изображений в указанной папке.

    Параметры берутся из словаря all_settings, который содержит:
    - paths.input_folder_path: путь к папке с исходными изображениями
    - paths.output_filename: имя файла для сохранения коллажа
    - collage_mode.*: различные настройки для создания коллажа
    - preprocessing.*, whitening.*, background_crop.*, padding.*: настройки для обработки отдельных изображений перед коллажем
    """
    log.info("--- Starting Collage Processing ---")
    start_time = time.time()

    try:
        # --- 1. Извлечение параметров ---
        paths_settings = all_settings.get('paths', {})
        collage_settings = all_settings.get('collage_mode', {})
        prep_settings = all_settings.get('preprocessing', {})
        white_settings = all_settings.get('whitening', {}) # Добавлено извлечение настроек отбеливания
        bgc_settings = all_settings.get('background_crop', {})
        pad_settings = all_settings.get('padding', {})

        source_dir = paths_settings.get('input_folder_path', '')
        output_filename = paths_settings.get('output_filename', '')

        # Получаем другие параметры из настроек коллажа
        output_format = str(collage_settings.get('output_format', 'jpg')).lower()
        jpeg_quality = int(collage_settings.get('jpeg_quality', 95))
        forced_cols = int(collage_settings.get('forced_cols', 0))
        spacing_percent = float(collage_settings.get('spacing_percent', 2.0))
        bg_color_tuple = tuple(collage_settings.get('jpg_background_color', [255, 255, 255]))

        # Параметры для финальной обработки коллажа
        force_collage_aspect_ratio = collage_settings.get('force_collage_aspect_ratio', None)
        max_collage_width = int(collage_settings.get('max_collage_width', 0))
        max_collage_height = int(collage_settings.get('max_collage_height', 0))
        final_collage_exact_width = int(collage_settings.get('final_collage_exact_width', 0))
        final_collage_exact_height = int(collage_settings.get('final_collage_exact_height', 0))

        log.info(f"Parameters: source_dir={source_dir}, output_filename={output_filename}, format={output_format}")

        # Проверка наличия обязательных параметров
        if not source_dir or not output_filename:
            error_msg = "Source directory or output filename missing"
            log.error(error_msg)
            raise ValueError(error_msg)

        # --- 2. Подготовка путей ---
        # Стандартизируем имя выходного файла
        base_name = os.path.splitext(output_filename)[0]
        file_ext = ".jpg" if output_format == "jpg" else ".png"
        output_filename = base_name + file_ext

        # Создаем абсолютные пути
        abs_source_dir = os.path.abspath(source_dir)
        output_path = os.path.join(abs_source_dir, output_filename)

        log.info(f"Input folder: {abs_source_dir}")
        log.info(f"Output path: {output_path}")

        # --- 3. Проверка директорий и прав доступа ---
        if not os.path.isdir(abs_source_dir):
            error_msg = f"Source directory not found: {abs_source_dir}"
            log.error(error_msg)
            raise ValueError(error_msg) # Используем ValueError для консистентности

        # Проверка прав на запись
        try:
            test_file = os.path.join(abs_source_dir, "_test_permissions.txt")
            with open(test_file, 'w') as f:
                f.write("Test write permission")
            os.remove(test_file)
            log.info("Test file created and removed successfully")
        except Exception as e:
            error_msg = f"Permission test failed in '{abs_source_dir}': {e}" # Уточняем папку
            log.error(error_msg)
            raise PermissionError(error_msg) # Перебрасываем как PermissionError

        # --- 4. Сбор и обработка изображений ---
        supported_extensions = ('.png', '.jpg', '.jpeg', '.bmp', '.gif')
        image_files = [f for f in os.listdir(abs_source_dir)
                     if os.path.isfile(os.path.join(abs_source_dir, f))
                     and f.lower().endswith(supported_extensions)
                     and not f.startswith("_test_") # Игнорируем тестовые файлы
                     and os.path.normcase(os.path.join(abs_source_dir, f)) != os.path.normcase(output_path)] # Игнорируем сам будущий коллаж

        if not image_files:
            error_msg = f"No suitable image files found in {abs_source_dir}"
            log.error(error_msg)
            raise ValueError(error_msg)

        # Сортируем файлы
        try:
            image_files = natsorted(image_files)
            log.info(f"Found {len(image_files)} image files (natsorted) for processing")
        except NameError:
             image_files = sorted(image_files)
             log.info(f"Found {len(image_files)} image files (standard sorted) for processing")

        # Обрабатываем каждое изображение
        processed_images = []
        log.info("Starting individual image processing for collage...")

        for i, img_file in enumerate(image_files):
            img_path = os.path.join(abs_source_dir, img_file)
            log.info(f"Processing image {i+1}/{len(image_files)}: {img_file}")

            try:
                # Вызываем _process_image_for_collage
                processed_img = _process_image_for_collage(
                    image_path=img_path,
                    prep_settings=prep_settings,
                    white_settings=white_settings, # Передаем настройки отбеливания
                    bgc_settings=bgc_settings,
                    pad_settings=pad_settings
                )

                if processed_img:
                    processed_images.append(processed_img)
                    log.info(f"  > Successfully processed: {img_file} -> new size {processed_img.size}")
                else:
                    log.warning(f"  ! Failed to process image {img_file}, skipping.")

            except Exception as e:
                log.error(f"  ! Critical error processing image {img_file}: {e}", exc_info=True)
                # Продолжаем со следующими файлами

        if not processed_images:
            error_msg = "No images could be processed for the collage"
            log.error(error_msg)
            raise ValueError(error_msg)

        log.info(f"Successfully processed {len(processed_images)} images for the collage.")

        # --- 5. Определение размеров коллажа ---
        num_images_for_collage = len(processed_images)
        cols = forced_cols if forced_cols > 0 else int(pow(num_images_for_collage, 0.5) + 0.5)
        rows = (num_images_for_collage + cols - 1) // cols
        log.info(f"Grid size for collage: {cols}x{rows}")

        max_width = max(img.width for img in processed_images) if processed_images else 1
        max_height = max(img.height for img in processed_images) if processed_images else 1
        log.info(f"Max cell dimensions from processed images: {max_width}x{max_height}")

        spacing_px = int(max(max_width, max_height) * (spacing_percent / 100.0))
        collage_width = cols * max_width + (cols + 1) * spacing_px
        collage_height = rows * max_height + (rows + 1) * spacing_px
        log.info(f"Creating collage canvas: {collage_width}x{collage_height}, cell: {max_width}x{max_height}, spacing: {spacing_px}px")

        # --- 6. Создание коллажа ---
        collage_mode = 'RGBA' if output_format == 'png' else 'RGB'
        collage_bg = (0, 0, 0, 0) if collage_mode == 'RGBA' else bg_color_tuple
        collage = Image.new(collage_mode, (collage_width, collage_height), collage_bg)

        for i, img in enumerate(processed_images):
            row = i // cols
            col = i % cols
            x = spacing_px + col * (max_width + spacing_px)
            y = spacing_px + row * (max_height + spacing_px)
            x_offset = (max_width - img.width) // 2
            y_offset = (max_height - img.height) // 2
            paste_pos = (x + x_offset, y + y_offset)
            log.debug(f"Pasting image {i} (size {img.size}) at {paste_pos} on canvas {collage.size}")

            try:
                paste_mask = None
                image_to_paste = img
                if img.mode in ('RGBA', 'LA', 'P'):
                    try:
                         paste_mask = img.getchannel('A')
                         if collage_mode == 'RGB':
                              temp_bg_patch = Image.new('RGB', img.size, bg_color_tuple)
                              temp_bg_patch.paste(img, (0,0), mask=paste_mask)
                              image_to_paste = temp_bg_patch
                              paste_mask = None
                         log.debug(f"  Using alpha mask for image {i}")
                    except ValueError:
                         log.debug(f"  Image {i} is {img.mode} but has no alpha channel?")
                         if collage_mode == 'RGB' and img.mode != 'RGB': image_to_paste = img.convert('RGB')
                         elif collage_mode == 'RGBA' and img.mode != 'RGBA': image_to_paste = img.convert('RGBA')
                elif collage_mode == 'RGB' and img.mode != 'RGB': image_to_paste = img.convert('RGB')
                elif collage_mode == 'RGBA' and img.mode != 'RGBA': image_to_paste = img.convert('RGBA')

                collage.paste(image_to_paste, paste_pos, mask=paste_mask)
                if image_to_paste is not img: image_utils.safe_close(image_to_paste)

            except Exception as e:
                log.warning(f"Error pasting processed image {i}: {e}", exc_info=True)

        for img in processed_images: image_utils.safe_close(img) # Закрываем обработанные

        # --- 7. Финальная обработка коллажа ---
        log.info("Applying final adjustments to the generated collage...")

        if force_collage_aspect_ratio:
             collage = _apply_force_aspect_ratio(collage, force_collage_aspect_ratio)
             if not collage: raise ValueError("Collage became None after force aspect ratio")
             log.info(f"Collage size after aspect ratio: {collage.size}")

        if max_collage_width > 0 or max_collage_height > 0:
             collage = _apply_max_dimensions(collage, max_collage_width, max_collage_height)
             if not collage: raise ValueError("Collage became None after max dimensions")
             log.info(f"Collage size after max dimensions: {collage.size}")

        collage = _apply_final_canvas_or_prepare(collage,
                                                 final_collage_exact_width,
                                                 final_collage_exact_height,
                                                 output_format,
                                                 bg_color_tuple)
        if not collage:
            error_msg = "Collage became None after final canvas/prepare step"
            log.error(error_msg)
            raise ValueError(error_msg)
        log.info(f"Collage size after final canvas/prepare: {collage.size}, Mode: {collage.mode}")

        # --- 8. Сохранение финального коллажа ---
        log.info(f"Attempting to save final collage to {output_path}")
        save_success = _save_image(collage, output_path, output_format, jpeg_quality)
        image_utils.safe_close(collage) # Закрываем финальный коллаж

        # === ДОПОЛНИТЕЛЬНАЯ ПРОВЕРКА ПОСЛЕ ВЫЗОВА _save_image ===
        final_check_passed = False
        if save_success:
            log.info("  _save_image reported SUCCESS. Performing final verification...")
            try:
                if os.path.isfile(output_path):
                    final_size = os.path.getsize(output_path)
                    if final_size > 0:
                        final_check_passed = True
                        log.info(f"  FINAL CHECK PASSED: File '{os.path.basename(output_path)}' exists and size is {final_size} bytes.")
                    else:
                        log.error(f"  FINAL CHECK FAILED: File '{os.path.basename(output_path)}' exists BUT size is {final_size} bytes!")
                else:
                    log.error(f"  FINAL CHECK FAILED: File '{os.path.basename(output_path)}' does NOT exist after _save_image reported success!")
            except Exception as final_check_err:
                 log.error(f"  FINAL CHECK ERROR: Error checking file status: {final_check_err}")
        else:
            log.warning("  _save_image reported FAILURE. Skipping final verification.")

        # --- 9. Завершение и отчет ---
        if final_check_passed: # Используем результат финальной проверки
            log.info("--- Collage processing completed successfully! ---")
        else:
            error_msg = "Collage processing failed (or file invalid) after save attempts."
            log.error(error_msg) # Изменено с info на error
            raise RuntimeError(error_msg) # Оставим raise, чтобы app.py показал ошибку

        log.info(f"Total collage processing time: {time.time() - start_time:.2f} seconds")

    except Exception as e:
        log.critical(f"!!! UNEXPECTED error in collage processing: {e}", exc_info=True)
        import traceback
        traceback.print_exc()
        raise