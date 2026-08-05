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

def resolve_llama_api_key(api_key, model_name):
    if model_name and ":" in model_name:
        section = model_name.split(":", 1)[1].strip()
        import configparser
        from pathlib import Path
        presets_path = Path("c:/llama-cpp/presets.ini")
        if presets_path.exists():
            parser = configparser.ConfigParser(strict=False)
            parser.read(presets_path, encoding='utf-8')
            if parser.has_section(section) and parser.has_option(section, 'api-key'):
                return parser.get(section, 'api-key')
    return api_key

def validate_model_access(model_name, api_key):
    if model_name.startswith("local-llama-cpp"):
        return
        
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

def download_image_from_url(url, cancel_check=None, bypass_size_limit=False):
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
                if not bypass_size_limit and total > MAX_FILE_MB * 1024 * 1024:
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

def call_llama_cpp(image_b64, mime_type, api_key, instruction, model_name="default"):
    if mime_type not in ("image/jpeg", "image/png"):
        try:
            from PIL import Image
            from io import BytesIO
            import base64
            img_data = base64.b64decode(image_b64)
            with Image.open(BytesIO(img_data)) as img:
                if img.mode not in ("RGB", "L"):
                    img = img.convert("RGB")
                buffer = BytesIO()
                img.save(buffer, format="JPEG", quality=85)
                image_b64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
                mime_type = "image/jpeg"
        except Exception as e:
            log_event("llama_cpp_image_convert_error", {"error": str(e)})

    req_model = model_name.split(":", 1)[1].strip() if model_name and ":" in model_name else (model_name or "default")
    url = "http://127.0.0.1:8081/v1/chat/completions"
    body = {
        "model": req_model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": instruction},
                    {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{image_b64}"}}
                ]
            }
        ],
        "temperature": 0.4
    }
    data = json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            return res_data["choices"][0]["message"]["content"].strip()
    except urllib.error.HTTPError as e:
        err_body = e.read().decode('utf-8', errors='ignore')
        raise RuntimeError(f"로컬 LLM 호출 오류: {str(e)}\n상세: {err_body}")
    except Exception as e:
        raise RuntimeError(f"로컬 LLM 호출 오류: {str(e)}")

def call_gemini(image_b64, mime_type, api_key, instruction, model_name, thinking_level=None):
    if model_name.startswith("local-llama-cpp"):
        api_key = resolve_llama_api_key(api_key, model_name)
        return call_llama_cpp(image_b64, mime_type, api_key, instruction, model_name)
        
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

def call_llama_cpp_stream(image_b64, mime_type, api_key, instruction, on_chunk=None, cancel_check=None, model_name="default"):
    if mime_type not in ("image/jpeg", "image/png"):
        try:
            from PIL import Image
            from io import BytesIO
            import base64
            img_data = base64.b64decode(image_b64)
            with Image.open(BytesIO(img_data)) as img:
                if img.mode not in ("RGB", "L"):
                    img = img.convert("RGB")
                buffer = BytesIO()
                img.save(buffer, format="JPEG", quality=85)
                image_b64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
                mime_type = "image/jpeg"
        except Exception as e:
            log_event("llama_cpp_image_convert_error", {"error": str(e)})

    req_model = model_name.split(":", 1)[1].strip() if model_name and ":" in model_name else (model_name or "default")
    url = "http://127.0.0.1:8081/v1/chat/completions"
    body = {
        "model": req_model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": instruction},
                    {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{image_b64}"}}
                ]
            }
        ],
        "temperature": 0.4,
        "stream": True
    }
    data = json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    
    combined = ""
    raw_buffer = ""
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
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
                    payload = line[5:].strip() if line.startswith("data:") else line.strip()
                    
                    if payload == "[DONE]":
                        break
                        
                    try:
                        data_json = json.loads(payload)
                        if "error" in data_json:
                            raise RuntimeError(f"서버 오류: {data_json['error']}")
                            
                        choices = data_json.get("choices", [])
                        if not choices:
                            continue
                            
                        # Handle stream (delta) or full response (message)
                        chunk_content = ""
                        if "delta" in choices[0]:
                            delta = choices[0]["delta"]
                            if "reasoning_content" in delta and delta["reasoning_content"]:
                                chunk_content += delta["reasoning_content"]
                            if "content" in delta and delta["content"]:
                                chunk_content += delta["content"]
                        elif "message" in choices[0]:
                            msg = choices[0]["message"]
                            if "reasoning_content" in msg and msg["reasoning_content"]:
                                chunk_content += msg["reasoning_content"]
                            if "content" in msg and msg["content"]:
                                chunk_content += msg["content"]
                            
                        if chunk_content:
                            combined += chunk_content
                            if on_chunk:
                                on_chunk(chunk_content)
                    except json.JSONDecodeError:
                        pass
            
            final_text = combined.strip()
            if not final_text:
                raise RuntimeError("로컬 LLM에서 빈 응답을 반환했습니다. (이미지 분석 모델이 아니거나, API 형식이 맞지 않을 수 있습니다.)")
            return final_text
    except urllib.error.HTTPError as e:
        err_body = e.read().decode('utf-8', errors='ignore')
        raise RuntimeError(f"로컬 LLM 스트리밍 오류: {str(e)}\n상세 내용: {err_body}")
    except Exception as e:
        raise RuntimeError(f"로컬 LLM 스트리밍 오류: {str(e)}")

