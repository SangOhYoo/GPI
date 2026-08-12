import tkinter as tk
from gpi.ui.window import PromptApp
import json
import time

def test_remix():
    print("Testing PromptApp Remix logic...")
    root = tk.Tk()
    app = PromptApp(root)
    
    # 1. Test refresh_remix_options
    print("\n--- Testing refresh_remix_options ---")
    app.refresh_remix_options()
    
    has_options = False
    for attr in app.remix_attributes:
        vals = app.remix_combos[attr]['values']
        print(f"{attr}: {len(vals)} options found")
        if len(vals) > 1:
            has_options = True
            # select the first non-empty option
            app.remix_combos[attr].set(vals[1])
            
    if not has_options:
        print("WARN: No remix options were extracted from history.txt!")
    else:
        print("Success: Remix options were extracted from history.txt")

    # 2. Test generation parameters
    print("\n--- Testing on_generate_remix state setup ---")
    app.model_var.set("gemini-1.5-flash")

    assembled_parts = []
    for attr in app.remix_attributes:
        val = app.remix_combos[attr].get().strip()
        if val:
            assembled_parts.append(f"{attr.replace('_', '/')}: {val}")
    
    assembled_text = "\n".join(assembled_parts)
    print("Assembled text:")
    print(assembled_text)
    
        # Try calling the core logic directly (using local llama model to avoid API Key 403)
    from gpi.core.prompt import generate_remix_logic
    from gpi.core.config import get_api_key
    
    print("\n--- Testing generate_remix_logic (dry run) ---")
    api_key = get_api_key("llama.cpp") # Try local key
    
    def on_chunk(c):
        print(c, end="", flush=True)
        
    def on_pass2_chunk(c):
        print(c, end="", flush=True)

    try:
        # Just passing "local-llama-cpp" as model so it routes to local api
        # If it fails, that's fine, we just want to ensure it doesn't crash on invocation.
        print("Invoking generate_remix_logic with local-llama-cpp:Qwen3-VL-8B-Text-Only ...")
        # For testing we can just pass empty active_character_ids
        generate_remix_logic(
            assembled_text=assembled_text,
            api_key=api_key,
            model_name="local-llama-cpp:Qwen3-VL-8B-Text-Only",
            thinking_level="none",
            keyword_text="",
            on_chunk=None,
            on_pass2_chunk=None,
            active_character_ids=[]
        )
        print("\n[OK] generate_remix_logic finished without crashing.")
    except Exception as e:
        print(f"\n[Error] {e}")
        
    print("\nTest completed.")

if __name__ == '__main__':
    test_remix()
