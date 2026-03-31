import base64
import re
import json
from datetime import datetime
from PIL import Image
from io import BytesIO
from .api import call_gemini, call_gemini_stream
from .config import (
    MAX_UI_HISTORY, HISTORY_FILE, HISTORY_IMAGES_DIR, BASE_DIR, CANCELLED_MESSAGE,
    MIN_PROMPT_WORDS, MAX_PROMPT_WORDS
)
from .utils import log_event

def build_instruction(min_words=MIN_PROMPT_WORDS, max_words=MAX_PROMPT_WORDS, keyword_text='', high_fidelity=False):
    if high_fidelity:
        base = (
            "You are an expert image reconstruction and forensic visual analyst. "
            "Your goal is to provide a 99.99% accurate technical description of the image so it can be recreated perfectly. "
            "\n\n[Reconstruction Requirements]\n"
            "1. Technical Geometry: Describe the exact spatial placement, scale, and perspective of every object. "
            "Use geometric terms (e.g., vanishing points, horizon line height).\n"
            "2. Material Science: Describe surfaces with micro-precision. Specify textures (e.g., 'porous matte sandstone', 'brushed 304 stainless steel'), reflectivity, transparency, and refractive indices if applicable.\n"
            "3. Light & Physics: Identify every light source (direct, ambient, rim, bounce). Describe shadow density, falloff, color temperature, and caustic effects.\n"
            "4. Color Theory: Describe colors using precise shades, saturations, and relationships (e.g., 'deep ultramarine with subtle cyan highlights in the shadows').\n"
            "5. Micro-details: Capture every minute detail (scratches, dust, skin pores, fabric weave patterns).\n"
            "6. Camera & Optics: Infer the visual equivalent of focal length (e.g., 35mm wide-angle), aperture (depth of field), and sensor noise or film grain if visible.\n"
            f"\nProvide a comprehensive, highly technical natural language English prompt of approximately {min_words} to {max_words} words as a single paragraph."
        )
    else:
        base = (
            f"You are an expert prompt engineer for an advanced AI image generation model. "
            f"Your task is to deeply analyze the provided image and generate a highly detailed, natural language English prompt. "
            f"Describe the visible visual content in approximately {min_words} to {max_words} words as a single paragraph. "
            "\n\n[Instruction]\n"
            "1. Style & Atmosphere: Describe the art style and mood.\n"
            "2. Subjects: Detail their appearance, facial expressions, clothing, and pose.\n"
            "3. Composition & Environment: Describe the setting, spatial depth, camera angle, and lighting.\n"
            "4. Details: Include visible text and minute props.\n"
            "5. Constraints: Write in flowing, natural sentences. Avoid tags or backstory."
        )
    
    keyword_text = (keyword_text or '').strip()
    
    if keyword_text:
        base += (
            f"\n\nUser keyword(s): {keyword_text}. "
            "You must incorporate these keyword(s) by adjusting the most relevant visual elements. "
            "If conflicting, prioritize the keyword(s) seamlessly."
        )
    
    # 출력 포맷 강제 (영어/한국어/중국어 트리플 포맷)
    instr = base + (
        "\n\n"
        "And you MUST provide the output in the following format strictly:\n"
        "[ENGLISH]\n"
        "(English prompt here)\n\n"
        "[KOREAN]\n"
        "(Korean translation here)\n\n"
        "[CHINESE]\n"
        "(Chinese translation here)"
    )
    return instr

def append_history(result, image_source=None):
    try:
        entry = {
            "en": result["en"].replace("\n", " ").strip(),
            "ko": result["ko"].replace("\n", " ").strip(),
            "zh": result.get("zh", "").replace("\n", " ").strip()
        }
        
        # Save image if provided
        if image_source:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            img_filename = f"hist_{timestamp}.png"
            img_path = HISTORY_IMAGES_DIR / img_filename
            
            try:
                if image_source["type"] == "file":
                    # Copy or Save as PNG for consistency
                    with Image.open(image_source["value"]) as img:
                        img.save(img_path, "PNG")
                else:
                    # Memory data (clipboard, drop, url_data)
                    with Image.open(BytesIO(image_source["value"])) as img:
                        img.save(img_path, "PNG")
                
                # Store relative path to BASE_DIR
                entry["image_path"] = str(img_path.relative_to(BASE_DIR))
            except Exception as e:
                log_event("history_image_save_error", {"error": str(e)})

        with HISTORY_FILE.open("a", encoding="utf-8") as file:
            file.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry
    except Exception:
        return None

def load_history():
    if not HISTORY_FILE.exists():
        return []
    try:
        lines = HISTORY_FILE.read_text(encoding="utf-8").splitlines()
        history = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                # Try parsing as JSON (new format)
                history.append(json.loads(line))
            except json.JSONDecodeError:
                # Fallback for old plain-text format
                history.append({"en": line, "ko": ""})
        if MAX_UI_HISTORY is None:
            return history
        return history[-MAX_UI_HISTORY:]
    except Exception:
        return []

def save_all_history(history_list):
    """Rewrites the entire history file with the provided list."""
    try:
        with HISTORY_FILE.open("w", encoding="utf-8") as file:
            for entry in history_list:
                file.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return True
    except Exception as e:
        log_event("history_save_all_error", {"error": str(e)})
        return False

def delete_history_item_files(entry):
    """Deletes the image file associated with a history entry."""
    if not entry or not isinstance(entry, dict):
        return False
        
    image_rel_path = entry.get("image_path")
    if image_rel_path:
        full_path = BASE_DIR / image_rel_path
        try:
            if full_path.exists():
                full_path.unlink()
                log_event("history_image_deleted", {"path": str(image_rel_path)})
                return True
        except Exception as e:
            log_event("history_image_delete_error", {"error": str(e), "path": str(image_rel_path)})
    return False

def extract_word_count(text):
    return len(re.findall(r"\w+", text))

def generate_prompt_logic(image_data, mime_type, api_key, model_name, thinking_level, keyword_text, 
                          min_words=MIN_PROMPT_WORDS, max_words=MAX_PROMPT_WORDS, high_fidelity=False,
                          on_chunk=None, cancel_check=None):
    image_b64 = base64.b64encode(image_data).decode("utf-8")
    
    instruction = build_instruction(min_words=min_words, max_words=max_words, 
                                    keyword_text=keyword_text, high_fidelity=high_fidelity)
    
    if on_chunk:
        full_text = call_gemini_stream(image_b64, mime_type, api_key, instruction, model_name, thinking_level, on_chunk, cancel_check)
    else:
        full_text = call_gemini(image_b64, mime_type, api_key, instruction, model_name, thinking_level)
    
    if cancel_check and cancel_check():
        raise RuntimeError(CANCELLED_MESSAGE)
    
    # Parse combined output
    en_part = ""
    ko_part = ""
    zh_part = ""
    
    if "[ENGLISH]" in full_text and "[KOREAN]" in full_text:
        parts = full_text.split("[KOREAN]")
        en_part = parts[0].replace("[ENGLISH]", "").strip()
        
        remainder = parts[1]
        if "[CHINESE]" in remainder:
            sub_parts = remainder.split("[CHINESE]")
            ko_part = sub_parts[0].strip()
            zh_part = sub_parts[1].strip()
        else:
            ko_part = remainder.strip()
    else:
        # Fallback if AI skips tags
        en_part = full_text
    
    word_count = extract_word_count(en_part)
    log_event("generate_success", {"model": model_name, "word_count": word_count, "multilingual": True})
    return {"en": en_part, "ko": ko_part, "zh": zh_part}, word_count

