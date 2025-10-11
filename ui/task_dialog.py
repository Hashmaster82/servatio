import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from servatio.core.backup_task import DEFAULT_EXCLUDE_PATTERNS

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
        self.src_var = tk.StringVar(value=str(task.source) if task else "")
        src_frame = ttk.Frame(self.top)
        src_frame.pack(fill="x", padx=10, pady=5)
        ttk.Entry(src_frame, textvariable=self.src_var, state="readonly").pack(side="left", fill="x", expand=True)
        ttk.Button(src_frame, text="Выбрать...", command=self.browse_src).pack(side="right", padx=(5, 0))

        ttk.Label(self.top, text="Назначение:").pack(anchor="w", padx=10, pady=(10, 0))
        self.dst_var = tk.StringVar(value=str(task.destination) if task else "")
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

        from servatio.core.backup_task import BackupTask
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