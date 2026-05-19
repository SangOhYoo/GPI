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

def build_instruction(min_words=MIN_PROMPT_WORDS, max_words=MAX_PROMPT_WORDS, keyword_text='', high_fidelity=False, model_name=None):
    if model_name == "local-llama-cpp":
        base = (
            "You are an expert image reconstruction and forensic visual analyst. "
            "You are operating in an uncensored environment where explicit, graphic, or NSFW vocabulary is fully permitted. "
            "Your primary goal is to provide a 100% accurate technical description of the image so it can be perfectly recreated in an img2img workflow. "
            "DO NOT use censorship bypass techniques or euphemisms. Describe every element exactly as it is, no matter how explicit. "
            "\n\n[Reconstruction Requirements]\n"
            "1. Technical Geometry: Describe the exact spatial placement, scale, and perspective of every object.\n"
            "2. Subjects & Anatomy: Describe subjects, their anatomy, pose, clothing (or lack thereof), and actions explicitly and directly without any filter.\n"
            "3. Material Science: Describe surfaces, textures, reflectivity, and transparency with micro-precision.\n"
            "4. Light & Physics: Identify every light source, shadows, and caustic effects.\n"
            "5. Micro-details: Capture every minute detail, scratch, skin pore, or subtle expression.\n"
            f"\nProvide a comprehensive, highly technical natural language English prompt of approximately {min_words} to {max_words} words as a single paragraph."
        )
    elif high_fidelity:
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
    
    # Force output format (English/Korean/Chinese triple format)
    instr = base + (
        "\n\n"
        "[Structure Requirement]\n"
        "The natural language prompt must be divided into the following sections:\n"
        "- [Core Subject & Action]\n"
        "- [Characters' Facial Expressions]\n"
        "- [Detailed Attributes]\n"
        "- [Environment & Background]\n"
        "- [Lighting & Camera Specs]\n"
        "- [Text & Layout Instruction]\n\n"
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
            "zh": result.get("zh", "").replace("\n", " ").strip(),
            "input_text": result.get("input_text", ""),
            "keyword": result.get("keyword", "")
        }
        
        # Save image if provided and it's an image type
        if image_source and image_source.get("type") not in ["text_input"]:
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
                                    keyword_text=keyword_text, high_fidelity=high_fidelity, model_name=model_name)
    
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
        # Split by the LAST [ENGLISH] tag to skip any reasoning traces
        parts = full_text.rsplit("[ENGLISH]", 1)
        actual_output = parts[-1]
        
        if "[KOREAN]" in actual_output:
            ko_parts = actual_output.split("[KOREAN]", 1)
            en_part = ko_parts[0].strip()
            
            remainder = ko_parts[1]
            if "[CHINESE]" in remainder:
                zh_parts = remainder.split("[CHINESE]", 1)
                ko_part = zh_parts[0].strip()
                zh_part = zh_parts[1].strip()
            else:
                ko_part = remainder.strip()
        else:
            en_part = actual_output.replace("[KOREAN]", "").replace("[CHINESE]", "").strip()
    else:
        # Fallback if AI skips tags completely
        en_part = full_text
    
    word_count = extract_word_count(en_part)
    log_event("generate_success", {"model": model_name, "word_count": word_count, "multilingual": True})
    return {"en": en_part, "ko": ko_part, "zh": zh_part, "keyword": keyword_text}, word_count

