from datetime import datetime

class BackupMetrics:
    def __init__(self):
        self.start_time = None
        self.end_time = None
        self.total_files = 0
        self.copied_files = 0
        self.errors = 0

    def start(self):
        self.start_time = datetime.now()

    def finish(self):
        self.end_time = datetime.now()

    def duration(self):
        if self.start_time and self.end_time:
            return self.end_time - self.start_time
        return None