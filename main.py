import sys
from pathlib import Path

# Добавляем корень проекта в sys.path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root.parent))

from servatio.ui.main_window import ServatioApp
import tkinter as tk

if __name__ == "__main__":
    root = tk.Tk()
    app = ServatioApp(root)
    root.mainloop()