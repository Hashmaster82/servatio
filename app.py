#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Servatio — надёжное резервное копирование с поддержкой множества задач.
"""

import os
import sys
import shutil
import logging
import threading
import configparser
import json
from pathlib import Path
from datetime import datetime, timedelta
import fnmatch
import ctypes
from tkinter import ttk
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext

# Попытка импорта pystray (опционально)
TRAY_AVAILABLE = False
try:
    import pystray
    from PIL import Image, ImageDraw
    TRAY_AVAILABLE = True
except ImportError:
    pass


# === Настройки ===
CONFIG_FILE = Path.home() / ".servatio_config.ini"
DEFAULT_EXCLUDE_PATTERNS = [
    "*.tmp", "*.log", ".git", ".gitignore", "__pycache__", "*.pyc",
    ".DS_Store", "Thumbs.db", "desktop.ini", "$RECYCLE.BIN", "System Volume Information"
]

# Папка логов по умолчанию
DEFAULT_LOG_DIR = Path.home() / "Documents" / "Servatio" / "Logs"

progress_info = {
    "total_files": 0,
    "processed_files": 0,
    "current_file": "",
    "lock": threading.Lock()
}


# === Вспомогательные функции (без изменений) ===

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


def get_total_files(src: Path, exclude_patterns):
    count = 0
    try:
        for item in src.rglob("*"):
            if item.is_file() and not is_excluded(item, exclude_patterns, src):
                count += 1
    except PermissionError:
        pass
    return count


def safe_remove(path: Path, log_callback, update_progress):
    try:
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        log_callback(f"Удалено: {path}")
    except Exception as e:
        log_callback(f"⚠️ Не удалось удалить {path}: {e}")


def safe_copy(src: Path, dst: Path, log_callback, update_progress):
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dst)
            with progress_info["lock"]:
                progress_info["processed_files"] += 1
                progress_info["current_file"] = str(src.name)
            update_progress()
        log_callback(f"Скопировано: {src} → {dst}")
    except Exception as e:
        log_callback(f"⚠️ Ошибка копирования {src} → {dst}: {e}")


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


def create_image():
    width, height = 64, 64
    image = Image.new('RGB', (width, height), 'black')
    dc = ImageDraw.Draw(image)
    dc.rectangle((width // 4, height // 4, 3 * width // 4, 3 * height // 4), fill='green')
    return image


def cleanup_old_logs(log_dir: Path, days=30):
    """Удаляет логи старше N дней."""
    if not log_dir.exists():
        return
    cutoff = datetime.now() - timedelta(days=days)
    for log_file in log_dir.glob("*.log"):
        try:
            file_time = datetime.fromtimestamp(log_file.stat().st_mtime)
            if file_time < cutoff:
                log_file.unlink()
        except Exception:
            pass


# === Класс задачи ===
class BackupTask:
    def __init__(self, name, source, destination, exclude_patterns=None, delete_extra=True):
        self.name = name
        self.source = source
        self.destination = destination
        self.exclude_patterns = exclude_patterns or DEFAULT_EXCLUDE_PATTERNS.copy()
        self.delete_extra = delete_extra

    def to_dict(self):
        return {
            "name": self.name,
            "source": self.source,
            "destination": self.destination,
            "exclude_patterns": json.dumps(self.exclude_patterns),
            "delete_extra": str(self.delete_extra)
        }

    @classmethod
    def from_dict(cls, data):
        return cls(
            name=data["name"],
            source=data["source"],
            destination=data["destination"],
            exclude_patterns=json.loads(data.get("exclude_patterns", "[]")),
            delete_extra=data.get("delete_extra", "True").lower() == "true"
        )


# === Основная логика синхронизации ===
def sync_recursive(src: Path, dst: Path, exclude_patterns, log_callback, update_progress, should_delete=True):
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

    for name, src_path in src_items.items():
        dst_path = dst / name
        if name not in dst_items:
            safe_copy(src_path, dst_path, log_callback, update_progress)
        else:
            existing_dst = dst_items[name]
            if src_path.is_dir() and existing_dst.is_dir():
                sync_recursive(src_path, existing_dst, exclude_patterns, log_callback, update_progress, should_delete)
            elif src_path.is_file() and existing_dst.is_file():
                if not files_are_equal(src_path, existing_dst):
                    safe_copy(src_path, dst_path, log_callback, update_progress)
            else:
                safe_remove(existing_dst, log_callback, update_progress)
                safe_copy(src_path, dst_path, log_callback, update_progress)

    if should_delete:
        for name, dst_path in dst_items.items():
            if name not in src_items:
                safe_remove(dst_path, log_callback, update_progress)


# === Drag & Drop ===
def enable_dnd(widget, callback):
    if os.name != 'nt':
        return

    import ctypes
    from ctypes import wintypes

    hwnd = widget.winfo_id()
    GWL_EXSTYLE = -20
    WS_EX_ACCEPTFILES = 0x00000010
    ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE,
                                        ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE) | WS_EX_ACCEPTFILES)

    def wnd_proc(hwnd, msg, wparam, lparam):
        if msg == 0x0233:
            hdrop = wparam
            file_count = ctypes.windll.shell32.DragQueryFileW(hdrop, -1, None, 0)
            if file_count == 1:
                buffer = ctypes.create_unicode_buffer(260)
                ctypes.windll.shell32.DragQueryFileW(hdrop, 0, buffer, 260)
                path = buffer.value
                if Path(path).is_dir():
                    callback(path)
            ctypes.windll.shell32.DragFinish(hdrop)
        return ctypes.windll.user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    widget._wnd_proc = wnd_proc
    WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_long, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    widget._proc = WNDPROC(wnd_proc)
    ctypes.windll.user32.SetWindowLongW(hwnd, -4, widget._proc)


# === Диалог настроек (папка логов) ===
class SettingsDialog:
    def __init__(self, parent, log_dir):
        self.result = None
        self.top = tk.Toplevel(parent)
        self.top.title("Настройки Servatio")
        self.top.geometry("500x180")
        self.top.transient(parent)
        self.top.grab_set()

        ttk.Label(self.top, text="Папка для хранения логов:").pack(anchor="w", padx=10, pady=(10, 0))
        self.log_dir_var = tk.StringVar(value=str(log_dir))
        dir_frame = ttk.Frame(self.top)
        dir_frame.pack(fill="x", padx=10, pady=5)
        ttk.Entry(dir_frame, textvariable=self.log_dir_var, state="readonly").pack(side="left", fill="x", expand=True)
        ttk.Button(dir_frame, text="Выбрать...", command=self.browse_dir).pack(side="right", padx=(5, 0))

        ttk.Label(self.top, text="Примечание: старые логи (старше 30 дней) удаляются автоматически.").pack(
            anchor="w", padx=10, pady=(10, 0)
        )

        btn_frame = ttk.Frame(self.top)
        btn_frame.pack(pady=10)
        ttk.Button(btn_frame, text="Сохранить", command=self.save).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="Отмена", command=self.cancel).pack(side="left", padx=5)

    def browse_dir(self):
        path = filedialog.askdirectory(title="Папка для логов")
        if path:
            self.log_dir_var.set(path)

    def save(self):
        self.result = Path(self.log_dir_var.get())
        self.top.destroy()

    def cancel(self):
        self.result = None
        self.top.destroy()


# === Диалог редактирования задачи ===
class TaskDialog:
    def __init__(self, parent, task=None):
        self.result = None
        self.top = tk.Toplevel(parent)
        self.top.title("Редактировать задачу" if task else "Новая задача")
        self.top.geometry("600x500")
        self.top.transient(parent)
        self.top.grab_set()

        ttk.Label(self.top, text="Название задачи:").pack(anchor="w", padx=10, pady=(10, 0))
        self.name_var = tk.StringVar(value=task.name if task else "")
        ttk.Entry(self.top, textvariable=self.name_var, width=50).pack(padx=10, pady=5)

        ttk.Label(self.top, text="Источник:").pack(anchor="w", padx=10, pady=(10, 0))
        self.src_var = tk.StringVar(value=task.source if task else "")
        src_frame = ttk.Frame(self.top)
        src_frame.pack(fill="x", padx=10, pady=5)
        ttk.Entry(src_frame, textvariable=self.src_var, state="readonly").pack(side="left", fill="x", expand=True)
        ttk.Button(src_frame, text="Выбрать...", command=self.browse_src).pack(side="right", padx=(5, 0))

        ttk.Label(self.top, text="Назначение:").pack(anchor="w", padx=10, pady=(10, 0))
        self.dst_var = tk.StringVar(value=task.destination if task else "")
        dst_frame = ttk.Frame(self.top)
        dst_frame.pack(fill="x", padx=10, pady=5)
        ttk.Entry(dst_frame, textvariable=self.dst_var, state="readonly").pack(side="left", fill="x", expand=True)
        ttk.Button(dst_frame, text="Выбрать...", command=self.browse_dst).pack(side="right", padx=(5, 0))

        options_frame = ttk.LabelFrame(self.top, text="Настройки", padding="10")
        options_frame.pack(fill="x", padx=10, pady=10)
        self.delete_var = tk.BooleanVar(value=task.delete_extra if task else True)
        ttk.Checkbutton(
            options_frame,
            text="Удалять лишние файлы в целевой папке",
            variable=self.delete_var
        ).pack(anchor="w")

        ttk.Label(options_frame, text="Исключения (по одному на строку):").pack(anchor="w", pady=(10, 5))
        self.exclude_text = tk.Text(options_frame, height=6, wrap=tk.WORD)
        self.exclude_text.pack(fill="x", pady=5)
        patterns = task.exclude_patterns if task else DEFAULT_EXCLUDE_PATTERNS
        self.exclude_text.insert("1.0", "\n".join(patterns))

        btn_frame = ttk.Frame(self.top)
        btn_frame.pack(pady=10)
        ttk.Button(btn_frame, text="Сохранить", command=self.save).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="Отмена", command=self.cancel).pack(side="left", padx=5)

        self.top.bind("<Return>", lambda e: self.save())
        self.top.bind("<Escape>", lambda e: self.cancel())

    def browse_src(self):
        path = filedialog.askdirectory(title="Источник")
        if path:
            self.src_var.set(path)

    def browse_dst(self):
        path = filedialog.askdirectory(title="Назначение")
        if path:
            self.dst_var.set(path)

    def save(self):
        name = self.name_var.get().strip()
        src = self.src_var.get().strip()
        dst = self.dst_var.get().strip()
        if not name or not src or not dst:
            messagebox.showerror("Ошибка", "Заполните все поля!")
            return

        exclude_content = self.exclude_text.get("1.0", tk.END).strip()
        exclude_patterns = [line.strip() for line in exclude_content.splitlines() if line.strip()]

        self.result = BackupTask(
            name=name,
            source=src,
            destination=dst,
            exclude_patterns=exclude_patterns,
            delete_extra=self.delete_var.get()
        )
        self.top.destroy()

    def cancel(self):
        self.result = None
        self.top.destroy()


# === Основное приложение ===
class ServatioApp:
    def __init__(self, root):
        self.root = root
        self.root.title("📁 Servatio — Резервное копирование")
        self.root.geometry("1000x700")
        self.root.minsize(900, 600)

        self.tasks = []
        self.current_task = None
        self.log_file = None
        self.log_dir = DEFAULT_LOG_DIR

        self.load_config()
        self.setup_theme()
        self.create_widgets()
        self.cleanup_logs()

    def setup_theme(self):
        dark_mode = False
        if os.name == 'nt':
            try:
                import winreg
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
                value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
                dark_mode = (value == 0)
                winreg.CloseKey(key)
            except Exception:
                dark_mode = False

        style = ttk.Style()
        if dark_mode:
            self.root.configure(background='#2d2d2d')
            style.configure(".", background='#2d2d2d', foreground='white', fieldbackground='#3c3c3c')
            style.configure("TButton", background='#3c3c3c', foreground='white', borderwidth=1)
            style.map("TButton", background=[('active', '#4a4a4a')], foreground=[('active', 'white')])
            style.configure("TCheckbutton", background='#2d2d2d', foreground='white')
            style.configure("TRadiobutton", background='#2d2d2d', foreground='white')
            style.configure("TLabelframe", background='#2d2d2d', foreground='white')
            style.configure("TLabelframe.Label", background='#2d2d2d', foreground='white')
            style.configure("TEntry", fieldbackground='#3c3c3c', foreground='white')
            style.configure("TCombobox", fieldbackground='#3c3c3c', foreground='white')
            self.root.option_add("*Listbox*Background", "#2d2d2d")
            self.root.option_add("*Listbox*Foreground", "white")
            self.root.option_add("*Text*Background", "#2d2d2d")
            self.root.option_add("*Text*Foreground", "white")
        else:
            self.root.configure(background='SystemButtonFace')

    def create_widgets(self):
        # Верхнее меню
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)
        settings_menu = tk.Menu(menubar, tearoff=0)
        settings_menu.add_command(label="Папка для логов...", command=self.open_settings)
        menubar.add_cascade(label="Настройки", menu=settings_menu)

        # Левая панель
        left_frame = ttk.LabelFrame(self.root, text="Задачи", padding="10")
        left_frame.grid(row=0, column=0, sticky="nsew", padx=(10, 5), pady=10)
        left_frame.rowconfigure(0, weight=1)

        self.task_listbox = tk.Listbox(left_frame, width=30, selectmode=tk.SINGLE)
        self.task_listbox.grid(row=0, column=0, columnspan=2, sticky="nsew", pady=(0, 10))
        self.task_listbox.bind("<<ListboxSelect>>", self.on_task_select)

        ttk.Button(left_frame, text="➕ Добавить", command=self.add_task).grid(row=1, column=0, sticky="ew", padx=(0, 5))
        ttk.Button(left_frame, text="✏️ Редактировать", command=self.edit_task).grid(row=2, column=0, sticky="ew", padx=(0, 5), pady=5)
        ttk.Button(left_frame, text="🗑️ Удалить", command=self.delete_task).grid(row=3, column=0, sticky="ew", padx=(0, 5))

        # Правая панель
        right_frame = ttk.Frame(self.root)
        right_frame.grid(row=0, column=1, sticky="nsew", padx=(5, 10), pady=10)
        right_frame.columnconfigure(0, weight=1)
        right_frame.rowconfigure(4, weight=1)

        self.task_title = ttk.Label(right_frame, text="Выберите задачу", font=("Segoe UI", 12, "bold"))
        self.task_title.grid(row=0, column=0, sticky="w", pady=(0, 10))

        path_frame = ttk.Frame(right_frame)
        path_frame.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        path_frame.columnconfigure(1, weight=1)

        ttk.Label(path_frame, text="Источник:").grid(row=0, column=0, sticky="w")
        self.src_label = ttk.Label(path_frame, text="-")
        self.src_label.grid(row=0, column=1, sticky="w", padx=(10, 0))

        ttk.Label(path_frame, text="Назначение:").grid(row=1, column=0, sticky="w", pady=(5, 0))
        self.dst_label = ttk.Label(path_frame, text="-")
        self.dst_label.grid(row=1, column=1, sticky="w", padx=(10, 0), pady=(5, 0))

        self.progress_var = tk.DoubleVar()
        self.progress_label = ttk.Label(right_frame, text="Готово к запуску")
        self.progress_label.grid(row=2, column=0, sticky="w", pady=(0, 5))
        self.progress_bar = ttk.Progressbar(right_frame, variable=self.progress_var, maximum=100)
        self.progress_bar.grid(row=3, column=0, sticky="ew", pady=(0, 10))

        log_frame = ttk.LabelFrame(right_frame, text="Лог", padding="5")
        log_frame.grid(row=4, column=0, sticky="nsew")
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        self.log_text = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD, state="disabled", font=("Consolas", 9))
        self.log_text.grid(row=0, column=0, sticky="nsew")

        btn_frame = ttk.Frame(right_frame)
        btn_frame.grid(row=5, column=0, pady=10)
        self.run_btn = ttk.Button(btn_frame, text="▶️ Запустить задачу", command=self.run_task, state="disabled")
        self.run_btn.pack(side="left", padx=5)
        self.open_log_btn = ttk.Button(btn_frame, text="📂 Открыть лог", command=self.open_log_file, state="disabled")
        self.open_log_btn.pack(side="left", padx=5)
        ttk.Button(btn_frame, text="Очистить лог", command=self.clear_log).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="Выход", command=self.on_closing).pack(side="left", padx=5)

        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(0, weight=1)
        left_frame.columnconfigure(0, weight=1)
        left_frame.rowconfigure(0, weight=1)

        self.update_task_list()

    def open_settings(self):
        dialog = SettingsDialog(self.root, self.log_dir)
        self.root.wait_window(dialog.top)
        if dialog.result:
            self.log_dir = dialog.result
            self.save_config()

    def update_task_list(self):
        self.task_listbox.delete(0, tk.END)
        for task in self.tasks:
            self.task_listbox.insert(tk.END, task.name)
        self.clear_task_details()

    def clear_task_details(self):
        self.task_title.config(text="Выберите задачу")
        self.src_label.config(text="-")
        self.dst_label.config(text="-")
        self.run_btn.config(state="disabled")
        self.current_task = None

    def on_task_select(self, event):
        selection = self.task_listbox.curselection()
        if selection:
            idx = selection[0]
            self.current_task = self.tasks[idx]
            self.task_title.config(text=self.current_task.name)
            self.src_label.config(text=self.current_task.source)
            self.dst_label.config(text=self.current_task.destination)
            self.run_btn.config(state="normal")
        else:
            self.clear_task_details()

    def add_task(self):
        dialog = TaskDialog(self.root)
        self.root.wait_window(dialog.top)
        if dialog.result:
            self.tasks.append(dialog.result)
            self.update_task_list()
            self.save_config()

    def edit_task(self):
        selection = self.task_listbox.curselection()
        if not selection:
            messagebox.showwarning("Внимание", "Выберите задачу для редактирования!")
            return
        idx = selection[0]
        dialog = TaskDialog(self.root, self.tasks[idx])
        self.root.wait_window(dialog.top)
        if dialog.result:
            self.tasks[idx] = dialog.result
            self.update_task_list()
            self.save_config()
            if self.current_task and self.current_task.name == dialog.result.name:
                self.on_task_select(None)

    def delete_task(self):
        selection = self.task_listbox.curselection()
        if not selection:
            messagebox.showwarning("Внимание", "Выберите задачу для удаления!")
            return
        idx = selection[0]
        task_name = self.tasks[idx].name
        if messagebox.askyesno("Подтверждение", f"Удалить задачу '{task_name}'?"):
            del self.tasks[idx]
            self.update_task_list()
            self.save_config()

    def save_config(self):
        config = configparser.ConfigParser()
        config["global"] = {"log_dir": str(self.log_dir)}
        for i, task in enumerate(self.tasks):
            config[f"task_{i}"] = task.to_dict()
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            config.write(f)

    def load_config(self):
        if not CONFIG_FILE.exists():
            return
        config = configparser.ConfigParser()
        try:
            config.read(CONFIG_FILE, encoding='utf-8')
            if "global" in config:
                log_dir_str = config["global"].get("log_dir")
                if log_dir_str:
                    self.log_dir = Path(log_dir_str)
            self.tasks = []
            i = 0
            while f"task_{i}" in config:
                task = BackupTask.from_dict(config[f"task_{i}"])
                self.tasks.append(task)
                i += 1
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось загрузить конфиг:\n{e}")

    def cleanup_logs(self):
        """Очистка старых логов при запуске."""
        try:
            cleanup_old_logs(self.log_dir, days=30)
        except Exception:
            pass  # Игнорируем ошибки очистки

    def clear_log(self):
        self.log_text.config(state="normal")
        self.log_text.delete(1.0, tk.END)
        self.log_text.config(state="disabled")

    def log_message(self, msg):
        self.log_text.config(state="normal")
        self.log_text.insert(tk.END, msg + "\n")
        self.log_text.see(tk.END)
        self.log_text.config(state="disabled")
        self.root.update_idletasks()

    def update_progress(self):
        with progress_info["lock"]:
            total = progress_info["total_files"]
            done = progress_info["processed_files"]
            current = progress_info["current_file"]
        if total > 0:
            percent = (done / total) * 100
            self.progress_var.set(percent)
            self.progress_label.config(text=f"Обработано: {done}/{total} — {current}")
        else:
            self.progress_label.config(text="Подсчёт файлов...")

    def run_task(self):
        if not self.current_task:
            return

        src_path = Path(self.current_task.source).resolve()
        dst_path = Path(self.current_task.destination).resolve()

        try:
            validate_paths(src_path, dst_path)
        except ValueError as e:
            messagebox.showerror("Ошибка валидации", str(e))
            return

        src_size = get_folder_size(src_path)
        free_space = get_free_space(dst_path)
        if src_size > free_space:
            if not messagebox.askyesno(
                "Недостаточно места",
                f"Размер: {src_size / (1024**3):.2f} ГБ\nСвободно: {free_space / (1024**3):.2f} ГБ\nПродолжить?"
            ):
                return

        # Создаём папку логов и файл
        self.log_dir.mkdir(parents=True, exist_ok=True)
        safe_name = "".join(c if c.isalnum() or c in " _-" else "_" for c in self.current_task.name)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_file = self.log_dir / f"{safe_name}_{timestamp}.log"
        self.open_log_btn.config(state="disabled")

        global progress_info
        progress_info = {
            "total_files": get_total_files(src_path, self.current_task.exclude_patterns),
            "processed_files": 0,
            "current_file": "",
            "lock": threading.Lock()
        }

        self.run_btn.config(state="disabled", text="⏳ Выполняется...")
        self.log_message("=" * 70)
        self.log_message(f"Запуск задачи: {self.current_task.name}")
        self.log_message(f"Лог: {self.log_file}")

        thread = threading.Thread(
            target=self.run_sync_in_thread,
            args=(src_path, dst_path),
            daemon=True
        )
        thread.start()

    def run_sync_in_thread(self, src_path, dst_path):
        try:
            enable_long_paths()

            file_handler = logging.FileHandler(self.log_file, encoding='utf-8')
            formatter = logging.Formatter('%(asctime)s | %(message)s', datefmt='%H:%M:%S')
            file_handler.setFormatter(formatter)
            logging.getLogger().addHandler(file_handler)
            logging.getLogger().setLevel(logging.INFO)

            def gui_logger(msg):
                self.log_message(msg)
                logging.info(msg)

            should_delete = self.current_task.delete_extra
            sync_recursive(
                src_path, dst_path,
                self.current_task.exclude_patterns,
                gui_logger,
                self.update_progress,
                should_delete
            )

            self.log_message("✅ Задача успешно завершена!")
            logging.info("✅ Задача успешно завершена!")

            self.root.after(0, self.show_completion_notification)

        except Exception as e:
            error_msg = f"❌ Ошибка: {e}"
            self.log_message(error_msg)
            logging.exception(error_msg)
            self.root.after(0, lambda: messagebox.showerror("Ошибка", str(e)))
        finally:
            self.root.after(0, self.on_task_complete)

    def on_task_complete(self):
        self.run_btn.config(state="normal", text="▶️ Запустить задачу")
        self.open_log_btn.config(state="normal")
        self.progress_var.set(0)
        self.progress_label.config(text="Готово.")

    def show_completion_notification(self):
        try:
            import winsound
            winsound.MessageBeep(winsound.MB_OK)
        except:
            pass

        if TRAY_AVAILABLE:
            def on_clicked(icon, item):
                icon.stop()
                self.root.deiconify()

            image = create_image()
            icon = pystray.Icon("Servatio", image, "Servatio", menu=pystray.Menu(
                pystray.MenuItem("Открыть", on_clicked),
                pystray.MenuItem("Выход", lambda icon, item: icon.stop())
            ))
            icon.run_detached()
            self.root.after(1000, lambda: icon.notify("Задача завершена!", self.current_task.name))
        else:
            messagebox.showinfo("Готово", f"Задача '{self.current_task.name}' завершена!")

    def open_log_file(self):
        if self.log_file and self.log_file.exists():
            try:
                os.startfile(self.log_file)
            except Exception as e:
                messagebox.showerror("Ошибка", f"Не удалось открыть лог:\n{e}")

    def on_closing(self):
        self.save_config()
        self.root.destroy()


# === Запуск ===
if __name__ == "__main__":
    if os.name != 'nt':
        messagebox.showwarning("Предупреждение", "Servatio предназначена для Windows!")

    root = tk.Tk()
    app = ServatioApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()