# Decompiled with PyLingual (https://pylingual.io)
# Internal filename: 'app.py'
# Bytecode version: 3.12.0rc2 (3531)
# Source timestamp: 1970-01-01 00:00:00 UTC (0)

import base64
import json
import os
import re
import sys
import threading
import struct
from io import BytesIO
from pathlib import Path
from datetime import datetime
from time import perf_counter
from urllib.parse import urlparse, unquote
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

try:
    from tkinterdnd2 import TkinterDnD, DND_FILES, DND_TEXT

    DND_AVAILABLE = True
except Exception:
    TkinterDnD = None
    DND_FILES = None
    DND_TEXT = None
    DND_AVAILABLE = False
try:
    from PIL import Image, ImageGrab

    PIL_AVAILABLE = True
except Exception:
    Image = None
    ImageGrab = None
    PIL_AVAILABLE = False
WIN_DND_IMPORT_ERROR = ""
try:
    import pythoncom
    import win32con
    import win32clipboard
    import win32com.server.util
    from win32com.shell import shellcon

    WIN_DND_AVAILABLE = True
except Exception as error:
    WIN_DND_IMPORT_ERROR = str(error)
    if getattr(sys, "frozen", False):
        try:
            dll_dir = Path(sys.executable).resolve().parent
            os.add_dll_directory(str(dll_dir))
            import importlib

            pythoncom = importlib.import_module("pythoncom")
            win32con = importlib.import_module("win32con")
            win32clipboard = importlib.import_module("win32clipboard")
            win32com = importlib.import_module("win32com")
            win32com.server.util = importlib.import_module("win32com.server.util")
            shellcon = importlib.import_module("win32com.shell.shellcon")
            WIN_DND_AVAILABLE = True
            WIN_DND_IMPORT_ERROR = ""
        except Exception as retry_error:
            WIN_DND_IMPORT_ERROR = f"{error} | retry: {retry_error}"
            pythoncom = None
            win32con = None
            shellcon = None
            win32clipboard = None
            WIN_DND_AVAILABLE = False
        else:
            pass
    else:
        pythoncom = None
        win32con = None
        shellcon = None
        win32clipboard = None
        WIN_DND_AVAILABLE = False
APP_TITLE = "GPI 1.3v"
DEFAULT_MODEL = "gemini-3-flash-preview"
MODEL_OPTIONS = [
    "gemini-3-flash-preview",
    "gemini-3-pro-preview",
    "gemini-flash-latest",
    "gemini-flash-lite-latest",
]
MODEL_THINKING_LEVELS = {
    "gemini-3-flash-preview": "minimal",
    "gemini-3-pro-preview": "low",
}
API_URL_TEMPLATE = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)
API_STREAM_URL_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:streamGenerateContent?alt=sse"
MIN_PROMPT_WORDS = 75
MAX_PROMPT_WORDS = 250
MAX_UI_HISTORY = 20
MAX_FILE_MB = 20
MAX_OUTPUT_TOKENS = 5000
MAX_IMAGE_DIM = 2048
URL_DOWNLOAD_TIMEOUT_SEC = 5
URL_DOWNLOAD_MAX_SECONDS = 15
URL_DOWNLOAD_CHUNK_SIZE = 524288
DOWNLOAD_TIMEOUT_MESSAGE = "IMAGE_DOWNLOAD_TIMEOUT"
CANCELLED_MESSAGE = "사용자 중단"
DESIGN_TOKENS = {
    "colors": {
        "bg": "#0F1115",
        "surface": "#161B22",
        "surface_alt": "#1F2630",
        "surface_alt_strong": "#243042",
        "text_primary": "#E6EDF3",
        "text_secondary": "#A3ACB9",
        "text_muted": "#7A8696",
        "border": "#2D3642",
        "border_strong": "#3B4656",
        "accent": "#3B82F6",
        "accent_hover": "#60A5FA",
        "accent_active": "#2563EB",
        "success": "#10B981",
    },
    "typography": {
        "base": ("Segoe UI", 12),
        "title": ("Segoe UI", 16, "bold"),
        "label": ("Segoe UI", 11),
    },
    "spacing": {"xs": 4, "sm": 8, "md": 12, "lg": 16, "xl": 24},
}
SUPPORTED_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}
FILEDESCRIPTORW_SIZE = 592
FILEDESCRIPTORA_SIZE = 332
FILEDESCRIPTOR_NAME_OFFSET = 72
if WIN_DND_AVAILABLE:
    CF_FILEDESCRIPTORW = win32clipboard.RegisterClipboardFormat("FileGroupDescriptorW")
    CF_FILEDESCRIPTORA = win32clipboard.RegisterClipboardFormat("FileGroupDescriptor")
    CF_FILECONTENTS = win32clipboard.RegisterClipboardFormat("FileContents")
else:
    CF_FILEDESCRIPTORW = None
    CF_FILEDESCRIPTORA = None
    CF_FILECONTENTS = None


def get_app_dir():
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        if exe_dir.name.lower() == "dist":
            parent = exe_dir.parent
            for marker in ["app.py", "GPI.spec", "requirements.txt"]:
                if (parent / marker).exists():
                    return parent
        return exe_dir
    else:
        return Path(__file__).resolve().parent


APP_DIR = get_app_dir()
HISTORY_FILE = APP_DIR / "history.txt"
LOG_FILE = APP_DIR / "logs.jsonl"
API_KEY_FILE = APP_DIR / "gpi_api_key.txt"


def load_api_key():
    if not API_KEY_FILE.exists():
        return ""
    else:
        try:
            return API_KEY_FILE.read_text(encoding="utf-8").strip()
        except Exception:
            return ""


def save_api_key(api_key):
    API_KEY_FILE.write_text(api_key.strip(), encoding="utf-8")


def delete_api_key():
    if API_KEY_FILE.exists():
        API_KEY_FILE.unlink()


def get_api_key():
    return load_api_key()


def normalize_prompt(text):
    return " ".join(text.split())


def count_words(text):
    return len(re.findall("[A-Za-z0-9']+", text))


def is_non_english_text(text):
    if not text:
        return False
    else:
        for char in text:
            if not char.isspace() and ord(char) > 127:
                return True
        return False


def build_keyword_preview(text, max_len=60):
    text = (text or "").strip()
    if len(text) <= max_len:
        return text
    else:
        return text[: max_len - 3] + "..."


def ellipsize_text(text, max_len=60, head=28, tail=20):
    if not text:
        return ""
    else:
        if len(text) <= max_len:
            return text
        else:
            head = max(10, min(head, max_len - 5))
            tail = max(10, min(tail, max_len - head - 3))
            return f"{text[:head]}...{text[-tail:]}"


def looks_truncated(text, finish_reason):
    if not text:
        return True
    else:
        if finish_reason and finish_reason != "STOP":
            return True
        else:
            return re.search("[.!?][\"\\']?$", text.strip()) is None


def log_event(event_type, data):
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


def is_url(text):
    try:
        parsed = urlparse(text)
    except Exception:
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def normalize_drop_item(item):
    cleaned = item.strip().strip("{}")
    if cleaned.startswith("file://"):
        cleaned = cleaned.replace("file:///", "")
        cleaned = cleaned.replace("file://", "")
        cleaned = unquote(cleaned)
    return cleaned


def extract_drop_candidates(raw_data, tk_root):
    if not raw_data:
        return []
    else:
        candidates = []
        try:
            candidates = list(tk_root.tk.splitlist(raw_data))
        except Exception:
            candidates = [raw_data]
        if len(candidates) == 1:
            text = str(candidates[0])
            if "\n" in text or "\r" in text:
                for line in re.split("[\\r\\n]+", text):
                    if line.strip():
                        candidates.append(line.strip())
        return candidates


def build_instruction(
    min_words=MIN_PROMPT_WORDS, max_words=MAX_PROMPT_WORDS, keyword_text=""
):
    base = f"You are given an image. Describe only the visible visual content in English. Write {min_words} to {max_words} words in full, natural sentences as a single paragraph. When analyzing an image, estimate the race and add it to the prompt. Do not use keyword lists. This prompt is for Qwen/Flux, but must remain natural sentences. Avoid unnecessary adjectives and avoid any non-visual statements such as symbolism, intent, backstory, or guesses. Include the subject's facial expression and the camera angle (e.g., high angle, low angle, eye-level) if discernible. Do not mention camera, lens, or metadata unless they are visually evident in the image."
    keyword_text = (keyword_text or "").strip()
    if not keyword_text:
        return base
    else:
        return (
            base
            + "\n\n"
            + "User keyword(s): "
            + keyword_text
            + ". "
            + "You must incorporate the keyword(s). "
            + "If the keyword(s) are not in English, translate them to English first and use the English translation in the description. "
            + "Do not mention the translation process. "
            + "Incorporate the keyword(s) by adjusting only the most relevant visual element(s) "
            + "(such as clothing, background, or a specific object). "
            + "If the keyword(s) conflict with the image, replace the most relevant visual element with the keyword(s) "
            + "and do not mention the original conflicting element. "
            + "Keep all other elements faithful to the original image and do not alter unrelated details."
        )


def get_mime_type(path):
    ext = Path(path).suffix.lower()
    return SUPPORTED_MIME.get(ext, "")


def detect_mime_from_bytes(data, filename=""):
    ext = Path(filename).suffix.lower()
    ext = Path(filename).suffix.lower()
    if ext in SUPPORTED_MIME:
        return SUPPORTED_MIME[ext]
    else:
        if PIL_AVAILABLE and Image is not None:
            pass
        else:
            return ""
    try:
        with Image.open(BytesIO(data)) as img:
            fmt = (img.format or "").upper()
            fmt_map = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}
            return fmt_map.get(fmt, "")
    except Exception:
        return ""


