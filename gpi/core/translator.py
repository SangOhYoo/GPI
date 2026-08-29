import json
import urllib.request
import urllib.parse
import re
import html
import time
import copy

USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36'
DELIMITER = "\n<<<GPI_SEP>>>\n"
SPLIT_REGEX = re.compile(r'\s*<<<\s*GPI_SEP\s*>>>\s*')

# Keys whose string values should NOT be translated (technical identifiers, enum values)
SKIP_TRANSLATE_KEYS = {
    "camera_distance", "category", "visual_priority", "aspect_ratio",
    "orbit_azimuth_deg", "orbit_elevation_deg", "z_index",
    "facing_direction_deg", "name", "character_id", "total_character_count",
    "genre", "composition_layout", "shot_type", "composition_rule",
    "medium", "render_texture"
}

def _call_google_m(text, target_lang):
    """Google Web Translation mobile endpoint - highly resilient and not easily rate-limited."""
    tl = 'zh-CN' if target_lang == 'zh' else target_lang
    url = f"https://translate.google.com/m?sl=auto&tl={tl}&q={urllib.parse.quote(text)}"
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    with urllib.request.urlopen(req, timeout=10) as resp:
        body = resp.read().decode('utf-8')
        match = re.search(r'<div class="result-container">(.*?)</div>', body, re.DOTALL)
        if match:
            return html.unescape(match.group(1)).strip()
    return None

def _call_googleapis_post(text, target_lang, client='dict-chrome-ex'):
    """Google APIs POST endpoint."""
    tl = 'zh-CN' if target_lang == 'zh' else target_lang
    url = f"https://translate.googleapis.com/translate_a/single?client={client}&sl=auto&tl={tl}&dt=t"
    data = urllib.parse.urlencode({'q': text}).encode('utf-8')
    headers = {
        'User-Agent': USER_AGENT,
        'Content-Type': 'application/x-www-form-urlencoded;charset=utf-8',
        'Referer': 'https://translate.google.com/'
    }
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=10) as response:
        res_data = json.loads(response.read().decode('utf-8'))
        translated = "".join([sentence[0] for sentence in res_data[0] if sentence and sentence[0]])
        if translated and translated.strip():
            return translated.strip()
    return None

def _call_clients5_get(text, target_lang):
    """Clients5 Google endpoint."""
    tl = 'zh-CN' if target_lang == 'zh' else target_lang
    url = f"https://clients5.google.com/translate_a/t?client=dict-chrome-ex&sl=auto&tl={tl}&q={urllib.parse.quote(str(text))}"
    headers = {'User-Agent': USER_AGENT}
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=10) as response:
        res_data = json.loads(response.read().decode('utf-8'))
        if isinstance(res_data, list) and len(res_data) > 0:
            if isinstance(res_data[0], list) and len(res_data[0]) > 0:
                return res_data[0][0].strip()
            elif isinstance(res_data[0], str):
                return res_data[0].strip()
    return None

def _call_mymemory(text, target_lang):
    """MyMemory free translation API fallback."""
    langpair = f"en|{target_lang}" if target_lang not in ('zh', 'zh-CN') else "en|zh"
    mm_url = f"https://api.mymemory.translated.net/get?q={urllib.parse.quote(str(text))}&langpair={langpair}"
    req = urllib.request.Request(mm_url, headers={'User-Agent': USER_AGENT})
    with urllib.request.urlopen(req, timeout=10) as response:
        mm_data = json.loads(response.read().decode('utf-8'))
        mm_translated = mm_data.get('responseData', {}).get('translatedText')
        if mm_translated and mm_translated.strip():
            return mm_translated.strip()
    return None

def translate_text(text, target_lang='ko', retries=3):
    """Translate single text with multi-provider fallback."""
    if not text or not str(text).strip():
        return text
    
    methods = [
        lambda t, tl: _call_google_m(t, tl),
        lambda t, tl: _call_googleapis_post(t, tl, 'dict-chrome-ex'),
        lambda t, tl: _call_googleapis_post(t, tl, 'at'),
        lambda t, tl: _call_clients5_get(t, tl),
        lambda t, tl: _call_mymemory(t, tl),
    ]
    
    for attempt in range(retries):
        for method in methods:
            try:
                res = method(text, target_lang)
                if res and res.strip():
                    return res
            except Exception:
                continue
        time.sleep(0.3 * (attempt + 1))
        
    return text

def _translate_batch_chunk(chunk_texts, target_lang):
    """Translate a list of strings in one request using delimiters with multi-method fallback."""
    if not chunk_texts:
        return []
    if len(chunk_texts) == 1:
        return [translate_text(chunk_texts[0], target_lang)]

    combined = DELIMITER.join(chunk_texts)
    
    # 1. Try Google Mobile (highest reliability, no 429 blocking)
    try:
        res = _call_google_m(combined, target_lang)
        if res:
            parts = SPLIT_REGEX.split(res)
            if len(parts) == len(chunk_texts):
                return [p.strip() for p in parts]
    except Exception:
        pass

    # 2. Try Googleapis POST with dict-chrome-ex
    try:
        res = _call_googleapis_post(combined, target_lang, client='dict-chrome-ex')
        if res:
            parts = SPLIT_REGEX.split(res)
            if len(parts) == len(chunk_texts):
                return [p.strip() for p in parts]
    except Exception:
        pass

    # 3. Try Googleapis POST with at
    try:
        res = _call_googleapis_post(combined, target_lang, client='at')
        if res:
            parts = SPLIT_REGEX.split(res)
            if len(parts) == len(chunk_texts):
                return [p.strip() for p in parts]
    except Exception:
        pass

    # Fallback: translate items individually if batch split fails
    return [translate_text(t, target_lang) for t in chunk_texts]

def translate_json_values(json_obj, target_lang='ko'):
    """Recursively traverses a JSON-like dict/list and translates all string values in high-speed batches."""
    paths_and_texts = []
    
    def collect_strings(obj, current_path):
        if isinstance(obj, dict):
            for k, v in obj.items():
                collect_strings(v, current_path + [k])
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                collect_strings(v, current_path + [i])
        elif isinstance(obj, str):
            if obj.strip(): # Only collect non-empty strings
                # Skip translation for technical/enum keys
                if current_path and isinstance(current_path[-1], str) and current_path[-1] in SKIP_TRANSLATE_KEYS:
                    return
                paths_and_texts.append((current_path, obj))
    
    collect_strings(json_obj, [])
    if not paths_and_texts:
        return json_obj
    
    # Split into manageable batches of ~2000 chars or 20 items to prevent oversized requests
    batches = []
    current_batch_paths = []
    current_batch_texts = []
    current_len = 0
    
    for path, text in paths_and_texts:
        t_len = len(text)
        if current_batch_texts and (current_len + t_len > 2000 or len(current_batch_texts) >= 20):
            batches.append((current_batch_paths, current_batch_texts))
            current_batch_paths = [path]
            current_batch_texts = [text]
            current_len = t_len
        else:
            current_batch_paths.append(path)
            current_batch_texts.append(text)
            current_len += t_len
            
    if current_batch_texts:
        batches.append((current_batch_paths, current_batch_texts))
        
    results = {}
    for b_paths, b_texts in batches:
        translated_texts = _translate_batch_chunk(b_texts, target_lang)
        for path, t_val in zip(b_paths, translated_texts):
            results[tuple(path)] = t_val
            
    # Reconstruct the translated json object
    translated_json = copy.deepcopy(json_obj)
    for path, translated_text in results.items():
        target = translated_json
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = translated_text
        
    return translated_json
