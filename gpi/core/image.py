import struct
from io import BytesIO
from pathlib import Path
from PIL import Image
from .config import MAX_IMAGE_DIM, MAX_FILE_MB
from .utils import log_event

def read_istream_all(stream):
    """Safely read all data from an OLE IStream."""
    chunks = []
    try:
        while True:
            # Read in 1MB chunks
            chunk = stream.Read(1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
    except Exception:
        pass
    return b"".join(chunks)

SUPPORTED_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}

def detect_mime_from_bytes(data, filename=""):
    ext = Path(filename).suffix.lower()
    if ext in SUPPORTED_MIME:
        return SUPPORTED_MIME[ext]
    
    try:
        with Image.open(BytesIO(data)) as img:
            fmt = (img.format or "").upper()
            fmt_map = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}
            return fmt_map.get(fmt, "")
    except Exception:
        return ""

def optimize_image_bytes(data, mime_type, source_type):
    try:
        with Image.open(BytesIO(data)) as img:
            orig_width, orig_height = img.size
            orig_bytes = len(data)
            resized = False
            max_edge = max(orig_width, orig_height)
            
            if max_edge > MAX_IMAGE_DIM:
                scale = MAX_IMAGE_DIM / max_edge
                new_size = (max(1, int(orig_width * scale)), max(1, int(orig_height * scale)))
                img = img.resize(new_size, Image.LANCZOS)
                resized = True
            else:
                new_size = (orig_width, orig_height)
            
            format_map = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}
            fmt = format_map.get(mime_type)
            if not fmt:
                return (data, {"optimized": False, "reason": "지원하지 않는 형식", "source": source_type})
            
            if fmt == "JPEG" and img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            
            buffer = BytesIO()
            save_kwargs = {}
            if fmt == "JPEG":
                save_kwargs = {"quality": 85, "optimize": True, "progressive": True}
            elif fmt == "PNG":
                save_kwargs = {"optimize": True}
            elif fmt == "WEBP":
                save_kwargs = {"quality": 85}
            
            img.save(buffer, format=fmt, **save_kwargs)
            new_data = buffer.getvalue()
            new_bytes = len(new_data)
            
            if not resized and new_bytes >= orig_bytes:
                return (data, {
                    "optimized": False,
                    "reason": "용량 감소 없음",
                    "source": source_type,
                    "orig_bytes": orig_bytes,
                    "orig_width": orig_width,
                    "orig_height": orig_height
                })
            
            return (new_data, {
                "optimized": True,
                "source": source_type,
                "orig_bytes": orig_bytes,
                "new_bytes": new_bytes,
                "orig_width": orig_width,
                "orig_height": orig_height,
                "new_width": new_size[0],
                "new_height": new_size[1],
                "resized": resized
            })
    except Exception:
        return (data, {"optimized": False, "reason": "최적화 실패", "source": source_type})

def prepare_image_bytes(data, mime_type, source_type):
    optimized_data, info = optimize_image_bytes(data, mime_type, source_type)
    if info.get("optimized"):
        log_event("image_optimize", info)
    
    size_mb = len(optimized_data) / (1024 * 1024)
    if size_mb > MAX_FILE_MB:
        raise ValueError(f"이미지 용량이 {MAX_FILE_MB}MB를 초과했습니다.")
    return optimized_data, len(optimized_data)

def parse_file_group_descriptor(data, wide=True):
    if not data or len(data) < 4:
        return []
    
    count = struct.unpack_from("<I", data, 0)[0]
    desc_size = 592 if wide else 332
    name_size = 520 if wide else 260
    name_offset = 72
    
    items = []
    for index in range(min(count, 10)):
        offset = 4 + index * desc_size
        if len(data) < offset + desc_size:
            break
        
        name_bytes = data[offset + name_offset : offset + name_offset + name_size]
        if wide:
            name = name_bytes.decode("utf-16le", errors="ignore").split("\x00", 1)[0]
        else:
            name = name_bytes.decode("mbcs", errors="ignore").split("\x00", 1)[0]
        
        size_high = struct.unpack_from("<I", data, offset + 64)[0]
        size_low = struct.unpack_from("<I", data, offset + 68)[0]
        size_bytes = (size_high << 32) | size_low
        items.append({"name": name, "size": size_bytes})
    return items

def parse_dropfiles(data):
    if not data or len(data) < 20:
        return []
    
    p_files = struct.unpack_from("<I", data, 0)[0]
    f_wide = struct.unpack_from("<I", data, 16)[0]
    if p_files >= len(data):
        return []
    
    raw = data[p_files:]
    if f_wide:
        text = raw.decode("utf-16le", errors="ignore")
    else:
        text = raw.decode("mbcs", errors="ignore")
    return [item.strip() for item in text.split("\x00") if item.strip()]
