from typing import List
from pathlib import Path
import json

# === Стандартные исключения ===
DEFAULT_EXCLUDE_PATTERNS = [
    "*.tmp", "*.log", ".git", ".gitignore", "__pycache__", "*.pyc",
    ".DS_Store", "Thumbs.db", "desktop.ini", "$RECYCLE.BIN", "System Volume Information"
]

class BackupTask:
    def __init__(self, name: str, source: str, destination: str, exclude_patterns: List[str] = None, delete_extra: bool = True):
        self.name = name
        self.source = Path(source)
        self.destination = Path(destination)
        self.exclude_patterns = exclude_patterns or DEFAULT_EXCLUDE_PATTERNS.copy()
        self.delete_extra = delete_extra

    def to_dict(self):
        return {
            "name": self.name,
            "source": str(self.source),
            "destination": str(self.destination),
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