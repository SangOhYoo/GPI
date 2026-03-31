import json
import urllib.request
import urllib.error
import socket
from time import perf_counter
from urllib.parse import urlparse

def is_url(text):
    try:
        parsed = urlparse(text)
    except Exception:
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)

from .config import (
    API_URL_TEMPLATE, API_STREAM_URL_TEMPLATE, 
    CANCELLED_MESSAGE, DOWNLOAD_TIMEOUT_MESSAGE,
    URL_DOWNLOAD_TIMEOUT_SEC, URL_DOWNLOAD_MAX_SECONDS, URL_DOWNLOAD_CHUNK_SIZE,
    MAX_FILE_MB
)
from .utils import log_event
from .image import SUPPORTED_MIME

def validate_model_access(model_name, api_key):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}"
    headers = {"Content-Type": "application/json", "x-goog-api-key": api_key}
    request = urllib.request.Request(url, headers=headers, method="GET")
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

def fetch_available_models(api_key):
    url = "https://generativelanguage.googleapis.com/v1beta/models"
    headers = {"Content-Type": "application/json", "x-goog-api-key": api_key}
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            models = res_data.get("models", [])
            # Filter for models that support generateContent and are current versions
            supported = []
            for m in models:
                name = m.get("name", "")
                # Skip legacy models or specific non-vision models if necessary
                # Most gemini-1.5 and 2.0 models support image input
                if "generateContent" in m.get("supportedGenerationMethods", []):
                    # Strip 'models/' prefix
                    model_id = name.replace("models/", "")
                    supported.append(model_id)
            return sorted(supported)
    except Exception as e:
        raise RuntimeError(f"모델 목록 가져오기 실패: {str(e)}")

def download_image_from_url(url, cancel_check=None):
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8"
    }
    request = urllib.request.Request(url, headers=headers)
    start_time = perf_counter()
    log_event("download_start", {"url": url})
    
    try:
        with urllib.request.urlopen(request, timeout=URL_DOWNLOAD_TIMEOUT_SEC) as response:
            content_type = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
            if content_type not in SUPPORTED_MIME.values():
                raise ValueError("이미지 URL이 아닙니다. jpg/png/webp 이미지 주소를 사용하세요.")
            
            chunks = []
            total = 0
            while True:
                if cancel_check and cancel_check():
                    raise RuntimeError(CANCELLED_MESSAGE)
                if perf_counter() - start_time > URL_DOWNLOAD_MAX_SECONDS:
                    raise RuntimeError(DOWNLOAD_TIMEOUT_MESSAGE)
                
                chunk = response.read(URL_DOWNLOAD_CHUNK_SIZE)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_FILE_MB * 1024 * 1024:
                    raise ValueError(f"이미지 용량이 {MAX_FILE_MB}MB를 초과했습니다.")
                chunks.append(chunk)
            
            data = b"".join(chunks)
            log_event("download_done", {"bytes": len(data), "content_type": content_type})
            return data, content_type
    except socket.timeout:
        raise RuntimeError(DOWNLOAD_TIMEOUT_MESSAGE)
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"이미지 다운로드 실패: HTTP {error.code}")
    except urllib.error.URLError:
        raise RuntimeError("이미지 다운로드 중 네트워크 오류가 발생했습니다.")

def call_gemini(image_b64, mime_type, api_key, instruction, model_name, thinking_level=None):
    url = API_URL_TEMPLATE.format(model=model_name)
    body = {
        "contents": [{
            "parts": [
                {"inline_data": {"mime_type": mime_type, "data": image_b64}},
                {"text": instruction}
            ]
        }],
        "generationConfig": {"temperature": 0.4, "topP": 0.9, "topK": 32}
    }
    if thinking_level:
        body["generationConfig"]["thinkingConfig"] = {"thinkingLevel": thinking_level}
    
    data = json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json", "x-goog-api-key": api_key}
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            candidate = res_data.get("candidates", [{}])[0]
            parts = candidate.get("content", {}).get("parts", [])
            text = "".join([p.get("text", "") for p in parts if p.get("text")])
            return text.strip()
    except Exception as e:
        raise RuntimeError(f"API 호출 오류: {str(e)}")

def call_gemini_stream(image_b64, mime_type, api_key, instruction, model_name, thinking_level=None, on_chunk=None, cancel_check=None):
    url = API_STREAM_URL_TEMPLATE.format(model=model_name)
    body = {
        "contents": [{
            "parts": [
                {"inline_data": {"mime_type": mime_type, "data": image_b64}},
                {"text": instruction}
            ]
        }],
        "generationConfig": {"temperature": 0.4}
    }
    if thinking_level:
        body["generationConfig"]["thinkingConfig"] = {"thinkingLevel": thinking_level}
        
    data = json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json", "x-goog-api-key": api_key}
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    
    combined = ""
    raw_buffer = ""
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            while True:
                if cancel_check and cancel_check():
                    raise RuntimeError(CANCELLED_MESSAGE)
                chunk = response.read(4096)
                if not chunk:
                    break
                
                raw_buffer += chunk.decode("utf-8", errors="ignore")
                while "\n" in raw_buffer:
                    line, raw_buffer = raw_buffer.split("\n", 1)
                    line = line.strip()
                    if not line or not line.startswith("data:"):
                        continue
                    
                    payload = line[5:].strip()
                    try:
                        data_json = json.loads(payload)
                        candidate = data_json.get("candidates", [{}])[0]
                        parts = candidate.get("content", {}).get("parts", [])
                        for p in parts:
                            if p.get("text"):
                                piece = p.get("text")
                                combined += piece
                                if on_chunk:
                                    on_chunk(piece)
                    except json.JSONDecodeError:
                        pass
            return combined.strip()
    except Exception as e:
        raise RuntimeError(f"API 스트리밍 오류: {str(e)}")

