import sys
import os

# Add parent directory to path to allow importing app modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.indic_parler_tts_service import get_indic_parler_service

print("--- Initializing Indic Parler Service ---")
try:
    service = get_indic_parler_service()
    print("Service initialized.")
    
    print("\n--- Generating Audio Bytes (Test: 'hello world', output_language='english') ---")
    audio_bytes = service.generate_audio_bytes("hello world", "english")
    print(f"Success! Generated {len(audio_bytes)} bytes of audio.")
    
except Exception as e:
    print("\n💥 ERROR OCCURRED DURING GENERATION:")
    import traceback
    traceback.print_exc()
