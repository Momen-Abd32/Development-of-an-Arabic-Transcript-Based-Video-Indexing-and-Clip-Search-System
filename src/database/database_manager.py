import sqlite3
from pathlib import Path


class DatabaseManager:

    def __init__(self, database_path="data/database/videos.db"):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)

        self.connection = sqlite3.connect(
            self.database_path,
            timeout=5,
        )
        self.connection.row_factory = sqlite3.Row

        self.connection.execute("PRAGMA busy_timeout = 5000")

        self.create_tables()

    def create_tables(self):
        cursor = self.connection.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS segments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                video_id TEXT NOT NULL,
                start REAL NOT NULL,
                end REAL NOT NULL,
                original_text TEXT NOT NULL,
                normalized_text TEXT NOT NULL,
                speaker TEXT,
                speaker_age TEXT,
                speaker_gender TEXT,
                speaker_dialect TEXT,
                environment TEXT,
                category TEXT,
                show_name TEXT,
                source_segment_id TEXT,
                segment_length REAL
            )
        """)

        columns = {
            row["name"] for row in cursor.execute("PRAGMA table_info(segments)")
        }
        migrations = {
            "speaker": "TEXT",
            "speaker_age": "TEXT",
            "speaker_gender": "TEXT",
            "speaker_dialect": "TEXT",
            "environment": "TEXT",
            "category": "TEXT",
            "show_name": "TEXT",
            "source_segment_id": "TEXT",
            "segment_length": "REAL",
        }
        for column, column_type in migrations.items():
            if column not in columns:
                cursor.execute(
                    f"ALTER TABLE segments ADD COLUMN {column} {column_type}"
                )

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_segments_video_id
            ON segments(video_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_segments_speaker
            ON segments(speaker)
        """)

        # Optional semantic vectors are stored separately so legacy transcript
        # and FTS5 data remain untouched when semantic search is not installed.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS segment_embeddings (
                segment_id INTEGER NOT NULL,
                video_id TEXT NOT NULL,
                model_name TEXT NOT NULL,
                embedding_json TEXT NOT NULL,
                PRIMARY KEY (segment_id, model_name)
            )
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_segment_embeddings_model
            ON segment_embeddings(model_name, video_id)
        """)

        cursor.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS segments_fts
            USING fts5(
                normalized_text,
                content='segments',
                content_rowid='id'
            )
        """)

        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS validate_segment_insert
            BEFORE INSERT ON segments
            WHEN new.start < 0 OR new.end <= new.start
            BEGIN
                SELECT RAISE(ABORT, 'Invalid segment timestamps');
            END;
        """)

        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS validate_segment_update
            BEFORE UPDATE ON segments
            WHEN new.start < 0 OR new.end <= new.start
            BEGIN
                SELECT RAISE(ABORT, 'Invalid segment timestamps');
            END;
        """)

        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS segments_ai
            AFTER INSERT ON segments BEGIN
                INSERT INTO segments_fts(rowid, normalized_text)
                VALUES (new.id, new.normalized_text);
            END;
        """)

        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS segments_ad
            AFTER DELETE ON segments BEGIN
                INSERT INTO segments_fts(
                    segments_fts, rowid, normalized_text
                )
                VALUES ('delete', old.id, old.normalized_text);
            END;
        """)

        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS segments_au
            AFTER UPDATE ON segments BEGIN
                INSERT INTO segments_fts(
                    segments_fts, rowid, normalized_text
                )
                VALUES ('delete', old.id, old.normalized_text);

                INSERT INTO segments_fts(rowid, normalized_text)
                VALUES (new.id, new.normalized_text);
            END;
        """)

        self.connection.commit()

    def close(self):
        self.connection.close()