def parse_file_group_descriptor(data, wide=True):
    # ***<module>.parse_file_group_descriptor: Failure: Different bytecode
    if not data or len(data) < 4:
        return []
    else:
        count = struct.unpack_from("<I", data, 0)[0]
        desc_size = FILEDESCRIPTORW_SIZE if wide else FILEDESCRIPTORA_SIZE
        name_size = 520 if wide else 260
        items = []
        for index in range(count):
            offset = 4 + index * desc_size
            if len(data) < offset + desc_size:
                break
            else:
                name_bytes = data[
                    offset
                    + FILEDESCRIPTOR_NAME_OFFSET : offset
                    + FILEDESCRIPTOR_NAME_OFFSET
                    + name_size
                ]
                if wide:
                    name = name_bytes.decode("utf-16le", errors="ignore").split(
                        "\x00", 1
                    )[0]
                else:
                    name = name_bytes.decode("mbcs", errors="ignore").split("\x00", 1)[
                        0
                    ]
                size_high = struct.unpack_from("<I", data, offset + 64)[0]
                size_low = struct.unpack_from("<I", data, offset + 68)[0]
                size_bytes = size_high << 32 | size_low
                items.append({"name": name, "size": size_bytes})
        else:
            return items


def parse_dropfiles(data):
    if not data or len(data) < 20:
        return []
    else:
        p_files = struct.unpack_from("<I", data, 0)[0]
        f_wide = struct.unpack_from("<I", data, 16)[0]
        if p_files >= len(data):
            return []
        else:
            raw = data[p_files:]
            if f_wide:
                text = raw.decode("utf-16le", errors="ignore")
            else:
                text = raw.decode("mbcs", errors="ignore")
            return [item for item in text.split("\x00") if item]


def read_istream_all(stream):
    chunks = []
    while True:
        chunk = stream.Read(1048576)
        if not chunk:
            break
        else:
            chunks.append(chunk)
    return b"".join(chunks)


def optimize_image_bytes(data, mime_type, source_type):
    if PIL_AVAILABLE and Image is None:
        return (
            data,
            {"optimized": False, "reason": "Pillow 없음", "source": source_type},
        )
    try:
        with Image.open(BytesIO(data)) as img:
            orig_width, orig_height = img.size
            orig_bytes = len(data)
            resized = False
            max_edge = max(orig_width, orig_height)
            if max_edge > MAX_IMAGE_DIM:
                scale = MAX_IMAGE_DIM / max_edge
                new_size = (
                    max(1, int(orig_width * scale)),
                    max(1, int(orig_height * scale)),
                )
                img = img.resize(new_size, Image.LANCZOS)
                resized = True
            else:
                new_size = (orig_width, orig_height)
            format_map = {
                "image/jpeg": "JPEG",
                "image/png": "PNG",
                "image/webp": "WEBP",
            }
            fmt = format_map.get(mime_type)
            if not fmt:
                return (
                    data,
                    {
                        "optimized": False,
                        "reason": "지원하지 않는 형식",
                        "source": source_type,
                    },
                )
            if fmt == "JPEG" and img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            buffer = BytesIO()
            save_kwargs = {}
            if fmt == "JPEG":
                save_kwargs = {"quality": 85, "optimize": True, "progressive": True}
            else:
                if fmt == "PNG":
                    save_kwargs = {"optimize": True}
                else:
                    if fmt == "WEBP":
                        save_kwargs = {"quality": 85}
            img.save(buffer, format=fmt, **save_kwargs)
            new_data = buffer.getvalue()
            new_bytes = len(new_data)
            if not resized and new_bytes >= orig_bytes:
                return (
                    data,
                    {
                        "optimized": False,
                        "reason": "용량 감소 없음",
                        "source": source_type,
                        "orig_bytes": orig_bytes,
                        "orig_width": orig_width,
                        "orig_height": orig_height,
                    },
                )
            return (
                new_data,
                {
                    "optimized": True,
                    "source": source_type,
                    "orig_bytes": orig_bytes,
                    "new_bytes": new_bytes,
                    "orig_width": orig_width,
                    "orig_height": orig_height,
                    "new_width": new_size[0],
                    "new_height": new_size[1],
                    "resized": resized,
                },
            )
    except Exception as e:
        return (
            data,
            {"optimized": False, "reason": "최적화 실패", "source": source_type},
        )


def prepare_image_bytes(data, mime_type, source_type):
    optimized_data, info = optimize_image_bytes(data, mime_type, source_type)
    if info.get("optimized"):
        log_event("image_optimize", info)
    size_mb = len(optimized_data) / 1048576
    if size_mb > MAX_FILE_MB:
        raise ValueError(f"이미지 용량이 {MAX_FILE_MB}MB를 초과했습니다.")
    else:
        return (optimized_data, len(optimized_data))


def download_image_from_url(url, cancel_check=None):
    import urllib.request
    import urllib.error
    import socket

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    }
    request = urllib.request.Request(url, headers=headers)
    start_time = perf_counter()
    parsed = urlparse(url)
    log_event(
        "download_start", {"url_host": parsed.netloc, "url_path": parsed.path[:120]}
    )
    try:
        with urllib.request.urlopen(
            request, timeout=URL_DOWNLOAD_TIMEOUT_SEC
        ) as response:
            content_type = (
                response.headers.get("Content-Type", "").split(";")[0].strip().lower()
            )
            if content_type not in SUPPORTED_MIME.values():
                raise ValueError(
                    "이미지 URL이 아닙니다. jpg/png/webp 이미지 주소를 사용하세요."
                )
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > MAX_FILE_MB * 1024 * 1024:
                raise ValueError(f"이미지 용량이 {MAX_FILE_MB}MB를 초과했습니다.")
            chunks = []
            total = 0
            while True:
                if cancel_check and cancel_check():
                    log_event(
                        "download_cancel",
                        {"elapsed_sec": round(perf_counter() - start_time, 2)},
                    )
                    raise RuntimeError(CANCELLED_MESSAGE)
                if perf_counter() - start_time > URL_DOWNLOAD_MAX_SECONDS:
                    log_event(
                        "download_timeout",
                        {"elapsed_sec": round(perf_counter() - start_time, 2)},
                    )
                    raise RuntimeError(DOWNLOAD_TIMEOUT_MESSAGE)

                chunk = response.read(URL_DOWNLOAD_CHUNK_SIZE)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_FILE_MB * 1024 * 1024:
                    raise ValueError(f"이미지 용량이 {MAX_FILE_MB}MB를 초과했습니다.")
                chunks.append(chunk)

            data = b"".join(chunks)
            elapsed_sec = round(perf_counter() - start_time, 2)
            log_event(
                "download_done",
                {
                    "elapsed_sec": elapsed_sec,
                    "content_type": content_type,
                    "bytes": len(data),
                },
            )
            return (data, content_type)
    except socket.timeout:
        if perf_counter() - start_time > URL_DOWNLOAD_MAX_SECONDS:
            log_event(
                "download_timeout",
                {"elapsed_sec": round(perf_counter() - start_time, 2)},
            )
            raise RuntimeError(DOWNLOAD_TIMEOUT_MESSAGE)
        raise RuntimeError(DOWNLOAD_TIMEOUT_MESSAGE)
    except urllib.error.HTTPError as error:
        log_event("download_error", {"reason": "HTTP 오류", "status": error.code})
        raise RuntimeError(f"이미지 다운로드 실패: HTTP {error.code}") from error
    except urllib.error.URLError as error:
        log_event("download_error", {"reason": "네트워크 오류"})
        raise RuntimeError(
            "이미지 다운로드 중 네트워크 오류가 발생했습니다."
        ) from error


def get_image_payload(
    image_source, cancel_check=None, on_download_start=None, on_download_done=None
):
    if image_source["type"] == "file":
        path = image_source["value"]
        mime_type = get_mime_type(path)
        if not mime_type:
            raise ValueError(
                "지원하지 않는 이미지 형식입니다. jpg/png/webp만 지원합니다."
            )
        else:
            data = Path(path).read_bytes()
            data, size_bytes = prepare_image_bytes(data, mime_type, "file")
            image_b64 = base64.b64encode(data).decode("utf-8")
            log_event(
                "image_ready",
                {"source": "file", "mime_type": mime_type, "size_bytes": size_bytes},
            )
            return (image_b64, mime_type, size_bytes)
    else:
        if image_source["type"] == "url":
            if on_download_start:
                on_download_start()
            data, mime_type = download_image_from_url(
                image_source["value"], cancel_check=cancel_check
            )
            if on_download_done:
                on_download_done()
            data, size_bytes = prepare_image_bytes(data, mime_type, "url")
            image_b64 = base64.b64encode(data).decode("utf-8")
            log_event(
                "image_ready",
                {"source": "url", "mime_type": mime_type, "size_bytes": size_bytes},
            )
            return (image_b64, mime_type, size_bytes)
        else:
            if image_source["type"] == "url_data":
                data = image_source["value"]
                mime_type = image_source.get("mime_type", "image/png")
                data, size_bytes = prepare_image_bytes(data, mime_type, "url_cached")
                image_b64 = base64.b64encode(data).decode("utf-8")
                log_event(
                    "image_ready",
                    {
                        "source": "url_cached",
                        "mime_type": mime_type,
                        "size_bytes": size_bytes,
                    },
                )
                return (image_b64, mime_type, size_bytes)
            else:
                if image_source["type"] == "drop_data":
                    data = image_source["value"]
                    mime_type = image_source.get("mime_type", "image/png")
                    data, size_bytes = prepare_image_bytes(data, mime_type, "drop")
                    image_b64 = base64.b64encode(data).decode("utf-8")
                    log_event(
                        "image_ready",
                        {
                            "source": "drop",
                            "mime_type": mime_type,
                            "size_bytes": size_bytes,
                        },
                    )
                    return (image_b64, mime_type, size_bytes)
                else:
                    if image_source["type"] == "clipboard":
                        data = image_source["value"]
                        mime_type = image_source.get("mime_type", "image/png")
                        data, size_bytes = prepare_image_bytes(
                            data, mime_type, "clipboard"
                        )
                        image_b64 = base64.b64encode(data).decode("utf-8")
                        log_event(
                            "image_ready",
                            {
                                "source": "clipboard",
                                "mime_type": mime_type,
                                "size_bytes": size_bytes,
                            },
                        )
                        return (image_b64, mime_type, size_bytes)
                    else:
                        raise ValueError("이미지 입력을 처리할 수 없습니다.")