def call_gemini_stream(image_b64, mime_type, api_key, instruction, model_name, thinking_level=None, on_chunk=None, cancel_check=None):
    if model_name.startswith("local-llama-cpp"):
        api_key = resolve_llama_api_key(api_key, model_name)
        return call_llama_cpp_stream(image_b64, mime_type, api_key, instruction, on_chunk, cancel_check, model_name)
        
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

def call_llama_cpp_text(user_text, api_key, instruction, model_name="default"):
    req_model = model_name.split(":", 1)[1].strip() if model_name and ":" in model_name else (model_name or "default")
    url = "http://127.0.0.1:8081/v1/chat/completions"
    body = {
        "model": req_model,
        "messages": [
            {"role": "system", "content": instruction},
            {"role": "user", "content": user_text}
        ],
        "temperature": 0.5
    }
    data = json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            return res_data["choices"][0]["message"]["content"].strip()
    except urllib.error.HTTPError as e:
        err_body = e.read().decode('utf-8', errors='ignore')
        raise RuntimeError(f"로컬 LLM 호출 오류 (Text): {str(e)}\n상세: {err_body}")
    except Exception as e:
        raise RuntimeError(f"로컬 LLM 호출 오류 (Text): {str(e)}")

def call_gemini_text(user_text, api_key, instruction, model_name, thinking_level=None):
    if model_name.startswith("local-llama-cpp"):
        api_key = resolve_llama_api_key(api_key, model_name)
        return call_llama_cpp_text(user_text, api_key, instruction, model_name)
        
    url = API_URL_TEMPLATE.format(model=model_name)
    body = {
        "contents": [{
            "parts": [
                {"text": instruction},
                {"text": user_text}
            ]
        }],
        "generationConfig": {"temperature": 0.5, "topP": 0.9, "topK": 32}
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
        raise RuntimeError(f"API 호출 오류 (Text): {str(e)}")

def call_llama_cpp_text_stream(user_text, api_key, instruction, on_chunk=None, cancel_check=None, model_name="default"):
    req_model = model_name.split(":", 1)[1].strip() if model_name and ":" in model_name else (model_name or "default")
    url = "http://127.0.0.1:8081/v1/chat/completions"
    body = {
        "model": req_model,
        "messages": [
            {"role": "system", "content": instruction},
            {"role": "user", "content": user_text}
        ],
        "temperature": 0.5,
        "stream": True
    }
    data = json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    
    combined = ""
    raw_buffer = ""
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
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
                    payload = line[5:].strip() if line.startswith("data:") else line.strip()
                    
                    if payload == "[DONE]":
                        break
                        
                    try:
                        data_json = json.loads(payload)
                        if "error" in data_json:
                            raise RuntimeError(f"서버 오류: {data_json['error']}")
                            
                        choices = data_json.get("choices", [])
                        if not choices:
                            continue
                            
                        # Handle stream (delta) or full response (message)
                        chunk_content = ""
                        if "delta" in choices[0]:
                            delta = choices[0]["delta"]
                            if "reasoning_content" in delta and delta["reasoning_content"]:
                                chunk_content += delta["reasoning_content"]
                            if "content" in delta and delta["content"]:
                                chunk_content += delta["content"]
                        elif "message" in choices[0]:
                            msg = choices[0]["message"]
                            if "reasoning_content" in msg and msg["reasoning_content"]:
                                chunk_content += msg["reasoning_content"]
                            if "content" in msg and msg["content"]:
                                chunk_content += msg["content"]
                            
                        if chunk_content:
                            combined += chunk_content
                            if on_chunk:
                                on_chunk(chunk_content)
                    except json.JSONDecodeError:
                        pass
            
            final_text = combined.strip()
            if not final_text:
                raise RuntimeError("로컬 LLM에서 빈 응답을 반환했습니다.")
            return final_text
    except urllib.error.HTTPError as e:
        err_body = e.read().decode('utf-8', errors='ignore')
        raise RuntimeError(f"로컬 LLM 스트리밍 오류 (Text): {str(e)}\n상세: {err_body}")
    except Exception as e:
        raise RuntimeError(f"로컬 LLM 스트리밍 오류 (Text): {str(e)}")

def call_gemini_text_stream(user_text, api_key, instruction, model_name, thinking_level=None, on_chunk=None, cancel_check=None):
    if model_name.startswith("local-llama-cpp"):
        api_key = resolve_llama_api_key(api_key, model_name)
        return call_llama_cpp_text_stream(user_text, api_key, instruction, on_chunk, cancel_check, model_name)
        
    url = API_STREAM_URL_TEMPLATE.format(model=model_name)
    body = {
        "contents": [{
            "parts": [
                {"text": instruction},
                {"text": user_text}
            ]
        }],
        "generationConfig": {"temperature": 0.5}
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
        raise RuntimeError(f"API 스트리밍 오류 (Text): {str(e)}")
