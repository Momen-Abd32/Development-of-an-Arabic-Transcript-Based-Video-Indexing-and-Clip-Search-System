from pathlib import Path
from faster_whisper import WhisperModel


class FasterWhisperEngine:

    def __init__(
        self,
        model_size="tiny",
        device="cpu",
        compute_type="int8",
    ):
        if device not in ("cpu", "cuda"):
            raise ValueError("Device must be 'cpu' or 'cuda'.")

        self.model = WhisperModel(
            model_size,
            device=device,
            compute_type=compute_type,
            cpu_threads=2,
            num_workers=1,
        )

    def transcribe(self, audio_path: str) -> list[dict]:
        audio = Path(audio_path)

        if not audio.exists():
            raise FileNotFoundError(f"Audio not found: {audio}")

        if not audio.is_file() or audio.stat().st_size == 0:
            raise ValueError("Audio file is empty or invalid.")

        segments, info = self.model.transcribe(
            str(audio),
            language="ar",
            task="transcribe",
            beam_size=1,
            best_of=1,
            vad_filter=True,
            condition_on_previous_text=False,
        )

        results = []

        for segment in segments:
            text = segment.text.strip()

            if not text:
                continue

            start = round(segment.start, 2)
            end = round(segment.end, 2)

            if start < 0 or end <= start:
                continue

            results.append({
                "start": start,
                "end": end,
                "text": text,
            })

        return results
