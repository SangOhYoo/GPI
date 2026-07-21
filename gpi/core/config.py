import json
import os
from pathlib import Path

# Paths
BASE_DIR = Path(os.getcwd())
API_KEYS_FILE = BASE_DIR / "gpi_api_keys.json"
OLD_API_KEY_FILE = BASE_DIR / "gpi_api_key.txt"
LOG_FILE = BASE_DIR / "gpi_events.jsonl"
HISTORY_FILE = BASE_DIR / "history.txt"
HISTORY_IMAGES_DIR = BASE_DIR / "history_images"

# Ensure history images directory exists
if not HISTORY_IMAGES_DIR.exists():
    HISTORY_IMAGES_DIR.mkdir(parents=True, exist_ok=True)

# Gemini API Constants
MODEL_OPTIONS = [
    "gemini-1.5-flash",
    "gemini-1.5-flash-8b",
    "gemini-1.5-pro",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite-preview-02-05",
    "gemini-2.0-pro-exp-02-05",
    "gemini-2.0-flash-thinking-exp-01-21",
    "local-llama-cpp",
]

MODEL_THINKING_LEVELS = {
    "gemini-2.0-flash-thinking-exp-01-21": "low",
}

API_URL_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
API_STREAM_URL_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:streamGenerateContent?alt=sse"

# Image Constraints
MAX_IMAGE_DIM = 1024
MAX_FILE_MB = 5
MIN_PROMPT_WORDS = 75
MAX_PROMPT_WORDS = 250
HIGH_FIDELITY_MIN_WORDS = 300
HIGH_FIDELITY_MAX_WORDS = 1000
URL_DOWNLOAD_TIMEOUT_SEC = 15
URL_DOWNLOAD_MAX_SECONDS = 30
URL_DOWNLOAD_CHUNK_SIZE = 65536

# UI Constants
MAX_UI_HISTORY = None
CANCELLED_MESSAGE = "USER_CANCELLED"
DOWNLOAD_TIMEOUT_MESSAGE = "DOWNLOAD_TIMEOUT"

def load_api_keys():
    # Migration logic
    if not API_KEYS_FILE.exists() and OLD_API_KEY_FILE.exists():
        old_key = OLD_API_KEY_FILE.read_text(encoding="utf-8").strip()
        if old_key:
            keys = {"Default": old_key}
            save_api_keys(keys)
            # Optional: OLD_API_KEY_FILE.unlink() - keep for safety for now
            return keys

    if API_KEYS_FILE.exists():
        try:
            return json.loads(API_KEYS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}

def save_api_keys(keys):
    API_KEYS_FILE.write_text(json.dumps(keys, indent=2), encoding="utf-8")

def get_api_key(name="Default"):
    env_key = os.environ.get("GOOGLE_API_KEY")
    if env_key:
        return env_key
    keys = load_api_keys()
    return keys.get(name, "")

# Keep these for backward compatibility if needed, but they are mostly obsolete
def load_api_key():
    return get_api_key()

def save_api_key(key):
    save_api_keys({"Default": key})

def delete_api_key():
    if API_KEYS_FILE.exists():
        API_KEYS_FILE.unlink()