def build_generation_config(thinking_level):
    config = {"temperature": 0.3, "maxOutputTokens": MAX_OUTPUT_TOKENS}
    if thinking_level:
        config["thinkingConfig"] = {"thinkingLevel": thinking_level}
    return config


def validate_model_access(model_name, api_key):
    import urllib.request
    import urllib.error

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}"
    request = urllib.request.Request(
        url,
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            if response.status != 200:
                raise RuntimeError(f"모델 확인 실패: HTTP {response.status}")
    except urllib.error.HTTPError as error:
        try:
            err = json.loads(error.read().decode("utf-8"))
            message = err.get("error", {}).get("message", "")
        except Exception:
            message = ""
        raise RuntimeError(f"모델 확인 실패: HTTP {error.code} {message}") from error
    except urllib.error.URLError:
        raise RuntimeError("모델 확인 중 네트워크 오류가 발생했습니다.")


def call_gemini(
    image_b64,
    mime_type,
    api_key,
    instruction,
    image_size_bytes,
    model_name,
    thinking_level,
    keyword_text,
    cancel_check=None,
):
    url = API_URL_TEMPLATE.format(model=model_name)
    body = {
        "contents": [
            {
                "parts": [
                    {"inline_data": {"mime_type": mime_type, "data": image_b64}},
                    {"text": instruction},
                ]
            }
        ],
        "generationConfig": build_generation_config(thinking_level),
    }
    data = json.dumps(body).encode("utf-8")
    log_event(
        "request",
        {
            "model": model_name,
            "mime_type": mime_type,
            "image_size_bytes": image_size_bytes,
            "instruction_chars": len(instruction),
            "keyword_chars": len(keyword_text or ""),
            "keyword_preview": build_keyword_preview(keyword_text),
            "keyword_non_english": is_non_english_text(keyword_text),
            "max_output_tokens": MAX_OUTPUT_TOKENS,
            "temperature": 0.3,
            "thinking_level": thinking_level,
        },
    )
    import urllib.request
    import urllib.error

    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
        method="POST",
    )
    try:
        if cancel_check and cancel_check():
            raise RuntimeError(CANCELLED_MESSAGE)
        else:
            with urllib.request.urlopen(request, timeout=40) as response:
                raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        try:
            err = json.loads(error.read().decode("utf-8"))
            message = err.get("error", {}).get("message", "")
        except Exception:
            message = ""
        else:
            pass
        log_event("http_error", {"status": error.code, "message": message})
        raise RuntimeError(f"API 오류: {error.code} {message}") from error
    except urllib.error.URLError:
        log_event("network_error", {})
        raise RuntimeError("네트워크 오류가 발생했습니다. 인터넷 연결을 확인하세요.")
    data = json.loads(raw)
    candidate = data.get("candidates", [{}])[0]
    parts = candidate.get("content", {}).get("parts", [])
    texts = [p.get("text", "") for p in parts if p.get("text")]
    finish_reason = candidate.get("finishReason", "")
    combined = "\n".join(texts).strip()
    if cancel_check and cancel_check():
        raise RuntimeError(CANCELLED_MESSAGE)
    else:
        usage = data.get("usageMetadata", {})
        log_event(
            "response",
            {
                "finish_reason": finish_reason,
                "text_chars": len(combined),
                "text_preview": combined[:200],
                "usage": usage,
            },
        )
        return (combined, finish_reason)


def call_gemini_stream(
    image_b64,
    mime_type,
    api_key,
    instruction,
    image_size_bytes,
    model_name,
    thinking_level,
    keyword_text,
    on_chunk=None,
    cancel_check=None,
):
    url = API_STREAM_URL_TEMPLATE.format(model=model_name)
    body = {
        "contents": [
            {
                "parts": [
                    {"inline_data": {"mime_type": mime_type, "data": image_b64}},
                    {"text": instruction},
                ]
            }
        ],
        "generationConfig": build_generation_config(thinking_level),
    }
    data = json.dumps(body).encode("utf-8")
    log_event(
        "request",
        {
            "model": model_name,
            "mime_type": mime_type,
            "image_size_bytes": image_size_bytes,
            "instruction_chars": len(instruction),
            "keyword_chars": len(keyword_text or ""),
            "keyword_preview": build_keyword_preview(keyword_text),
            "keyword_non_english": is_non_english_text(keyword_text),
            "max_output_tokens": MAX_OUTPUT_TOKENS,
            "temperature": 0.3,
            "thinking_level": thinking_level,
            "streaming": True,
        },
    )
    import urllib.request
    import urllib.error

    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
            "Accept": "text/event-stream",
        },
        method="POST",
    )
    combined = ""
    finish_reason = ""
    raw_buffer = ""
    try:
        if cancel_check and cancel_check():
            raise RuntimeError(CANCELLED_MESSAGE)
        with urllib.request.urlopen(request, timeout=60) as response:
            while True:
                if cancel_check and cancel_check():
                    raise RuntimeError(CANCELLED_MESSAGE)
                chunk = response.read(1024)
                if not chunk:
                    break
                raw_buffer += chunk.decode("utf-8", errors="ignore")
                while "\n" in raw_buffer:
                    line, raw_buffer = raw_buffer.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    if line.startswith("data:"):
                        payload = line[5:].strip()
                    else:
                        payload = line
                    if payload == "[DONE]":
                        raw_buffer = ""
                        continue
                    try:
                        data_json = json.loads(payload)
                        candidate = data_json.get("candidates", [{}])[0]
                        parts = candidate.get("content", {}).get("parts", [])
                        texts = [p.get("text", "") for p in parts if p.get("text")]
                        if texts:
                            piece = "".join(texts)
                            combined += piece
                            if on_chunk:
                                on_chunk(piece)
                        finish_reason = candidate.get("finishReason", finish_reason)
                    except json.JSONDecodeError:
                        pass

            if not combined and raw_buffer:
                try:
                    data_json = json.loads(raw_buffer)
                    candidate = data_json.get("candidates", [{}])[0]
                    parts = candidate.get("content", {}).get("parts", [])
                    texts = [p.get("text", "") for p in parts if p.get("text")]
                    combined = "\n".join(texts).strip()
                    finish_reason = candidate.get("finishReason", finish_reason)
                except Exception:
                    pass
            log_event(
                "response",
                {
                    "finish_reason": finish_reason,
                    "text_chars": len(combined),
                    "text_preview": combined[:200],
                },
            )
            return (combined, finish_reason)

    except urllib.error.HTTPError as error:
        try:
            err = json.loads(error.read().decode("utf-8"))
            message = err.get("error", {}).get("message", "")
        except Exception:
            message = ""
        log_event("http_error", {"status": error.code, "message": message})
        raise RuntimeError(f"API 오류: {error.code} {message}") from error
    except urllib.error.URLError:
        log_event("network_error", {})
        raise RuntimeError("네트워크 오류가 발생했습니다. 인터넷 연결을 확인하세요.")


def generate_prompt(
    image_source,
    api_key,
    model_name,
    thinking_level,
    keyword_text,
    max_retry=2,
    on_stream_start=None,
    on_stream_chunk=None,
    on_download_start=None,
    on_download_done=None,
    cancel_check=None,
):
    image_b64, mime_type, image_size_bytes = get_image_payload(
        image_source,
        cancel_check=cancel_check,
        on_download_start=on_download_start,
        on_download_done=on_download_done,
    )
    keyword_text = (keyword_text or "").strip()
    instruction = build_instruction(keyword_text=keyword_text)
    last_text = ""
    last_word_count = 0
    retry_reasons = []
    for _ in range(max_retry + 1):
        if cancel_check and cancel_check():
            raise RuntimeError(CANCELLED_MESSAGE)
        else:
            if on_stream_start:
                on_stream_start()
            if on_stream_chunk:
                text, finish_reason = call_gemini_stream(
                    image_b64,
                    mime_type,
                    api_key,
                    instruction,
                    image_size_bytes,
                    model_name,
                    thinking_level,
                    keyword_text,
                    on_stream_chunk,
                    cancel_check=cancel_check,
                )
            else:
                text, finish_reason = call_gemini(
                    image_b64,
                    mime_type,
                    api_key,
                    instruction,
                    image_size_bytes,
                    model_name,
                    thinking_level,
                    keyword_text,
                    cancel_check=cancel_check,
                )
            text = normalize_prompt(text)
            last_text = text
            word_count = count_words(text)
            last_word_count = word_count
            truncated = looks_truncated(text, finish_reason)
            keyword_non_english = is_non_english_text(keyword_text)
            keyword_matched = None
            if keyword_text:
                if not keyword_non_english:
                    keyword_matched = keyword_text.lower() in text.lower()
                log_event(
                    "keyword_check",
                    {
                        "keyword_preview": build_keyword_preview(keyword_text),
                        "keyword_non_english": keyword_non_english,
                        "matched": keyword_matched,
                    },
                )
            log_event(
                "check",
                {
                    "word_count": word_count,
                    "truncated": truncated,
                    "finish_reason": finish_reason,
                },
            )
            if MIN_PROMPT_WORDS <= word_count <= MAX_PROMPT_WORDS and (not truncated):
                log_event(
                    "generation_summary",
                    {"retries": len(retry_reasons), "retry_reasons": retry_reasons},
                )
                return (text, word_count)
            issues = []
            log_issues = []
            if word_count < MIN_PROMPT_WORDS or word_count > MAX_PROMPT_WORDS:
                issues.append(f"{word_count} words")
                log_issues.append(f"단어 수 {word_count}")
            if truncated:
                issues.append("ended mid-sentence or was cut off")
                log_issues.append("문장이 중간에 끊김")
            if finish_reason and finish_reason != "STOP":
                issues.append(f"finish_reason={finish_reason}")
                log_issues.append(f"종료 사유 {finish_reason}")
            retry_reasons.append(", ".join(log_issues) if log_issues else "알 수 없음")
            log_event(
                "retry",
                {
                    "attempt": len(retry_reasons),
                    "word_count": word_count,
                    "finish_reason": finish_reason,
                    "reasons": log_issues,
                },
            )
            issue_note = (
                " and ".join(issues)
                if issues
                else "not within the requested constraints"
            )
            instruction = (
                build_instruction(keyword_text=keyword_text)
                + f"\n\nThe previous output {issue_note}. Regenerate a complete paragraph that ends with a full sentence and fits {MIN_PROMPT_WORDS} to {MAX_PROMPT_WORDS} words."
            )
    log_event(
        "generation_summary",
        {
            "retries": len(retry_reasons),
            "retry_reasons": retry_reasons,
            "result": "fallback",
        },
    )
    return (last_text, last_word_count)


