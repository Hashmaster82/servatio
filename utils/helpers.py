import os
import ctypes
from pathlib import Path
import fnmatch

def enable_long_paths():
    if os.name == 'nt':
        try:
            ctypes.windll.kernel32.SetDllDirectoryW(None)
        except Exception:
            pass

def is_excluded(path: Path, exclude_patterns, base_path: Path):
    try:
        rel_path = path.relative_to(base_path).as_posix()
    except ValueError:
        return False
    for pattern in exclude_patterns:
        if fnmatch.fnmatch(rel_path, pattern) or fnmatch.fnmatch(rel_path, f"**/{pattern}"):
            return True
    return False

def files_are_equal(file1: Path, file2: Path) -> bool:
    if not file2.exists():
        return False
    stat1 = file1.stat()
    stat2 = file2.stat()
    return stat1.st_size == stat2.st_size and abs(stat1.st_mtime - stat2.st_mtime) < 1

def validate_paths(src: Path, dst: Path):
    if not src.is_absolute() or not dst.is_absolute():
        raise ValueError("Пути должны быть абсолютными!")
    if src.resolve() == dst.resolve():
        raise ValueError("Исходный и целевой каталоги совпадают!")
    dangerous = [f"{d}:\\" for d in "CDEFGHIJKLMNOPQRSTUVWXYZ"]
    dst_clean = str(dst).rstrip("\\/").upper()
    if dst_clean in [d.upper() for d in dangerous]:
        raise ValueError("Запрещено синхронизировать в корень диска!")

def get_total_files(src: Path, exclude_patterns):
    count = 0
    try:
        for item in src.rglob("*"):
            if item.is_file() and not is_excluded(item, exclude_patterns, src):
                count += 1
    except PermissionError:
        pass
    return count

def get_free_space(path: Path):
    if os.name == 'nt':
        free_bytes = ctypes.c_ulonglong(0)
        ctypes.windll.kernel32.GetDiskFreeSpaceExW(str(path), None, None, ctypes.byref(free_bytes))
        return free_bytes.value
    else:
        statvfs = os.statvfs(path)
        return statvfs.f_frsize * statvfs.f_bavail

def get_folder_size(path: Path):
    total = 0
    try:
        for entry in path.glob("**/*"):
            if entry.is_file():
                total += entry.stat().st_size
    except (OSError, PermissionError):
        pass
    return total

def setup_logging(log_file, level=20):  # 20 = INFO
    import logging
    from logging.handlers import RotatingFileHandler

    logger = logging.getLogger("Servatio")
    logger.setLevel(level)

    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    formatter = logging.Formatter('%(asctime)s | %(levelname)s | %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

    file_handler = RotatingFileHandler(log_file, maxBytes=10*1024*1024, backupCount=5, encoding='utf-8')
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger