import json
import uuid
from .config import CHARACTERS_FILE

def load_characters():
    """Load character profiles from disk."""
    if not CHARACTERS_FILE.exists():
        return []
    
    try:
        with open(CHARACTERS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("characters", [])
    except Exception:
        return []

def save_characters(characters):
    """Save character profiles to disk."""
    with open(CHARACTERS_FILE, "w", encoding="utf-8") as f:
        json.dump({"characters": characters}, f, ensure_ascii=False, indent=2)

def create_character_template():
    """Return a blank character template."""
    return {
        "id": str(uuid.uuid4()),
        "name": "",
        "demographics": {
            "age": "",
            "gender": "",
            "ethnicity": ""
        },
        "appearance": {
            "hair": "",
            "facial_features": "",
            "body_type": ""
        },
        "default_outfit": "",
        "personality_cues": "",
        "key_relationships": ""
    }

def get_character_prompt_context(active_character_ids=None):
    """Generate a prompt context string for active characters.
    
    If active_character_ids is None, uses all characters (not recommended for large rosters).
    """
    characters = load_characters()
    if not characters:
        return ""
        
    if active_character_ids is not None:
        characters = [c for c in characters if c.get("id") in active_character_ids]
        
    if not characters:
        return ""
        
    context = "[Character Profiles Context]\n"
    context += "The following established characters may appear in the scene (image or text). Use these physical and personality traits to ensure consistency:\n\n"
    
    for c in characters:
        name = c.get("name", "Unknown")
        context += f"Character: {name}\n"
        
        demo = c.get("demographics", {})
        demo_str = ", ".join([v for k, v in demo.items() if v])
        if demo_str:
            context += f"- Demographics: {demo_str}\n"
            
        app = c.get("appearance", {})
        if app.get("hair"): context += f"- Hair: {app['hair']}\n"
        if app.get("facial_features"): context += f"- Facial Features: {app['facial_features']}\n"
        if app.get("body_type"): context += f"- Body Type: {app['body_type']}\n"
        
        if c.get("default_outfit"): context += f"- Default Outfit: {c['default_outfit']}\n"
        if c.get("personality_cues"): context += f"- Personality & Visual Cues: {c['personality_cues']}\n"
        if c.get("key_relationships"): context += f"- Key Relationships: {c['key_relationships']}\n"
        context += "\n"
        
    return context
