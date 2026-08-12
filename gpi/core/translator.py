import json
import urllib.request
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
import time
import copy

def translate_text(text, target_lang='ko', retries=2):
    """Translate text using Google Translate free API endpoint."""
    if not text or not text.strip():
        return text
    
    if target_lang == 'zh':
        target_lang = 'zh-CN'
        
    url = "https://translate.googleapis.com/translate_a/single"
    params = {
        "client": "gtx",
        "sl": "auto",
        "tl": target_lang,
        "dt": "t",
        "q": text
    }
    query_string = urllib.parse.urlencode(params)
    full_url = f"{url}?{query_string}"
    
    req = urllib.request.Request(full_url, headers={'User-Agent': 'Mozilla/5.0'})
    
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=5) as response:
                res_data = json.loads(response.read().decode('utf-8'))
                # res_data[0] contains the list of translated segments
                translated = "".join([sentence[0] for sentence in res_data[0] if sentence[0]])
                return translated
        except Exception as e:
            if attempt == retries:
                # If it still fails, just return the original text
                print(f"Translation failed: {e}")
                return text
            time.sleep(0.5)
            
    return text

def translate_json_values(json_obj, target_lang='ko', max_workers=10):
    """Recursively traverses a JSON-like dict/list and translates all string values in parallel."""
    # We will collect all string paths and their original texts
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
                paths_and_texts.append((current_path, obj))
    
    collect_strings(json_obj, [])
    
    # Translate in parallel
    results = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_path = {
            executor.submit(translate_text, text, target_lang): path
            for path, text in paths_and_texts
        }
        
        for future in future_to_path:
            path = future_to_path[future]
            try:
                translated_text = future.result()
                results[tuple(path)] = translated_text
            except Exception:
                # On total failure, fallback to something or ignore
                pass
                
    # Reconstruct the translated json object
    translated_json = copy.deepcopy(json_obj)
    
    for path, translated_text in results.items():
        # Navigate and set the translated value
        target = translated_json
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = translated_text
        
    return translated_json
