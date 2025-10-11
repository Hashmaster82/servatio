import tkinter as tk
from tkinter import ttk, messagebox, filedialog, scrolledtext
from pathlib import Path
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from servatio.config.config_manager import ConfigManager
from servatio.core.sync_logic import sync_recursive
from servatio.utils.metrics import BackupMetrics
from servatio.utils.helpers import setup_logging, validate_paths, get_folder_size, get_free_space, get_total_files
import os

# === Глобальные переменные ===
progress_info = {
    "total_files": 0,
    "processed_files": 0,
    "current_file": "",
    "lock": threading.Lock()
}

class ServatioApp:
    def __init__(self, root):
        self.root = root
        self.root.title("📁 Servatio — Резервное копирование")
        self.root.geometry("1000x700")
        self.root.minsize(900, 600)

        self.log_dir = Path.home() / "Documents" / "Servatio" / "Logs"
        self.config_path = self.log_dir / "servatio_config.ini"
        self.config_manager = ConfigManager(self.config_path)
        self.tasks = self.config_manager.load()
        self.current_task = None
        self.logger = None
        self.current_log_file = None
        self.executor = ThreadPoolExecutor(max_workers=1)

        self.create_widgets()
        self.update_task_list()

    def create_widgets(self):
        # Меню
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
        self.run_all_btn = ttk.Button(btn_frame, text="▶️ Все задачи", command=self.run_all_tasks, state="normal")
        self.run_all_btn.pack(side="left", padx=5)
        self.open_log_btn = ttk.Button(btn_frame, text="📂 Открыть лог", command=self.open_log_file, state="disabled")
        self.open_log_btn.pack(side="left", padx=5)
        ttk.Button(btn_frame, text="Очистить лог", command=self.clear_log).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="Выход", command=self.on_closing).pack(side="left", padx=5)

        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(0, weight=1)
        left_frame.columnconfigure(0, weight=1)
        left_frame.rowconfigure(0, weight=1)

    def open_settings(self):
        path = filedialog.askdirectory(title="Папка для логов", initialdir=self.log_dir)
        if path:
            self.log_dir = Path(path)
            self.config_manager.log_dir = self.log_dir
            self.config_manager.save(self.tasks)

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
            self.src_label.config(text=str(self.current_task.source))
            self.dst_label.config(text=str(self.current_task.destination))
            self.run_btn.config(state="normal")
        else:
            self.clear_task_details()

    def add_task(self):
        from servatio.ui.task_dialog import TaskDialog
        dialog = TaskDialog(self.root)
        self.root.wait_window(dialog.top)
        if dialog.result:
            self.tasks.append(dialog.result)
            self.update_task_list()
            self.config_manager.save(self.tasks)

    def edit_task(self):
        selection = self.task_listbox.curselection()
        if not selection:
            messagebox.showwarning("Внимание", "Выберите задачу для редактирования!")
            return
        idx = selection[0]
        original_task = self.tasks[idx]
        from servatio.ui.task_dialog import TaskDialog
        dialog = TaskDialog(self.root, original_task)
        self.root.wait_window(dialog.top)
        if dialog.result:
            self.tasks[idx] = dialog.result
            self.update_task_list()
            self.config_manager.save(self.tasks)
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
            self.config_manager.save(self.tasks)

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

        src_path = self.current_task.source.resolve()
        dst_path = self.current_task.destination.resolve()

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
                    f"Размер: {src_size / (1024 ** 3):.2f} ГБ\nСвободно: {free_space / (1024 ** 3):.2f} ГБ\nПродолжить?"
            ):
                return

        # Создаём папку логов и файл
        self.log_dir.mkdir(parents=True, exist_ok=True)
        safe_name = "".join(c if c.isalnum() or c in " _-" else "_" for c in self.current_task.name)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.current_log_file = self.log_dir / f"{safe_name}_{timestamp}.log"

        global progress_info
        progress_info = {
            "total_files": get_total_files(src_path, self.current_task.exclude_patterns),
            "processed_files": 0,
            "current_file": "",
            "lock": threading.Lock()
        }

        self.run_btn.config(state="disabled", text="⏳ Выполняется...")
        self.open_log_btn.config(state="normal")  # <-- Включаем кнопку

        self.logger = setup_logging(self.current_log_file)
        self.logger.info(f"Запуск задачи: {self.current_task.name}")

        def gui_logger(msg):
            self.log_message(msg)
            self.logger.info(msg)

        def task_runner():
            metrics = BackupMetrics()
            metrics.start()
            metrics.total_files = progress_info["total_files"]

            sync_recursive(self.current_task, metrics, gui_logger, self.update_progress, self.current_task.delete_extra)

            metrics.finish()
            duration = metrics.duration()
            self.logger.info(f"Задача завершена за {duration}. Ошибок: {metrics.errors}")
            self.root.after(0, self.on_task_complete)

        self.executor.submit(task_runner)

    def on_task_complete(self):
        self.run_btn.config(state="normal", text="▶️ Запустить задачу")
        self.progress_var.set(0)
        self.progress_label.config(text="Готово.")

    def run_all_tasks(self):
        # Аналогично, но с циклом по всем задачам
        pass

    def open_log_file(self):
        if hasattr(self, 'current_log_file') and self.current_log_file and self.current_log_file.exists():
            try:
                os.startfile(self.current_log_file)
            except Exception as e:
                messagebox.showerror("Ошибка", f"Не удалось открыть лог:\n{e}")
        else:
            messagebox.showwarning("Внимание", "Лог-файл не найден.")

    def on_closing(self):
        self.config_manager.save(self.tasks)
        self.executor.shutdown(wait=True)
        self.root.destroy()