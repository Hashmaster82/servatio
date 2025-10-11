import configparser
from pathlib import Path
from typing import List
from servatio.core.backup_task import BackupTask

class ConfigManager:
    def __init__(self, config_path: Path):
        self.config_path = config_path
        self.log_dir = Path.home() / "Documents" / "Servatio" / "Logs"

    def load(self) -> List[BackupTask]:
        if not self.config_path.exists():
            return []

        config = configparser.ConfigParser()
        try:
            config.read(self.config_path, encoding='utf-8')
            if "global" in config:
                log_dir_str = config["global"].get("log_dir")
                if log_dir_str:
                    self.log_dir = Path(log_dir_str)
            tasks = []
            i = 0
            while f"task_{i}" in config:
                task = BackupTask.from_dict(config[f"task_{i}"])
                tasks.append(task)
                i += 1
            return tasks
        except Exception as e:
            print(f"Ошибка загрузки конфига: {e}")
            return []

    def save(self, tasks: List[BackupTask]):
        self.log_dir.mkdir(parents=True, exist_ok=True)

        config = configparser.ConfigParser()
        config["global"] = {"log_dir": str(self.log_dir)}
        for i, task in enumerate(tasks):
            config[f"task_{i}"] = task.to_dict()

        with open(self.config_path, 'w', encoding='utf-8') as f:
            config.write(f)