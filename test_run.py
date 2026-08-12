from gpi.core.config import get_api_key
from gpi.core.prompt import generate_from_text_logic
import json

def test():
    api_key = get_api_key()
    print("API Key loaded.")
    try:
        result, word_count = generate_from_text_logic(
            "A beautiful anime girl standing in the cyberpunk city under neon lights.", 
            api_key, 
            "gemini-1.5-flash", 
            None, 
            "masterpiece"
        )
        print("=== EN ===")
        print(result["en"])
        print("\n=== KO ===")
        print(result["ko"])
        print("\n=== ZH ===")
        print(result["zh"])
        print("\n=== JSON ===")
        print(result["json"])
        print("\n=== KO JSON ===")
        print(result["json_ko"])
    except Exception as e:
        print(f"Error during generation: {e}")

if __name__ == '__main__':
    test()
