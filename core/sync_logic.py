import os
import shutil
from pathlib import Path
from servatio.utils.helpers import is_excluded, files_are_equal, validate_paths, get_total_files
from servatio.utils.metrics import BackupMetrics
import logging

logger = logging.getLogger("Servatio")

def sync_recursive(task, metrics: BackupMetrics, log_callback, update_progress, should_delete=True):
    src = task.source
    dst = task.destination
    exclude_patterns = task.exclude_patterns

    if not src.exists():
        log_callback(f"❌ Исходный каталог не существует: {src}")
        return

    dst.mkdir(parents=True, exist_ok=True)

    try:
        src_items = {p.name: p for p in src.iterdir() if not is_excluded(p, exclude_patterns, src)}
        dst_items = {p.name: p for p in dst.iterdir()}
    except PermissionError as e:
        log_callback(f"⚠️ Нет доступа к {src} или {dst}: {e}")
        return
    except OSError as e:
        log_callback(f"⚠️ Ошибка доступа к файлам в {src} или {dst}: {e}")
        return

    for name, src_path in src_items.items():
        dst_path = dst / name
        if name not in dst_items:
            safe_copy(src_path, dst_path, log_callback, update_progress, metrics)
        else:
            existing_dst = dst_items[name]
            if src_path.is_dir() and existing_dst.is_dir():
                sync_recursive(task, metrics, log_callback, update_progress, should_delete)
            elif src_path.is_file() and existing_dst.is_file():
                if not files_are_equal(src_path, existing_dst):
                    safe_copy(src_path, dst_path, log_callback, update_progress, metrics)
            else:
                safe_remove(existing_dst, log_callback, metrics)
                safe_copy(src_path, dst_path, log_callback, update_progress, metrics)

    if should_delete:
        for name, dst_path in dst_items.items():
            if name not in src_items:
                safe_remove(dst_path, log_callback, metrics)

def safe_copy(src: Path, dst: Path, log_callback, update_progress, metrics):
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            # Используем shutil.copytree с dirs_exist_ok=True
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dst)
            metrics.copied_files += 1
            update_progress()
        log_callback(f"Скопировано: {src} → {dst}")
    except Exception as e:
        log_callback(f"⚠️ Ошибка копирования {src} → {dst}: {e}")
        metrics.errors += 1

def safe_remove(path: Path, log_callback, metrics):
    try:
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        log_callback(f"Удалено: {path}")
    except Exception as e:
        log_callback(f"⚠️ Не удалось удалить {path}: {e}")
        metrics.errors += 1