def load_history():
    if not HISTORY_FILE.exists():
        return []
    else:
        lines = [
            line.strip()
            for line in HISTORY_FILE.read_text(encoding="utf-8").splitlines()
        ]
        lines = [line for line in lines if line]
        return lines[-MAX_UI_HISTORY:]


def append_history(prompt):
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    with HISTORY_FILE.open("a", encoding="utf-8") as file:
        file.write(prompt + "\n")


def apply_design_system(root):
    colors = DESIGN_TOKENS["colors"]
    fonts = DESIGN_TOKENS["typography"]
    spacing = DESIGN_TOKENS["spacing"]
    style = ttk.Style(root)
    if "clam" in style.theme_names():
        style.theme_use("clam")
    root.configure(background=colors["bg"])
    root.option_add("*Font", fonts["base"])
    style.configure("App.TFrame", background=colors["bg"])
    style.configure("Card.TFrame", background=colors["surface"])
    style.configure(
        "TLabel", background=colors["bg"], foreground=colors["text_primary"]
    )
    style.configure(
        "Secondary.TLabel", background=colors["bg"], foreground=colors["text_secondary"]
    )
    style.configure(
        "Muted.TLabel", background=colors["bg"], foreground=colors["text_muted"]
    )
    style.configure(
        "Title.TLabel",
        background=colors["bg"],
        foreground=colors["text_primary"],
        font=fonts["title"],
    )
    style.configure(
        "Card.TLabel", background=colors["surface"], foreground=colors["text_primary"]
    )
    style.configure(
        "CardSecondary.TLabel",
        background=colors["surface"],
        foreground=colors["text_secondary"],
    )
    style.configure(
        "CardMuted.TLabel",
        background=colors["surface"],
        foreground=colors["text_muted"],
    )
    style.configure("TLabelframe", background=colors["bg"])
    style.configure(
        "TLabelframe.Label",
        background=colors["bg"],
        foreground=colors["text_secondary"],
        font=fonts["label"],
    )
    style.configure(
        "Card.TLabelframe", background=colors["surface"], borderwidth=1, relief="flat"
    )
    style.configure(
        "Card.TLabelframe.Label",
        background=colors["surface"],
        foreground=colors["text_secondary"],
        font=fonts["label"],
    )
    style.configure(
        "TButton",
        padding=(spacing["md"], spacing["xs"]),
        background=colors["surface"],
        foreground=colors["text_primary"],
        relief="flat",
    )
    style.map(
        "TButton",
        background=[
            ("active", colors["surface_alt"]),
            ("disabled", colors["surface_alt"]),
        ],
        foreground=[("disabled", colors["text_secondary"])],
    )
    style.configure(
        "Accent.TButton",
        padding=(spacing["md"], spacing["xs"]),
        background=colors["accent"],
        foreground="#FFFFFF",
        relief="flat",
    )
    style.map(
        "Accent.TButton",
        background=[
            ("active", colors["accent_hover"]),
            ("pressed", colors["accent_active"]),
            ("disabled", colors["border"]),
        ],
        foreground=[("disabled", colors["text_secondary"])],
    )
    style.configure(
        "Secondary.TButton",
        padding=(spacing["md"], spacing["xs"]),
        background=colors["surface_alt"],
        foreground=colors["text_primary"],
        relief="flat",
    )
    style.map(
        "Secondary.TButton",
        background=[
            ("active", colors["accent_active"]),
            ("disabled", colors["surface_alt"]),
        ],
        foreground=[("active", "#FFFFFF"), ("disabled", colors["text_secondary"])],
    )
    style.configure(
        "TEntry",
        padding=(spacing["sm"], spacing["xs"]),
        fieldbackground=colors["surface"],
        foreground=colors["text_primary"],
    )
    style.map("TEntry", fieldbackground=[("disabled", colors["surface_alt"])])
    style.configure(
        "TScrollbar",
        background=colors["surface_alt"],
        troughcolor=colors["bg"],
        arrowcolor=colors["text_secondary"],
    )
    return (colors, fonts, spacing)


class WindowsDropTarget:
    _com_interfaces_ = [pythoncom.IID_IDropTarget] if WIN_DND_AVAILABLE else []
    _public_methods_ = ["DragEnter", "DragOver", "DragLeave", "Drop"]

    def __init__(self, app):
        self.app = app
        self._data_obj = None

    def DragEnter(self, data_obj, key_state, pt, effect):
        self._data_obj = data_obj
        return self.app.win_drop_effect(data_obj)

    def DragOver(self, key_state, pt, effect):
        if not self._data_obj:
            return shellcon.DROPEFFECT_NONE
        else:
            return self.app.win_drop_effect(self._data_obj)

    def DragLeave(self):
        self._data_obj = None

    def Drop(self, data_obj, key_state, pt, effect):
        self._data_obj = None
        return self.app.handle_win_drop(data_obj)


