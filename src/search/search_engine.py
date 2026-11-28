import heapq

from rapidfuzz import fuzz
from src.database.database_manager import DatabaseManager
from src.indexing.text_processor import ArabicTextProcessor
from src.search.semantic_search import SemanticSearchIndex


UNSPECIFIED_SPEAKER = "__UNSPECIFIED_SPEAKER__"


class SearchEngine:

    def __init__(self, database_path="data/database/videos.db"):
        self.db = DatabaseManager(database_path)

    @staticmethod
    def _validate_limit(limit: int):
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError("Limit must be a positive integer.")

    METADATA_FIELDS = {
        "speaker_age", "speaker_gender", "speaker_dialect",
        "environment", "category", "show_name",
    }

    @classmethod
    def _append_metadata_filters(cls, sql, params, metadata_filters, alias=""):
        if metadata_filters is None:
            return sql
        if not isinstance(metadata_filters, dict):
            raise TypeError("metadata_filters must be a dictionary.")
        prefix = f"{alias}." if alias else ""
        for field, value in metadata_filters.items():
            if field not in cls.METADATA_FIELDS:
                raise ValueError(f"Unsupported metadata filter: {field}")
            if value is None or value == "":
                continue
            if isinstance(value, (list, tuple, set)):
                values = list(value)
                if not values:
                    return sql + " AND 1 = 0"
                sql += f" AND {prefix}{field} IN (" + ",".join("?" for _ in values) + ")"
                params.extend(values)
            else:
                sql += f" AND {prefix}{field} = ?"
                params.append(value)
        return sql

    def list_metadata_values(self, field: str, media_ids: list[str] | None = None) -> list[str]:
        if field not in self.METADATA_FIELDS:
            raise ValueError(f"Unsupported metadata field: {field}")
        if media_ids == []:
            return []
        sql = (
            f"SELECT DISTINCT {field} AS value FROM segments "
            f"WHERE {field} IS NOT NULL AND TRIM({field}) <> ''"
        )
        params = []
        if media_ids is not None:
            sql += " AND video_id IN (" + ",".join("?" for _ in media_ids) + ")"
            params.extend(media_ids)
        sql += " ORDER BY value COLLATE NOCASE"
        return [row["value"] for row in self.db.connection.execute(sql, params).fetchall()]

    def exact_search(
        self,
        query: str,
        limit: int = 20,
        video_id: str | None = None,
        media_ids: list[str] | None = None,
        speaker: str | None = None,
        metadata_filters: dict | None = None,
    ) -> list[dict]:

        self._validate_limit(limit)

        normalized_query = ArabicTextProcessor.normalize(query)

        if not normalized_query or media_ids == []:
            return []

        safe_query = '"' + normalized_query.replace('"', '""') + '"'

        sql = """
            SELECT
                segments.id,
                segments.video_id,
                segments.start,
                segments.end,
                segments.original_text,
                segments.speaker,
                segments.speaker_age,
                segments.speaker_gender,
                segments.speaker_dialect,
                segments.environment,
                segments.category,
                segments.show_name,
                segments.source_segment_id,
                segments.segment_length,
                bm25(segments_fts) AS score
            FROM segments_fts
            JOIN segments ON segments.id = segments_fts.rowid
            WHERE segments_fts MATCH ?
        """

        params = [safe_query]

        if video_id is not None:
            sql += " AND segments.video_id = ?"
            params.append(video_id)
        if media_ids is not None:
            placeholders = ",".join("?" for _ in media_ids)
            sql += f" AND segments.video_id IN ({placeholders})"
            params.extend(media_ids)
        if speaker == UNSPECIFIED_SPEAKER:
            sql += " AND (segments.speaker IS NULL OR TRIM(segments.speaker) = '')"
        elif speaker is not None:
            sql += " AND segments.speaker = ?"
            params.append(speaker)
        sql = self._append_metadata_filters(sql, params, metadata_filters, "segments")

        sql += " ORDER BY score LIMIT ?"
        params.append(limit)

        cursor = self.db.connection.execute(sql, params)

        return [dict(row) for row in cursor.fetchall()]

    def fuzzy_search(
        self,
        query: str,
        threshold: int = 75,
        limit: int = 20,
        video_id: str | None = None,
        media_ids: list[str] | None = None,
        speaker: str | None = None,
        metadata_filters: dict | None = None,
    ) -> list[dict]:

        self._validate_limit(limit)

        if (
            isinstance(threshold, bool)
            or not isinstance(threshold, (int, float))
            or not 0 <= threshold <= 100
        ):
            raise ValueError("Threshold must be between 0 and 100.")

        normalized_query = ArabicTextProcessor.normalize(query)

        if not normalized_query or media_ids == []:
            return []

        sql = """
            SELECT id, video_id, start, end, original_text,
                   normalized_text, speaker, speaker_age, speaker_gender,
                   speaker_dialect, environment, category, show_name,
                   source_segment_id, segment_length
            FROM segments
        """

        conditions = []
        params = []

        if video_id is not None:
            conditions.append("video_id = ?")
            params.append(video_id)
        if media_ids is not None:
            conditions.append("video_id IN (" + ",".join("?" for _ in media_ids) + ")")
            params.extend(media_ids)
        if speaker == UNSPECIFIED_SPEAKER:
            conditions.append("(speaker IS NULL OR TRIM(speaker) = '')")
        elif speaker is not None:
            conditions.append("speaker = ?")
            params.append(speaker)
        for field, value in (metadata_filters or {}).items():
            if field not in self.METADATA_FIELDS:
                raise ValueError(f"Unsupported metadata filter: {field}")
            if value is None or value == "":
                continue
            if isinstance(value, (list, tuple, set)):
                values = list(value)
                if not values:
                    return []
                conditions.append(f"{field} IN (" + ",".join("?" for _ in values) + ")")
                params.extend(values)
            else:
                conditions.append(f"{field} = ?")
                params.append(value)
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)

        cursor = self.db.connection.execute(sql, params)

        # Stream rows from SQLite and retain only the best matches. This keeps
        # memory usage bounded by the requested result limit for large archives.
        best_results = []

        for row in cursor:
            result = dict(row)
            normalized_text = result["normalized_text"]

            if not normalized_text:
                continue

            score = fuzz.partial_ratio(
                normalized_query,
                normalized_text,
            )

            if score >= threshold:
                result["similarity"] = round(score, 2)
                heapq.heappush(
                    best_results,
                    (score, -result["id"], result),
                )

                if len(best_results) > limit:
                    heapq.heappop(best_results)

        best_results.sort(
            key=lambda item: (-item[0], -item[1]),
        )
        return [item[2] for item in best_results]

    def semantic_search(
        self,
        query: str,
        provider,
        limit: int = 20,
        video_id: str | None = None,
        media_ids: list[str] | None = None,
        speaker: str | None = None,
        metadata_filters: dict | None = None,
    ) -> list[dict]:
        """Search the optional semantic index without changing lexical search."""
        semantic_index = SemanticSearchIndex(str(self.db.database_path))
        try:
            return semantic_index.search(
                query,
                provider,
                limit=limit,
                media_id=video_id,
                media_ids=media_ids,
                speaker=speaker,
                metadata_filters=metadata_filters,
            )
        finally:
            semantic_index.close()

    def index_semantic_media(self, video_id: str, provider) -> int:
        """Build or refresh embeddings for one already-indexed media item."""
        semantic_index = SemanticSearchIndex(str(self.db.database_path))
        try:
            return semantic_index.index_media(video_id, provider)
        finally:
            semantic_index.close()

    def hybrid_search(
        self,
        query: str,
        provider,
        limit: int = 20,
        video_id: str | None = None,
        media_ids: list[str] | None = None,
        speaker: str | None = None,
        metadata_filters: dict | None = None,
        fuzzy_threshold: int = 75,
        rrf_k: int = 60,
    ) -> list[dict]:
        """Fuse FTS5, RapidFuzz, and semantic rankings using RRF."""
        self._validate_limit(limit)
        if isinstance(rrf_k, bool) or not isinstance(rrf_k, int) or rrf_k <= 0:
            raise ValueError("RRF k must be a positive integer.")
        if media_ids == [] or (
            video_id is not None
            and media_ids is not None
            and video_id not in media_ids
        ):
            return []

        lexical = self.exact_search(query, limit=limit * 3, video_id=video_id, media_ids=media_ids, speaker=speaker, metadata_filters=metadata_filters)
        fuzzy = self.fuzzy_search(
            query,
            threshold=fuzzy_threshold,
            limit=limit * 3,
            video_id=video_id,
            media_ids=media_ids,
            speaker=speaker,
            metadata_filters=metadata_filters,
        )
        semantic = self.semantic_search(
            query,
            provider,
            limit=limit * 3,
            video_id=video_id,
            media_ids=media_ids,
            speaker=speaker,
            metadata_filters=metadata_filters,
        )
        if not semantic:
            scope = f" for media '{video_id}'" if video_id else " for the archive"
            raise RuntimeError(
                "No semantic embeddings are available"
                + scope
                + ". Build or refresh the semantic index before using hybrid search."
            )

        fused = {}
        for results in (lexical, fuzzy, semantic):
            for rank, result in enumerate(results, start=1):
                key = (result["video_id"], result["id"])
                entry = fused.setdefault(key, dict(result))
                entry["hybrid_score"] = entry.get("hybrid_score", 0.0) + (
                    1.0 / (rrf_k + rank)
                )
                if "speaker" in result:
                    entry["speaker"] = result["speaker"]
                if "semantic_score" in result:
                    entry["semantic_score"] = result["semantic_score"]
                if "similarity" in result:
                    entry["similarity"] = result["similarity"]

        ranked = sorted(
            fused.values(),
            key=lambda result: (
                -result["hybrid_score"],
                result["video_id"],
                result["start"],
                result["id"],
            ),
        )
        return ranked[:limit]

    def list_speakers(self, media_ids: list[str] | None = None) -> list[str]:
        """Return distinct assigned speaker labels within an optional media scope."""
        if media_ids == []:
            return []
        sql = """
            SELECT DISTINCT speaker
            FROM segments
            WHERE speaker IS NOT NULL AND TRIM(speaker) <> ''
        """
        params = []
        if media_ids is not None:
            sql += " AND video_id IN (" + ",".join("?" for _ in media_ids) + ")"
            params.extend(media_ids)
        sql += " ORDER BY speaker COLLATE NOCASE"
        return [
            row["speaker"]
            for row in self.db.connection.execute(sql, params).fetchall()
        ]

    def close(self):
        self.db.close()
