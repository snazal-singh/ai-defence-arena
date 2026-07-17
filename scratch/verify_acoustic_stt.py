import os
import sys
import torch
import soundfile as sf
import numpy as np

# Ensure workspace root is in python path
sys.path.insert(0, os.path.abspath("."))

from app.services.stt_service import get_stt_service

def verify_stt_acoustic():
    print("==================================================")
    print("      🎙️ Acoustic LID STT System Verification    ")
    print("==================================================")
    
    # 1. Create a 3-second silent WAV file
    temp_wav_path = "temp_mock_acoustic_query.wav"
    sample_rate = 16000
    duration = 3
    sf.write(temp_wav_path, np.zeros(sample_rate * duration), sample_rate)
    
    try:
        # 2. Get STT Service instance
        print("1. Fetching STT service singleton...")
        stt_service = get_stt_service()
        
        # 3. Test Acoustic Language Detection
        print("2. Running acoustic language detection...")
        detected_language = stt_service.detect_language_acoustically(temp_wav_path)
        print(f"   Acoustic LID Output: '{detected_language}'")
        
        # 4. Transcribe audio
        print("3. Executing automatic hybrid transcription...")
        transcript = stt_service.transcribe(temp_wav_path)
        print("   ASR execution successfully completed!")
        print(f"   Transcribed Output: '{transcript}'")
        
        print("\n🟢 ACOUSTIC LID INTEGRATION TEST COMPLETED SUCCESSFULLY!")
        
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if os.path.exists(temp_wav_path):
            os.remove(temp_wav_path)
            print("4. Cleaned up temporary files.")
    print("==================================================")

if __name__ == "__main__":
    verify_stt_acoustic()
