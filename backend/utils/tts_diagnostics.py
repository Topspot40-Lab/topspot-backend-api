# backend/utils/tts_diagnostics.py

def normalize_for_filename(text: str) -> str:
    return (
        text.lower()
        .replace(" ", "_")
        .replace("&", "and")
        .replace("/", "_")
    )
