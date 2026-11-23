import heapq

from rapidfuzz import fuzz
from src.database.database_manager import DatabaseManager
from src.indexing.text_processor import ArabicTextProcessor
from src.search.semantic_search import SemanticSearchIndex


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
                    (score, -result["id"], result),
                )

                if len(best_results) > limit:
                    heapq.heappop(best_results)

        best_results.sort(
            key=lambda item: (-item[0], -item[1]),
            reverse=True,
        )
        return [item[2] for item in best_results]

    def semantic_search(
        self,
        query: str,
        provider,
        limit: int = 20,
        video_id: str | None = None,
    ) -> list[dict]:
        """Search the optional semantic index without changing lexical search."""
        semantic_index = SemanticSearchIndex(str(self.db.database_path))
        try:
            return semantic_index.search(
                query,
                provider,
                limit=limit,
                media_id=video_id,
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
        fuzzy_threshold: int = 75,
        rrf_k: int = 60,
    ) -> list[dict]:
        """Fuse FTS5, RapidFuzz, and semantic rankings using RRF."""
        self._validate_limit(limit)
        if isinstance(rrf_k, bool) or not isinstance(rrf_k, int) or rrf_k <= 0:
            raise ValueError("RRF k must be a positive integer.")

        lexical = self.exact_search(query, limit=limit * 3, video_id=video_id)
        fuzzy = self.fuzzy_search(
            query,
            threshold=fuzzy_threshold,
            limit=limit * 3,
            video_id=video_id,
        )
        semantic = self.semantic_search(
            query,
            provider,
            limit=limit * 3,
            video_id=video_id,
        )

        fused = {}
        for results in (lexical, fuzzy, semantic):
            for rank, result in enumerate(results, start=1):
                key = (result["video_id"], result["id"])
                entry = fused.setdefault(key, dict(result))
                entry["hybrid_score"] = entry.get("hybrid_score", 0.0) + (
                    1.0 / (rrf_k + rank)
                )
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

    def close(self):
        self.db.close()
