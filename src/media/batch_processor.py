import hashlib
import os
import shutil
import tempfile
from pathlib import Path

from src.indexing.indexer import TranscriptIndexer
from src.media.audio_extractor import AudioExtractor
from src.transcription.faster_whisper_engine import FasterWhisperEngine
from src.transcription.transcript_manager import TranscriptManager


VIDEO_EXTENSIONS = {".mp4", ".mkv", ".mov", ".avi", ".webm"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}
SUPPORTED_EXTENSIONS = VIDEO_EXTENSIONS | AUDIO_EXTENSIONS


class MediaBatchProcessor:
    """Import and transcribe a directory of Arabic audio and video files."""

    def __init__(
        self,
        video_dir: str = "data/videos",
        audio_source_dir: str = "data/audio/originals",
        audio_dir: str = "data/audio",
        transcript_dir: str = "data/transcripts",
        database_path: str = "data/database/videos.db",
        model_size: str = "tiny",
        device: str = "cpu",
        compute_type: str = "int8",
    ):
        self.video_dir = Path(video_dir)
        self.audio_source_dir = Path(audio_source_dir)
        self.audio_dir = Path(audio_dir)
        self.transcript_dir = Path(transcript_dir)
        self.database_path = database_path
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type

    @staticmethod
    def _calculate_sha256(file_path: Path) -> str:
        digest = hashlib.sha256()
        with file_path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _store_source(source: Path, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)

        if source.resolve() == destination.resolve():
            return destination

        if destination.exists():
            return destination

        file_descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}.",
            suffix=".tmp",
            dir=destination.parent,
        )
        os.close(file_descriptor)
        temporary_path = Path(temporary_name)

        try:
            shutil.copy2(source, temporary_path)
            os.replace(temporary_path, destination)
        finally:
            if temporary_path.exists():
                temporary_path.unlink()

        return destination

    def _index(self, media_id: str, segments: list[dict]) -> None:
        indexer = TranscriptIndexer(self.database_path)
        try:
            indexer.index_segments(media_id, segments)
        finally:
            indexer.close()

    def process_directory(
        self,
        input_directory: str,
        recursive: bool = True,
    ) -> list[dict]:
        """Process supported files independently and return one result per file."""
        input_path = Path(input_directory)

        if not input_path.exists():
            raise FileNotFoundError(f"Input directory not found: {input_path}")

        if not input_path.is_dir():
            raise ValueError("Input path must point to a directory.")

        candidates = (
            input_path.rglob("*") if recursive else input_path.iterdir()
        )
        media_files = sorted(
            (
                path for path in candidates
                if path.is_file()
                and path.suffix.lower() in SUPPORTED_EXTENSIONS
            ),
            key=lambda path: str(path).lower(),
        )

        results = []
        engine = None
        seen_hashes = set()

        for source in media_files:
            media_type = (
                "video"
                if source.suffix.lower() in VIDEO_EXTENSIONS
                else "audio"
            )

            media_id = None
            try:
                media_id = self._calculate_sha256(source)

                if media_id in seen_hashes:
                    results.append({
                        "source": str(source),
                        "media_id": media_id,
                        "media_type": media_type,
                        "status": "duplicate_in_batch",
                        "segments": 0,
                    })
                    continue

                if media_type == "video":
                    stored_source = self.video_dir / (
                        f"{media_id}{source.suffix.lower()}"
                    )
                else:
                    stored_source = self.audio_source_dir / (
                        f"{media_id}{source.suffix.lower()}"
                    )

                self._store_source(source, stored_source)

                transcript_path = self.transcript_dir / f"{media_id}.json"

                if transcript_path.exists():
                    segments = TranscriptManager.load(str(transcript_path))
                    self._index(media_id, segments)
                    seen_hashes.add(media_id)
                    results.append({
                        "source": str(source),
                        "media_id": media_id,
                        "media_type": media_type,
                        "status": "already_transcribed",
                        "segments": len(segments),
                    })
                    continue

                audio_path = self.audio_dir / f"{media_id}.wav"
                AudioExtractor.prepare(str(stored_source), str(audio_path))

                if engine is None:
                    engine = FasterWhisperEngine(
                        model_size=self.model_size,
                        device=self.device,
                        compute_type=self.compute_type,
                    )

                segments = engine.transcribe(str(audio_path))
                TranscriptManager.save(segments, str(transcript_path))
                self._index(media_id, segments)
                seen_hashes.add(media_id)

                results.append({
                    "source": str(source),
                    "media_id": media_id,
                    "media_type": media_type,
                    "status": "processed",
                    "segments": len(segments),
                })

            except Exception as error:
                results.append({
                    "source": str(source),
                    "media_id": media_id,
                    "media_type": media_type,
                    "status": "failed",
                    "segments": 0,
                    "error": str(error),
                })

        return results
