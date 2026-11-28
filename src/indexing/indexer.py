from src.database.database_manager import DatabaseManager
from src.indexing.text_processor import ArabicTextProcessor


class TranscriptIndexer:

    def __init__(self, database_path="data/database/videos.db"):
        self.db = DatabaseManager(database_path)

    def index_segments(self, video_id: str, segments: list[dict]) -> int:
        if not video_id:
            raise ValueError("Video ID cannot be empty.")

        try:
            cursor = self.db.connection.cursor()

            # Transcript edits/re-indexing invalidate vectors for the old
            # segment IDs. Remove them in the same transaction.
            cursor.execute(
                "DELETE FROM segment_embeddings WHERE video_id = ?",
                (video_id,),
            )
            cursor.execute(
                "DELETE FROM segments WHERE video_id = ?",
                (video_id,),
            )

            for segment in segments:
                original_text = segment["text"]

                normalized_text = ArabicTextProcessor.normalize(
                    original_text
                )

                cursor.execute(
                    """
                    INSERT INTO segments (
                        video_id,
                        start,
                        end,
                        original_text,
                        normalized_text,
                        speaker,
                        speaker_age,
                        speaker_gender,
                        speaker_dialect,
                        environment,
                        category,
                        show_name,
                        source_segment_id,
                        segment_length
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        video_id,
                        segment["start"],
                        segment["end"],
                        original_text,
                        normalized_text,
                        segment.get("speaker"),
                        segment.get("speaker_age"),
                        segment.get("speaker_gender"),
                        segment.get("speaker_dialect"),
                        segment.get("environment"),
                        segment.get("category"),
                        segment.get("show_name"),
                        segment.get("source_segment_id"),
                        segment.get("segment_length", segment["end"] - segment["start"]),
                    ),
                )

            self.db.connection.commit()

            return len(segments)

        except Exception:
            self.db.connection.rollback()
            raise

    def close(self):
        self.db.close()