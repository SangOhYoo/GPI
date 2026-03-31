import json
from datetime import datetime
from .config import LOG_FILE

def log_event(event_type, data=None):
    payload = {
        "ts": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "event": event_type,
    }
    payload.update(data or {})
    try:
        with LOG_FILE.open("a", encoding="utf-8") as file:
            file.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        pass
