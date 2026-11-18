from src.transcription.faster_whisper_engine import FasterWhisperEngine
from src.transcription.transcript_manager import TranscriptManager

print("Loading Whisper model...")
engine = FasterWhisperEngine(model_size="tiny")

print("Transcribing Arabic audio...")
results = engine.transcribe("data/audio/sample.wav")

print("\nTRANSCRIPTION RESULTS")
print("-" * 50)

for item in results:
    print(f"[{item['start']}s - {item['end']}s] {item['text']}")

output_path = TranscriptManager.save(
    results,
    "data/transcripts/sample.json"
)

print("\nTranscript saved:", output_path)
print("Total segments:", len(results))