class PromptApp:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("1102x1310")
        self.root.minsize(1102, 1310)
        self.image_source = None
        self.history = load_history()
        self.last_duration_sec = None
        self.url_apply_after_id = None
        self.api_dialog = None
        self.cancel_requested = False
        self.generation_in_progress = False
        self.download_in_progress = False
        self.download_cancel_requested = False
        self.download_token = 0
        self.download_url = ""
        self.win_drop_enabled = False
        self._win_drop_target = None
        self._win_drop_target_com = None
        self._win_drop_formats = {}
        self.model_name = DEFAULT_MODEL
        self.model_thinking_level = MODEL_THINKING_LEVELS.get(self.model_name)
        self.keyword_enabled = True
        self.create_ui()
        self.refresh_history_list()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(100, self.ensure_api_key)
        log_event(
            "startup",
            {
                "win_dnd_available": WIN_DND_AVAILABLE,
                "win_dnd_error": WIN_DND_IMPORT_ERROR,
                "tkinterdnd_available": DND_AVAILABLE,
                "pil_available": PIL_AVAILABLE,
                "model": self.model_name,
                "thinking_level": self.model_thinking_level,
            },
        )

    def create_ui(self):
        colors = DESIGN_TOKENS["colors"]
        spacing = DESIGN_TOKENS["spacing"]
        self.colors = colors
        self.spacing = spacing
        header = ttk.Frame(self.root, style="App.TFrame")
        header.pack(fill="x", padx=spacing["lg"], pady=(spacing["lg"], spacing["sm"]))
        header_top = ttk.Frame(header, style="App.TFrame")
        header_top.pack(fill="x")
        title = ttk.Label(header_top, text="GPI 1.3v", style="Title.TLabel")
        title.pack(side="left", anchor="w")
        header_right = ttk.Frame(header_top, style="App.TFrame")
        header_right.pack(side="right", anchor="e")
        ttk.Label(header_right, text="모델", style="Secondary.TLabel").grid(
            row=0, column=0, padx=(0, spacing["xs"]), sticky="e"
        )
        self.model_var = tk.StringVar(value=self.model_name)
        self.model_combo = ttk.Combobox(
            header_right,
            textvariable=self.model_var,
            values=MODEL_OPTIONS,
            state="readonly",
            width=28,
        )
        self.model_combo.grid(row=0, column=1, padx=(0, spacing["sm"]), sticky="e")
        self.model_combo.bind("<<ComboboxSelected>>", self.on_model_change)
        self.api_key_button = ttk.Button(
            header_right,
            text="API 키 설정",
            command=self.open_api_key_dialog,
            style="Secondary.TButton",
        )
        self.api_key_button.grid(row=0, column=2, sticky="e")
        subtitle = ttk.Label(
            header,
            text="드래그앤드랍 또는 파일 선택으로 이미지 업로드 후 프롬프트를 생성합니다.",
            style="Secondary.TLabel",
        )
        subtitle.pack(anchor="w", pady=(spacing["xs"], 0))
        content = ttk.Frame(self.root, style="App.TFrame")
        content.pack(fill="both", expand=True, padx=spacing["lg"], pady=spacing["sm"])
        left = ttk.Frame(content, style="App.TFrame")
        left.pack(side="left", fill="both", expand=True, padx=(0, spacing["sm"]))
        right = ttk.Frame(content, style="App.TFrame", width=280)
        right.pack(side="right", fill="y")
        drop_box = ttk.LabelFrame(left, text="이미지 업로드", style="Card.TLabelframe")
        drop_box.pack(fill="x", pady=(0, spacing["sm"]))
        self.drop_label = tk.Label(
            drop_box,
            text="여기에 이미지를 드래그앤드랍하세요.\n이미지 URL도 드롭할 수 있습니다.",
            anchor="center",
            justify="center",
            background=colors["surface_alt"],
            foreground=colors["text_secondary"],
            bd=1,
            relief="groove",
            padx=spacing["lg"],
            pady=spacing["lg"],
        )
        self.drop_label.pack(fill="x", padx=spacing["sm"], pady=spacing["sm"])
        self.drop_label.bind("<Enter>", self.on_drop_hover)
        self.drop_label.bind("<Leave>", self.on_drop_leave)
        if WIN_DND_AVAILABLE and self.setup_windows_drop_target():
            pass
        else:
            if DND_AVAILABLE:
                self.drop_label.drop_target_register(DND_FILES, DND_TEXT)
                self.drop_label.dnd_bind("<<Drop>>", self.on_drop)
            else:
                self.drop_label.configure(
                    text="드래그앤드랍 사용 불가.\n파일 선택 버튼을 사용하세요."
                )
        file_row = ttk.Frame(drop_box, style="Card.TFrame")
        file_row.pack(fill="x", padx=spacing["sm"], pady=(0, spacing["sm"]))
        self.file_path_var = tk.StringVar(value="선택된 파일 없음")
        self.file_label = ttk.Label(
            file_row, textvariable=self.file_path_var, style="CardSecondary.TLabel"
        )
        self.file_label.pack(side="left", fill="x", expand=True)
        self.set_file_label_color(False)
        ttk.Button(
            file_row,
            text="붙여넣기 (Ctrl+V)",
            command=self.on_paste,
            style="Secondary.TButton",
        ).pack(side="right")
        ttk.Button(
            file_row,
            text="파일 선택",
            command=self.on_pick_file,
            style="Secondary.TButton",
        ).pack(side="right", padx=(spacing["xs"], 0))
        url_row = ttk.Frame(drop_box, style="Card.TFrame")
        url_row.pack(fill="x", padx=spacing["sm"], pady=(0, spacing["sm"]))
        ttk.Label(url_row, text="이미지 URL", style="CardSecondary.TLabel").pack(
            side="left"
        )
        self.url_var = tk.StringVar()
        self.url_entry = ttk.Entry(url_row, textvariable=self.url_var)
        self.url_entry.pack(
            side="left", fill="x", expand=True, padx=(spacing["sm"], spacing["sm"])
        )
        self.url_entry.bind("<Return>", lambda event: self.on_apply_url())
        self.url_var.trace_add("write", self.on_url_var_change)
        action_row = ttk.Frame(left, style="App.TFrame")
        action_row.pack(fill="x", pady=(0, spacing["sm"]))
        self.generate_button = ttk.Button(
            action_row,
            text="프롬프트 생성 (F1)",
            command=self.on_generate,
            style="Accent.TButton",
        )
        self.generate_button.pack(side="left")
        keyword_frame = ttk.Frame(action_row, style="App.TFrame")
        keyword_frame.pack(side="left", padx=(spacing["sm"], 0))
        ttk.Label(keyword_frame, text="키워드", style="Secondary.TLabel").pack(
            side="left"
        )
        self.keyword_var = tk.StringVar(value="고화질 4K 극사실주의 사진, 동양인,")
        self.keyword_entry = ttk.Entry(
            keyword_frame, textvariable=self.keyword_var, width=22
        )
        self.keyword_entry.pack(side="left", padx=(spacing["xs"], 0))
        self.keyword_var.set("고화질 4K 극사실주의 사진, 동양인,")
        self.update_keyword_state()
        self.retry_button = ttk.Button(
            action_row,
            text="재실행 (F5)",
            command=self.on_retry,
            style="Secondary.TButton",
        )
        self.retry_button.pack(side="left", padx=(spacing["sm"], 0))
        self.cancel_button = ttk.Button(
            action_row, text="중단", command=self.on_cancel, style="Secondary.TButton"
        )
        self.cancel_button.pack(side="left", padx=(spacing["sm"], 0))
        self.cancel_button.configure(state="disabled")
        self.status_var = tk.StringVar(value="대기 중")
        self.status_label = ttk.Label(
            action_row, textvariable=self.status_var, style="Secondary.TLabel"
        )
        self.status_label.pack(side="right")
        output_frame = ttk.LabelFrame(left, text="", style="Card.TLabelframe")
        output_frame.pack(fill="both", expand=True)
        output_header = ttk.Frame(output_frame, style="Card.TFrame")
        output_header.pack(fill="x", padx=spacing["sm"], pady=(spacing["sm"], 0))
        ttk.Label(
            output_header, text="출력된 프롬프트", style="CardSecondary.TLabel"
        ).pack(side="left")
        header_right = ttk.Frame(output_header, style="Card.TFrame")
        header_right.pack(side="right")
        self.output_time_var = tk.StringVar(value="생성 시간: -")
        ttk.Label(
            header_right,
            textvariable=self.output_time_var,
            style="CardSecondary.TLabel",
        ).pack(side="left")
        self.copy_button = ttk.Button(
            header_right,
            text="프롬프트복사 (Ctrl+C)",
            command=self.on_copy,
            style="Secondary.TButton",
        )
        self.copy_button.pack(side="left", padx=(spacing["sm"], 0))
        self.clear_button = ttk.Button(
            header_right,
            text="CLEAR",
            command=self.on_clear_output,
            style="Secondary.TButton",
        )
        self.clear_button.pack(side="left", padx=(spacing["sm"], 0))
        self.output_text = tk.Text(output_frame, wrap="word", height=18)
        self.output_text.pack(side="left", fill="both", expand=True)
        output_scroll = ttk.Scrollbar(output_frame, command=self.output_text.yview)
        output_scroll.pack(side="right", fill="y")
        self.output_text.configure(yscrollcommand=output_scroll.set)
        self.output_text.configure(
            background=colors["surface_alt_strong"],
            foreground=colors["text_primary"],
            insertbackground=colors["text_primary"],
            selectbackground=colors["accent"],
            selectforeground="#FFFFFF",
            highlightthickness=2,
            highlightbackground=colors["border_strong"],
            highlightcolor=colors["accent"],
            relief="flat",
            padx=spacing["sm"],
            pady=spacing["sm"],
        )
        self.output_text.configure(state="disabled")
        self.output_text.bind("<FocusIn>", self.on_output_focus_in)
        self.output_text.bind("<FocusOut>", self.on_output_focus_out)
        self.output_text.bind("<Button-1>", self.on_output_click)
        history_frame = ttk.LabelFrame(
            right, text="최근 프롬프트 (20개)", style="Card.TLabelframe"
        )
        history_frame.pack(fill="both", expand=True)
        self.history_list = tk.Listbox(history_frame, height=20)
        self.history_list.pack(
            fill="both", expand=True, padx=spacing["sm"], pady=spacing["sm"]
        )
        self.history_list.bind("<<ListboxSelect>>", self.on_history_select)
        self.history_list.configure(
            background=colors["surface"],
            foreground=colors["text_primary"],
            selectbackground=colors["accent"],
            selectforeground="#FFFFFF",
            highlightthickness=1,
            highlightbackground=colors["border"],
            relief="flat",
        )
        note = ttk.Label(
            right,
            text="히스토리는 prompt만 저장됩니다.\n파일: history.txt",
            style="Muted.TLabel",
        )
        note.pack(side="bottom", fill="x", pady=(spacing["sm"], 0))
        self.bind_shortcuts()
        self.update_action_state()

    def set_busy(self, busy=True, message=None):
        self.generation_in_progress = busy
        state = "disabled" if busy else "normal"
        self.generate_button.configure(state=state)
        self.retry_button.configure(state=state)
        self.copy_button.configure(state=state)
        if hasattr(self, "clear_button"):
            self.clear_button.configure(state=state)
        if hasattr(self, "cancel_button"):
            self.cancel_button.configure(state="normal" if busy else "disabled")
        if busy:
            self.status_var.set(message or "처리 중...")
        else:
            self.status_var.set(message or "대기 중")
        if busy:
            self.status_label.configure(foreground=self.colors["accent"])
        else:
            self.status_label.configure(foreground=self.colors["success"])
            self.update_action_state()

    def setup_windows_drop_target(self):
        if not WIN_DND_AVAILABLE:
            log_event(
                "win_drop_init", {"enabled": False, "reason": "pywin32 로드 실패"}
            )
            return False
        try:
            pythoncom.OleInitialize()
        except Exception:
            pass
        try:
            self.root.update_idletasks()
            hwnd = self.drop_label.winfo_id()
            log_event("win_drop_register_start", {"hwnd": hwnd})
            self._win_drop_target = WindowsDropTarget(self)
            self._win_drop_target_com = win32com.server.util.wrap(
                self._win_drop_target, pythoncom.IID_IDropTarget
            )
            pythoncom.RegisterDragDrop(hwnd, self._win_drop_target_com)
            self._win_drop_formats = {
                "filedesc_w": (
                    (
                        CF_FILEDESCRIPTORW,
                        None,
                        pythoncom.DVASPECT_CONTENT,
                        (-1),
                        pythoncom.TYMED_HGLOBAL,
                    )
                    if CF_FILEDESCRIPTORW
                    else None
                ),
                "filedesc_a": (
                    (
                        CF_FILEDESCRIPTORA,
                        None,
                        pythoncom.DVASPECT_CONTENT,
                        (-1),
                        pythoncom.TYMED_HGLOBAL,
                    )
                    if CF_FILEDESCRIPTORA
                    else None
                ),
                "filecontents": (
                    CF_FILECONTENTS,
                    None,
                    pythoncom.DVASPECT_CONTENT,
                    0,
                    pythoncom.TYMED_ISTREAM
                    | pythoncom.TYMED_HGLOBAL
                    | pythoncom.TYMED_FILE,
                ),
                "hdrop": (
                    win32con.CF_HDROP,
                    None,
                    pythoncom.DVASPECT_CONTENT,
                    (-1),
                    pythoncom.TYMED_HGLOBAL,
                ),
                "text_w": (
                    win32con.CF_UNICODETEXT,
                    None,
                    pythoncom.DVASPECT_CONTENT,
                    (-1),
                    pythoncom.TYMED_HGLOBAL,
                ),
                "text_a": (
                    win32con.CF_TEXT,
                    None,
                    pythoncom.DVASPECT_CONTENT,
                    (-1),
                    pythoncom.TYMED_HGLOBAL,
                ),
            }
            self.win_drop_enabled = True
            log_event("win_drop_ready", {"enabled": True})
            return True
        except Exception as error:
            log_event("win_drop_error", {"error": str(error)})
            self.win_drop_enabled = False
            return False

    def win_drop_query_format(self, data_obj, fmt):
        if not fmt or not data_obj:
            return False
        else:
            try:
                data_obj.QueryGetData(fmt)
            except Exception:
                return False
            return True

    def win_drop_can_accept(self, data_obj):
        for fmt in self._win_drop_formats.values():
            if self.win_drop_query_format(data_obj, fmt):
                return True
        return False

    def win_drop_effect(self, data_obj):
        if not WIN_DND_AVAILABLE or not data_obj:
            return shellcon.DROPEFFECT_NONE
        else:
            if self.win_drop_can_accept(data_obj):
                return shellcon.DROPEFFECT_COPY
            else:
                return shellcon.DROPEFFECT_NONE

    def stgmedium_to_bytes(self, stgmedium):
        if not stgmedium:
            return
        else:
            data = stgmedium.data
            if stgmedium.tymed == pythoncom.TYMED_ISTREAM:
                return read_istream_all(data)
            else:
                if stgmedium.tymed == pythoncom.TYMED_HGLOBAL:
                    if isinstance(data, (bytes, bytearray)):
                        return bytes(data)
                    else:
                        if isinstance(data, str):
                            return data.encode("latin1", errors="ignore")
                if (
                    stgmedium.tymed == pythoncom.TYMED_FILE
                    and isinstance(data, str)
                    and Path(data).exists()
                ):
                    return Path(data).read_bytes()
                else:
                    return None

    def get_text_from_data_obj(self, data_obj):
        for key in ["text_w", "text_a"]:
            fmt = self._win_drop_formats.get(key)
            if not fmt or not self.win_drop_query_format(data_obj, fmt):
                continue
            else:
                try:
                    stg = data_obj.GetData(fmt)
                except Exception:
                    pass
                else:
                    raw = stg.data
                    if isinstance(raw, str):
                        return raw.strip()
                    else:
                        if key == "text_w":
                            return raw.decode("utf-16le", errors="ignore").strip()
                        else:
                            return raw.decode("mbcs", errors="ignore").strip()
        return ""

    def get_hdrop_paths(self, data_obj):
        fmt = self._win_drop_formats.get("hdrop")
        if not fmt or not self.win_drop_query_format(data_obj, fmt):
            return []
        else:
            try:
                stg = data_obj.GetData(fmt)
            except Exception:
                return []
            raw = stg.data
            if isinstance(raw, str):
                raw = raw.encode("latin1", errors="ignore")
            return parse_dropfiles(raw)

    def get_file_group_descriptor(self, data_obj):
        fmt_w = self._win_drop_formats.get("filedesc_w")
        fmt_a = self._win_drop_formats.get("filedesc_a")
        if fmt_w and self.win_drop_query_format(data_obj, fmt_w):
            stg = data_obj.GetData(fmt_w)
            raw = stg.data
            if isinstance(raw, str):
                raw = raw.encode("latin1", errors="ignore")
            return parse_file_group_descriptor(raw, wide=True)
        else:
            if fmt_a and self.win_drop_query_format(data_obj, fmt_a):
                stg = data_obj.GetData(fmt_a)
                raw = stg.data
                if isinstance(raw, str):
                    raw = raw.encode("latin1", errors="ignore")
                return parse_file_group_descriptor(raw, wide=False)
            else:
                return []

    def get_file_contents(self, data_obj, index):
        if not CF_FILECONTENTS:
            return
        else:
            fmt = (
                CF_FILECONTENTS,
                None,
                pythoncom.DVASPECT_CONTENT,
                index,
                pythoncom.TYMED_ISTREAM
                | pythoncom.TYMED_HGLOBAL
                | pythoncom.TYMED_FILE,
            )
            try:
                stg = data_obj.GetData(fmt)
            except Exception:
                return None
            return self.stgmedium_to_bytes(stg)

    def try_win_drop_virtual(self, data_obj):
        descriptors = self.get_file_group_descriptor(data_obj)
        if not descriptors:
            return
        else:
            for index, info in enumerate(descriptors):
                name = info.get("name") or f"drop_{index}"
                size_bytes = info.get("size") or 0
                if size_bytes and size_bytes > MAX_FILE_MB * 1024 * 1024:
                    messagebox.showwarning(
                        "알림", f"이미지 용량이 {MAX_FILE_MB}MB를 초과했습니다."
                    )
                    return
                else:
                    data = self.get_file_contents(data_obj, index)
                    if data:
                        mime_type = detect_mime_from_bytes(data, name)
                        if mime_type:
                            return {"name": name, "data": data, "mime_type": mime_type}

    def handle_win_drop(self, data_obj):
        # irreducible cflow, using cdg fallback
        # ***<module>.PromptApp.handle_win_drop: Failure: Compilation Error
        if not WIN_DND_AVAILABLE or not data_obj:
            return shellcon.DROPEFFECT_NONE
        virtual_item = self.try_win_drop_virtual(data_obj)
        if virtual_item:
            log_event(
                "win_drop_virtual",
                {"name": virtual_item["name"], "size_bytes": len(virtual_item["data"])},
            )
            self.set_image_source(
                {
                    "type": "drop_data",
                    "value": virtual_item["data"],
                    "mime_type": virtual_item["mime_type"],
                    "name": virtual_item["name"],
                }
            )
            return shellcon.DROPEFFECT_COPY
        paths = self.get_hdrop_paths(data_obj)
        if paths:
            log_event("win_drop_file", {"path": paths[0]})
            self.set_image_source({"type": "file", "value": paths[0]})
            return shellcon.DROPEFFECT_COPY
        try:
            text = self.get_text_from_data_obj(data_obj)
            if text:
                log_event("win_drop_text", {"preview": text[:120]})
                if is_url(text):
                    self.start_url_download(text)
                    return shellcon.DROPEFFECT_COPY
                messagebox.showwarning(
                    "알림", "드롭한 항목에서 이미지 파일이나 URL을 찾지 못했습니다."
                )
                return shellcon.DROPEFFECT_NONE
        except Exception as error:
            log_event("win_drop_error", {"error": str(error)})
            messagebox.showerror("오류", f"드롭 처리 중 오류가 발생했습니다.\n{error}")
            return shellcon.DROPEFFECT_NONE
        return shellcon.DROPEFFECT_NONE

    def on_drop_hover(self, event=None):
        self.drop_label.configure(
            background=self.colors["surface_alt_strong"],
            foreground=self.colors["text_primary"],
            bd=2,
            relief="ridge",
        )

    def on_drop_leave(self, event=None):
        self.drop_label.configure(
            background=self.colors["surface_alt"],
            foreground=self.colors["text_secondary"],
            bd=1,
            relief="groove",
        )

    def on_pick_file(self):
        file_path = filedialog.askopenfilename(
            title="이미지 선택",
            filetypes=[
                ("Image Files", "*.png;*.jpg;*.jpeg;*.webp"),
                ("All Files", "*.*"),
            ],
        )
        if file_path:
            self.set_image_source({"type": "file", "value": file_path})

    def on_drop(self, event):
        items = extract_drop_candidates(event.data, self.root)
        if not items:
            return
        else:
            for item in items:
                cleaned = normalize_drop_item(item)
                if is_url(cleaned):
                    self.start_url_download(cleaned)
                    return
                else:
                    if Path(cleaned).exists():
                        self.set_image_source({"type": "file", "value": cleaned})
                        return
            messagebox.showwarning(
                "알림", "드롭한 항목에서 이미지 파일이나 URL을 찾지 못했습니다."
            )

    def set_image_source(self, source):
        if self.download_in_progress and source.get("type") != "url_data":
            self.download_token += 1
            self.download_cancel_requested = True
            self.download_in_progress = False
            self.download_url = ""
        self.image_source = source
        label = ""
        if source["type"] == "url":
            label = f"URL: {source['value']}"
            if hasattr(self, "url_var") and self.url_var.get() != source["value"]:
                self.url_var.set(source["value"])
        else:
            if source["type"] == "url_data":
                url_value = source.get("url", "")
                label = f"URL: {url_value}"
                if hasattr(self, "url_var") and self.url_var.get() != url_value:
                    self.url_var.set(url_value)
            else:
                if source["type"] == "drop_data":
                    name = source.get("name") or "드롭 이미지"
                    label = f"드롭 이미지: {name}"
                    if hasattr(self, "url_var") and self.url_var.get():
                        self.url_var.set("")
                else:
                    if source["type"] == "clipboard":
                        label = "클립보드 이미지"
                        if hasattr(self, "url_var") and self.url_var.get():
                            self.url_var.set("")
                    else:
                        label = source["value"]
                        if hasattr(self, "url_var") and self.url_var.get():
                            self.url_var.set("")
        self.file_path_var.set(ellipsize_text(label))
        has_image = source["type"] in ["file", "clipboard", "url_data", "drop_data"]
        self.set_file_label_color(has_image)
        self.update_action_state()

    def set_file_label_color(self, has_image):
        if not hasattr(self, "file_label"):
            return
        else:
            color = (
                self.colors["success"] if has_image else self.colors["text_secondary"]
            )
            self.file_label.configure(foreground=color)

    def update_action_state(self):
        if self.generation_in_progress:
            return
        else:
            if self.download_in_progress:
                self.generate_button.configure(state="disabled")
                self.retry_button.configure(state="disabled")
                if hasattr(self, "cancel_button"):
                    self.cancel_button.configure(state="normal")
                return None
            else:
                ready = self.image_source is not None
                self.generate_button.configure(state="normal" if ready else "disabled")
                self.retry_button.configure(state="normal" if ready else "disabled")
                if hasattr(self, "cancel_button"):
                    self.cancel_button.configure(state="disabled")

    def update_keyword_state(self):
        if not hasattr(self, "keyword_entry"):
            return
        else:
            if self.model_name == "gemini-flash-lite-latest":
                self.keyword_enabled = False
                if hasattr(self, "keyword_var"):
                    self.keyword_var.set("")
                self.keyword_entry.configure(state="disabled")
            else:
                self.keyword_enabled = True
                self.keyword_entry.configure(state="normal")

    def on_model_change(self, event=None):
        # ***<module>.PromptApp.on_model_change: Failure: Different bytecode
        selected = self.model_var.get().strip() if hasattr(self, "model_var") else ""
        if not selected:
            return
        else:
            if selected == self.model_name:
                return
            else:
                if self.generation_in_progress or self.download_in_progress:
                    messagebox.showwarning(
                        "알림", "작업 중에는 모델을 변경할 수 없습니다."
                    )
                    if hasattr(self, "model_var"):
                        self.model_var.set(self.model_name)
                    return None
                else:
                    if selected not in MODEL_OPTIONS:
                        messagebox.showerror("오류", "지원하지 않는 모델입니다.")
                        if hasattr(self, "model_var"):
                            self.model_var.set(self.model_name)
                        return None
                    else:
                        api_key = get_api_key()
                        if not api_key:
                            messagebox.showwarning("알림", "먼저 API 키를 설정하세요.")
                            if hasattr(self, "model_var"):
                                self.model_var.set(self.model_name)
                            self.open_api_key_dialog()
                            return
                        else:
                            previous_status = self.status_var.get()
                            self.status_var.set("모델 확인 중...")
                            if hasattr(self, "model_combo"):
                                self.model_combo.configure(state="disabled")

                            def worker():
                                try:
                                    validate_model_access(selected, api_key)
                                    self.root.after(
                                        0,
                                        lambda sel=selected: self.on_model_change_success(
                                            sel, previous_status
                                        ),
                                    )
                                except Exception as error:
                                    self.root.after(
                                        0,
                                        lambda err=str(
                                            error
                                        ): self.on_model_change_failure(
                                            err, previous_status
                                        ),
                                    )

                            threading.Thread(target=worker, daemon=True).start()

    def on_model_change_success(self, selected, previous_status):
        self.model_name = selected
        self.model_thinking_level = MODEL_THINKING_LEVELS.get(self.model_name)
        if hasattr(self, "model_var"):
            self.model_var.set(self.model_name)
        if hasattr(self, "model_combo"):
            self.model_combo.configure(state="readonly")
        self.update_keyword_state()
        self.status_var.set(previous_status)
        log_event(
            "model_change",
            {"model": self.model_name, "thinking_level": self.model_thinking_level},
        )
        if self.model_name == "gemini-flash-lite-latest":
            messagebox.showinfo("알림", "Model changed\n키워드 기능 사용 불가")
        else:
            messagebox.showinfo("알림", "Model changed")

    def on_model_change_failure(self, message, previous_status):
        if hasattr(self, "model_var"):
            self.model_var.set(self.model_name)
        if hasattr(self, "model_combo"):
            self.model_combo.configure(state="readonly")
        self.status_var.set(previous_status)
        messagebox.showerror("오류", message)

    def ensure_api_key(self):
        if not load_api_key():
            self.open_api_key_dialog()

    def open_api_key_dialog(self):
        if self.api_dialog and self.api_dialog.winfo_exists():
            self.api_dialog.focus_set()
            return
        else:
            dialog = tk.Toplevel(self.root)
            dialog.title("API 키 설정")
            dialog.resizable(False, False)
            dialog.transient(self.root)
            dialog.grab_set()
            self.api_dialog = dialog
            container = ttk.Frame(
                dialog, padding=(self.spacing["lg"], self.spacing["lg"])
            )
            container.pack(fill="both", expand=True)
            ttk.Label(
                container, text="Gemini API 키", style="CardSecondary.TLabel"
            ).pack(anchor="w")
            key_var = tk.StringVar(value=load_api_key())
            key_entry = ttk.Entry(container, textvariable=key_var, show="*")
            key_entry.pack(fill="x", pady=(self.spacing["xs"], self.spacing["sm"]))
            key_entry.focus_set()
            hint = "키는 프로젝트 폴더에 저장됩니다.\n파일: gpi_api_key.txt"
            ttk.Label(container, text=hint, style="Muted.TLabel").pack(anchor="w")
            button_row = ttk.Frame(container, style="App.TFrame")
            button_row.pack(fill="x", pady=(self.spacing["sm"], 0))

            def on_save():
                api_key = key_var.get().strip()
                if not api_key:
                    messagebox.showwarning(
                        "알림", "API 키를 입력하세요.", parent=dialog
                    )
                    return
                else:
                    try:
                        save_api_key(api_key)
                    except Exception:
                        messagebox.showerror(
                            "오류", "API 키 저장에 실패했습니다.", parent=dialog
                        )
                        return None
                    messagebox.showinfo(
                        "완료", "API 키가 저장되었습니다.", parent=dialog
                    )
                    dialog.destroy()

            def on_delete():
                if not load_api_key():
                    messagebox.showinfo(
                        "알림", "저장된 API 키가 없습니다.", parent=dialog
                    )
                    return
                else:
                    if not messagebox.askyesno(
                        "확인", "저장된 API 키를 삭제할까요?", parent=dialog
                    ):
                        return
                    else:
                        try:
                            delete_api_key()
                        except Exception:
                            messagebox.showerror(
                                "오류", "API 키 삭제에 실패했습니다.", parent=dialog
                            )
                            return None
                        messagebox.showinfo(
                            "완료", "API 키가 삭제되었습니다.", parent=dialog
                        )
                        dialog.destroy()

            ttk.Button(
                button_row, text="삭제", command=on_delete, style="Secondary.TButton"
            ).pack(side="right")
            ttk.Button(
                button_row, text="저장", command=on_save, style="Accent.TButton"
            ).pack(side="right", padx=(0, self.spacing["xs"]))

            def on_close():
                dialog.destroy()

            dialog.protocol("WM_DELETE_WINDOW", on_close)
            dialog.update_idletasks()
            x = (
                self.root.winfo_x()
                + self.root.winfo_width() // 2
                - dialog.winfo_width() // 2
            )
            y = (
                self.root.winfo_y()
                + self.root.winfo_height() // 2
                - dialog.winfo_height() // 2
            )
            dialog.geometry(f"+{max(0, x)}+{max(0, y)}")

    def start_url_download(self, url):
        # ***<module>.PromptApp.start_url_download: Failure: Different bytecode
        if not url:
            return
        else:
            if self.download_in_progress and self.download_url == url:
                return
            else:
                if hasattr(self, "url_var") and self.url_var.get() != url:
                    self.url_var.set(url)
                self.download_token += 1
                token = self.download_token
                self.download_in_progress = True
                self.download_cancel_requested = False
                self.download_url = url
                self.status_var.set("이미지 다운로드 중...")
                self.status_label.configure(foreground=self.colors["accent"])
                self.file_path_var.set(ellipsize_text(f"URL: {url}"))
                self.set_file_label_color(False)
                self.update_action_state()

                def worker():
                    try:
                        data, mime_type = download_image_from_url(
                            url,
                            cancel_check=lambda: self.download_cancel_requested
                            or token != self.download_token,
                        )
                        data, size_bytes = prepare_image_bytes(data, mime_type, "url")
                        if (
                            self.download_cancel_requested
                            or token != self.download_token
                        ):
                            raise RuntimeError(CANCELLED_MESSAGE)
                        self.root.after(
                            0,
                            lambda: self.on_url_download_success(
                                token, url, data, mime_type, size_bytes
                            ),
                        )
                    except Exception as error:
                        self.root.after(
                            0,
                            lambda err=str(error): self.on_url_download_error(
                                token, err
                            ),
                        )

                threading.Thread(target=worker, daemon=True).start()

    def on_url_download_success(self, token, url, data, mime_type, size_bytes):
        if token != self.download_token:
            return
        else:
            self.download_in_progress = False
            self.download_cancel_requested = False
            self.download_url = ""
            self.image_source = {
                "type": "url_data",
                "value": data,
                "mime_type": mime_type,
                "url": url,
            }
            self.file_path_var.set(ellipsize_text(f"URL: {url}"))
            self.set_file_label_color(True)
            self.status_var.set("다운로드 완료")
            self.status_label.configure(foreground=self.colors["success"])
            self.update_action_state()
            log_event(
                "download_ready",
                {
                    "mime_type": mime_type,
                    "size_bytes": size_bytes,
                    "url_host": urlparse(url).netloc,
                },
            )

    def on_url_download_error(self, token, message):
        if token != self.download_token:
            return
        else:
            self.download_in_progress = False
            self.download_cancel_requested = False
            self.download_url = ""
            self.image_source = None
            self.set_file_label_color(False)
            self.update_action_state()
            if message == CANCELLED_MESSAGE:
                self.status_var.set("중단됨")
            else:
                if message == DOWNLOAD_TIMEOUT_MESSAGE:
                    messagebox.showerror(
                        "다운로드 지연",
                        "이미지 다운로드가 15초 안에 완료되지 않았습니다.\n다시 시도하거나 이미지를 우클릭 하여 복사 후 붙여넣기 해주세요.",
                    )
                    self.status_var.set("다운로드 실패")
                else:
                    messagebox.showerror("오류", message)

    def bind_shortcuts(self):
        self.root.bind("<F1>", self.on_generate_shortcut)
        self.root.bind("<F5>", self.on_retry_shortcut)
        self.root.bind_all("<Control-v>", self.on_paste_shortcut)
        self.root.bind_all("<Control-V>", self.on_paste_shortcut)
        self.root.bind_all("<Control-c>", self.on_copy_shortcut)
        self.root.bind_all("<Control-C>", self.on_copy_shortcut)

    def is_text_input_widget(self, widget):
        return isinstance(widget, (tk.Entry, ttk.Entry, tk.Text))

    def widget_has_selection(self, widget):
        try:
            if isinstance(widget, tk.Text):
                return bool(widget.tag_ranges("sel"))
            if isinstance(widget, (tk.Entry, ttk.Entry)):
                return widget.selection_present()
            return False
        except Exception:
            return False

    def on_generate_shortcut(self, event=None):
        self.on_generate()
        return "break"

    def on_retry_shortcut(self, event=None):
        self.on_retry()
        return "break"

    def on_paste_shortcut(self, event=None):
        if event and self.is_text_input_widget(event.widget):
            return
        else:
            self.on_paste()
            return "break"

    def on_copy_shortcut(self, event=None):
        if (
            event
            and self.is_text_input_widget(event.widget)
            and self.widget_has_selection(event.widget)
        ):
            return
        else:
            self.on_copy()
            return "break"

    def on_url_var_change(self, *_):
        if self.url_apply_after_id:
            try:
                self.root.after_cancel(self.url_apply_after_id)
            except Exception:
                pass
        self.url_apply_after_id = self.root.after(1000, self.apply_url_if_ready)

    def apply_url_if_ready(self):
        self.url_apply_after_id = None
        url = self.url_var.get().strip() if hasattr(self, "url_var") else ""
        if not url or not is_url(url):
            return None
        else:
            if self.download_in_progress and self.download_url == url:
                return
            else:
                if (
                    self.image_source
                    and self.image_source.get("type") == "url_data"
                    and (self.image_source.get("url") == url)
                ):
                    return
                else:
                    self.start_url_download(url)

    def try_paste_image(self):
        log_event("paste_try", {"pil_available": PIL_AVAILABLE})
        if not PIL_AVAILABLE:
            return False
        else:
            try:
                data = ImageGrab.grabclipboard()
            except Exception as error:
                log_event(
                    "paste_error", {"stage": "grabclipboard", "error": str(error)}
                )
                return False
            if data is None:
                log_event("paste_none", {})
                return False
            else:
                if isinstance(data, list):
                    log_event("paste_list", {"count": len(data)})
                    for item in data:
                        if item and Path(item).exists():
                            self.set_image_source({"type": "file", "value": item})
                            return True
                    return False
                else:
                    try:
                        buffer = BytesIO()
                        data.save(buffer, format="PNG")
                        image_bytes = buffer.getvalue()
                    except Exception as error:
                        log_event(
                            "paste_error", {"stage": "encode_png", "error": str(error)}
                        )
                        return False
                    log_event("paste_image", {"bytes": len(image_bytes)})
                    self.set_image_source(
                        {
                            "type": "clipboard",
                            "value": image_bytes,
                            "mime_type": "image/png",
                        }
                    )
                    return True

    def get_clipboard_text(self):
        try:
            return self.root.clipboard_get().strip()
        except Exception:
            return ""

    def on_paste(self):
        log_event(
            "paste_start",
            {"focus_widget": str(self.root.focus_get()) if self.root else ""},
        )
        if self.try_paste_image():
            log_event("paste_result", {"result": "image"})
            return
        else:
            text = self.get_clipboard_text()
            log_event(
                "paste_text",
                {"has_text": bool(text), "is_url": is_url(text) if text else False},
            )
            if text and is_url(text):
                self.start_url_download(text)
            else:
                if not PIL_AVAILABLE:
                    log_event("paste_result", {"result": "no_pillow"})
                    messagebox.showwarning(
                        "알림",
                        "클립보드 이미지 붙여넣기는 Pillow 설치가 필요합니다.\n이미지 URL을 복사해 붙여넣을 수도 있습니다.",
                    )
                else:
                    log_event("paste_result", {"result": "empty"})
                    messagebox.showwarning(
                        "알림", "클립보드에 이미지나 URL이 없습니다."
                    )

    def on_apply_url(self):
        url = self.url_var.get().strip() if hasattr(self, "url_var") else ""
        if not url:
            messagebox.showwarning("알림", "이미지 URL을 입력하세요.")
            return
        else:
            if not is_url(url):
                messagebox.showwarning(
                    "알림", "http/https로 시작하는 이미지 URL을 입력하세요."
                )
                return
            else:
                self.start_url_download(url)

    def on_generate(self):
        self.run_generation()

    def on_retry(self):
        if not self.image_source:
            messagebox.showwarning("알림", "먼저 이미지를 선택하세요.")
            return
        else:
            self.run_generation()

    def on_copy(self):
        text = self.output_text.get("1.0", "end").strip()
        if not text:
            selection = self.history_list.curselection()
            if selection:
                text = self.history[selection[0]]
        if not text:
            messagebox.showwarning("알림", "복사할 프롬프트가 없습니다.")
            return
        else:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self.status_var.set("복사 완료")

    def on_clear_output(self):
        self.update_output_text("", append=False)
        self.output_time_var.set("생성 시간: -")
        self.status_var.set("출력 초기화")

    def on_cancel(self):
        if self.cancel_button.cget("state") == "disabled":
            return
        else:
            if self.download_in_progress and (not self.generation_in_progress):
                self.download_cancel_requested = True
                self.download_in_progress = False
                self.download_token += 1
                self.download_url = ""
                self.status_var.set("중단됨")
                log_event("cancel", {"reason": "사용자"})
                self.update_action_state()
                return
            else:
                self.cancel_requested = True
                self.status_var.set("중단 요청됨")
                log_event("cancel", {"reason": "사용자"})
                self.set_busy(False, message="중단됨")

    def on_history_select(self, event):
        selection = self.history_list.curselection()
        if not selection:
            return
        else:
            prompt = self.history[selection[0]]
            self.show_prompt(prompt)

    def on_close(self):
        if self.win_drop_enabled:
            try:
                pythoncom.RevokeDragDrop(self.drop_label.winfo_id())
            except Exception:
                pass
            try:
                pythoncom.OleUninitialize()
            except Exception:
                pass
        self.root.destroy()

    def run_generation(self):
        if self.download_in_progress:
            messagebox.showwarning(
                "알림", "이미지 다운로드 중입니다. 완료 후 다시 시도하세요."
            )
            return
        else:
            if not self.image_source:
                messagebox.showwarning("알림", "이미지를 선택하세요.")
                return
            else:
                api_key = get_api_key()
                if not api_key:
                    self.open_api_key_dialog()
                    return
                else:
                    self.cancel_requested = False
                    if self.image_source.get("type") == "url":
                        self.set_busy(True, message="이미지 다운로드 중...")
                    else:
                        self.set_busy(True)
                    start_time = perf_counter()

                    def worker():
                        try:
                            prompt, word_count = generate_prompt(
                                self.image_source,
                                api_key,
                                self.model_name,
                                self.model_thinking_level,
                                self.get_keyword_text(),
                                on_stream_start=lambda: self.root.after(
                                    0, self.on_stream_start
                                ),
                                on_stream_chunk=lambda piece: self.root.after(
                                    0, lambda: self.on_stream_chunk(piece)
                                ),
                                on_download_start=lambda: self.root.after(
                                    0,
                                    lambda: self.status_var.set(
                                        "이미지 다운로드 중..."
                                    ),
                                ),
                                on_download_done=lambda: self.root.after(
                                    0, lambda: self.status_var.set("처리 중...")
                                ),
                                cancel_check=lambda: self.cancel_requested,
                            )
                            duration = perf_counter() - start_time
                            self.root.after(
                                0,
                                lambda p=prompt, w=word_count, d=duration: self.on_success(
                                    p, w, d
                                ),
                            )
                        except Exception as error:
                            self.root.after(
                                0, lambda err=str(error): self.on_error(err)
                            )

                    threading.Thread(target=worker, daemon=True).start()

    def on_success(self, prompt, word_count, duration):
        if self.cancel_requested:
            self.status_var.set("중단됨")
            return
        else:
            self.set_busy(False)
            self.show_prompt(prompt)
            self.output_time_var.set(f"생성 시간: {duration:.1f}초")
            append_history(prompt)
            self.history.append(prompt)
            if len(self.history) > MAX_UI_HISTORY:
                self.history = self.history[-MAX_UI_HISTORY:]
            self.refresh_history_list()

    def is_invalid_api_error(self, message):
        match = re.search("API 오류:\\s*(\\d+)", message)
        if match:
            code = int(match.group(1))
            if code in (401, 403):
                return True
        lowered = message.lower()
        if "api key" in lowered or "api_key" in lowered or "apikey" in lowered:
            return True
        else:
            if "permission" in lowered or "unauthorized" in lowered:
                return True
            else:
                return False

    def on_error(self, message):
        self.set_busy(False)
        if message == CANCELLED_MESSAGE:
            self.status_var.set("중단됨")
            return
        else:
            if message == DOWNLOAD_TIMEOUT_MESSAGE:
                messagebox.showerror(
                    "다운로드 지연",
                    "이미지 다운로드가 15초 안에 완료되지 않았습니다.\n다시 시도하거나 이미지를 우클릭 하여 복사 후 붙여넣기 해주세요.",
                )
                return
            else:
                if self.is_invalid_api_error(message):
                    messagebox.showerror("오류", "API 값이 유효하지 않습니다.")
                    self.open_api_key_dialog()
                else:
                    messagebox.showerror("오류", message)

    def on_stream_start(self):
        self.update_output_text("", append=False)

    def on_stream_chunk(self, piece):
        self.update_output_text(piece, append=True)

    def show_prompt(self, prompt):
        self.update_output_text(prompt, append=False)

    def update_output_text(self, text, append=False):
        was_disabled = self.output_text.cget("state") == "disabled"
        if was_disabled:
            self.output_text.configure(state="normal")
        if not append:
            self.output_text.delete("1.0", "end")
        if text:
            index = "end" if append else "1.0"
            self.output_text.insert(index, text)
        if was_disabled and self.root.focus_get() != self.output_text:
            self.output_text.configure(state="disabled")

    def set_output_text_editable(self, editable):
        state = "normal" if editable else "disabled"
        if self.output_text.cget("state") != state:
            self.output_text.configure(state=state)

    def get_keyword_text(self):
        if not getattr(self, "keyword_enabled", False):
            return ""
        else:
            return (
                self.keyword_var.get().strip() if hasattr(self, "keyword_var") else ""
            )

    def on_output_focus_in(self, event=None):
        self.set_output_text_editable(True)

    def on_output_focus_out(self, event=None):
        self.set_output_text_editable(False)

    def on_output_click(self, event=None):
        self.set_output_text_editable(True)
        self.output_text.focus_set()

    def refresh_history_list(self):
        self.history_list.delete(0, "end")
        for item in self.history:
            preview = item
            if len(preview) > 80:
                preview = preview[:80] + "..."
            self.history_list.insert("end", preview)


def main():
    root = TkinterDnD.Tk() if DND_AVAILABLE else tk.Tk()
    apply_design_system(root)
    app = PromptApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
