import json
import time
from datetime import datetime, timezone
from pathlib import Path


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class EventLog:
    def __init__(self, path: str | None):
        self.file = None
        if path:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            self.file = open(path, "a", buffering=1)

    def emit(self, event: str, **fields):
        record = {"timestamp_utc": utc_now(), "monotonic_ms": round(time.monotonic() * 1000, 3), "event": event, **fields}
        line = json.dumps(record, ensure_ascii=False, default=str)
        print(line, flush=True)
        if self.file:
            self.file.write(line + "\n")

    def close(self):
        if self.file:
            self.file.close()
