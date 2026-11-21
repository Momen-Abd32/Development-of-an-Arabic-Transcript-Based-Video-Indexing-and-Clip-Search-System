import heapq

from rapidfuzz import fuzz
from src.database.database_manager import DatabaseManager
from src.indexing.text_processor import ArabicTextProcessor


class SearchEngine:

    def __init__(self, database_path="data/database/videos.db"):
        self.db = DatabaseManager(database_path)

    @staticmethod
    def _validate_limit(limit: int):
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError("Limit must be a positive integer.")

    def exact_search(
        self,
        query: str,
        limit: int = 20,
        video_id: str | None = None,
    ) -> list[dict]:

        self._validate_limit(limit)

        normalized_query = ArabicTextProcessor.normalize(query)

        if not normalized_query:
            return []

        safe_query = '"' + normalized_query.replace('"', '""') + '"'

        sql = """
            SELECT
                segments.id,
                segments.video_id,
                segments.start,
                segments.end,
                segments.original_text,
                bm25(segments_fts) AS score
            FROM segments_fts
            JOIN segments ON segments.id = segments_fts.rowid
            WHERE segments_fts MATCH ?
        """

        params = [safe_query]

        if video_id is not None:
            sql += " AND segments.video_id = ?"
            params.append(video_id)

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
    ) -> list[dict]:

        self._validate_limit(limit)

        if (
            isinstance(threshold, bool)
            or not isinstance(threshold, (int, float))
            or not 0 <= threshold <= 100
        ):
            raise ValueError("Threshold must be between 0 and 100.")

        normalized_query = ArabicTextProcessor.normalize(query)

        if not normalized_query:
            return []

        sql = """
            SELECT id, video_id, start, end, original_text,
                   normalized_text
            FROM segments
        """

        params = []

        if video_id is not None:
            sql += " WHERE video_id = ?"
            params.append(video_id)

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
                    (score, result["id"], result),
                )

                if len(best_results) > limit:
                    heapq.heappop(best_results)

        best_results.sort(
            key=lambda item: (item[0], item[1]),
            reverse=True,
        )
        return [item[2] for item in best_results]

    def close(self):
        self.db.close()
