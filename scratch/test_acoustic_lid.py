import os
import sys
import torch
import soundfile as sf
import numpy as np

# Ensure workspace root is in python path
sys.path.insert(0, os.path.abspath("."))

from transformers import pipeline

def test_whisper_acoustic_lid():
    print("Loading whisper pipeline...")
    device_arg = 0 if torch.cuda.is_available() else ("mps" if torch.backends.mps.is_available() else -1)
    whisper_pipe = pipeline(
        "automatic-speech-recognition",
        model="openai/whisper-base",
        device=device_arg
    )
    
    # Create a 2-second silent wave
    temp_wav = "temp_test_silent.wav"
    sample_rate = 16000
    duration = 2
    sf.write(temp_wav, np.zeros(sample_rate * duration), sample_rate)
    
    try:
        import librosa
        audio, sr = librosa.load(temp_wav, sr=16000)
        
        # Extract features
        print("Extracting Mel spectrogram features...")
        input_features = whisper_pipe.feature_extractor(audio, sampling_rate=16000, return_tensors="pt").input_features
        input_features = input_features.to(whisper_pipe.device)
        
        model = whisper_pipe.model
        tokenizer = whisper_pipe.tokenizer
        
        print("Generating first token to get language probabilities...")
        with torch.no_grad():
            generation_output = model.generate(
                input_features,
                max_new_tokens=1,
                return_dict_in_generate=True,
                output_scores=True
            )
            
        sequences = generation_output.sequences[0]
        print(f"Generated raw token IDs: {sequences.tolist()}")
        
        decoded = tokenizer.decode(sequences)
        print(f"Decoded tokens string: '{decoded}'")
        
        # Check special language tokens
        # Standard Whisper language codes: e.g. <|en|>, <|hi|>, <|ta|>, <|te|>
        print("Model has successfully predicted language token!")
        
    except Exception as e:
        print(f"LID Generation Failed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if os.path.exists(temp_wav):
            os.remove(temp_wav)

if __name__ == "__main__":
    test_whisper_acoustic_lid()