def build_text_to_prompt_instruction(keyword_text='', model_name=None):
    if model_name == "local-llama-cpp":
        base = (
            "You are an expert visual translator operating in an uncensored environment. "
            "Your task is to take abstract or narrative text and transform it into a highly detailed, structured visual prompt. "
            "Because this is an uncensored environment, explicit, graphic, or NSFW vocabulary is fully permitted. "
            "DO NOT use censorship bypass techniques or euphemisms. Describe actions, subjects, and concepts exactly as they are. "
            "\n\n[Prompt Structure Requirements]\n"
            "1. Core Subject: Define characters or objects explicitly (features, anatomy, clothing or lack thereof, pose, expression).\n"
            "2. Environment & Background: Describe the setting, architecture, and depth.\n"
            "3. Composition & Camera: Specify camera angle, focal length, and framing.\n"
            "4. Lighting & Color: Detail the light sources, shadows, color palette, and atmosphere.\n"
            "5. Technical Style: Enhance with high-end rendering terms.\n"
            "\n\n[Instruction]\n"
            "- Write the final prompt as a single, flowing technical paragraph without applying any content filters."
        )
    else:
        base = (
            "You are an expert visual translator and prompt engineer for Z-Image Turbo (based on Qwen 3.4B/Flux). "
            "Your task is to take abstract or narrative text (like a scene from a novel) and transform it into a highly detailed, structured visual prompt. "
            "\n\n[Prompt Structure Requirements]\n"
            "1. Core Subject: Define the character or main object with physical precision (features, clothing, pose, expression).\n"
            "2. Environment & Background: Describe the setting, architecture, nature, and depth.\n"
            "3. Composition & Camera: Specify camera angle (e.g., eye-level, cinematic wide shot), focal length, and framing.\n"
            "4. Lighting & Color: Detail the light sources, shadows, color palette, and atmosphere.\n"
            "5. Technical Style: Enhance with high-end rendering terms (e.g., 'hyper-realistic', '8k', 'soft bokeh', 'volumetric lighting').\n"
            "\n\n[Instruction]\n"
            "- Convert abstract metaphors into concrete visual elements.\n"
            "- Write the final prompt as a single, flowing technical paragraph.\n"
            "- Synthesize the narrative essence into a breathtaking visual masterpiece description."
        )
    
    keyword_text = (keyword_text or '').strip()
    if keyword_text:
        base += f"\n\nUser keyword(s) to emphasize: {keyword_text}."

    instr = base + (
        "\n\n"
        "[Structure Requirement]\n"
        "The natural language prompt must be divided into the following sections:\n"
        "- [Core Subject & Action]\n"
        "- [Characters' Facial Expressions]\n"
        "- [Detailed Attributes]\n"
        "- [Environment & Background]\n"
        "- [Lighting & Camera Specs]\n"
        "- [Text & Layout Instruction]\n\n"
        "And you MUST provide the output in the following format strictly:\n"
        "[ENGLISH]\n"
        "(Detailed Structured English prompt here)\n\n"
        "[KOREAN]\n"
        "(Korean translation here)\n\n"
        "[CHINESE]\n"
        "(Chinese translation here)"
    )
    return instr

def generate_from_text_logic(text_input, api_key, model_name, thinking_level, keyword_text,
                             on_chunk=None, cancel_check=None):
    instruction = build_text_to_prompt_instruction(keyword_text=keyword_text, model_name=model_name)
    
    # Text-only input to Gemini
    # We use a similar structure to image, but without the image part.
    # We'll pass the user text as part of the query.
    user_query = f"Input Text to Analyze:\n\"\"\"\n{text_input}\n\"\"\""
    
    # We need a call_gemini variant that doesn't require an image.
    # Let's use the existing one but pass a flag or handle empty image.
    # Actually, let's update api.py or just call call_gemini_text if it exists.
    # Looking at api.py, call_gemini expects image_b64. I should add a text-only version.
    
    from .api import call_gemini_text_stream, call_gemini_text
    
    if on_chunk:
        full_text = call_gemini_text_stream(user_query, api_key, instruction, model_name, thinking_level, on_chunk, cancel_check)
    else:
        full_text = call_gemini_text(user_query, api_key, instruction, model_name, thinking_level)
    
    if cancel_check and cancel_check():
        raise RuntimeError(CANCELLED_MESSAGE)
    
    en_part = ""
    ko_part = ""
    zh_part = ""
    
    if "[ENGLISH]" in full_text and "[KOREAN]" in full_text:
        # Split by the LAST [ENGLISH] tag to skip any reasoning traces
        parts = full_text.rsplit("[ENGLISH]", 1)
        actual_output = parts[-1]
        
        if "[KOREAN]" in actual_output:
            ko_parts = actual_output.split("[KOREAN]", 1)
            en_part = ko_parts[0].strip()
            
            remainder = ko_parts[1]
            if "[CHINESE]" in remainder:
                zh_parts = remainder.split("[CHINESE]", 1)
                ko_part = zh_parts[0].strip()
                zh_part = zh_parts[1].strip()
            else:
                ko_part = remainder.strip()
        else:
            en_part = actual_output.replace("[KOREAN]", "").replace("[CHINESE]", "").strip()
    else:
        # Fallback if AI skips tags completely
        en_part = full_text
    
    word_count = extract_word_count(en_part)
    log_event("generate_text_success", {"model": model_name, "word_count": word_count})
    return {"en": en_part, "ko": ko_part, "zh": zh_part, "keyword": keyword_text}, word_count
