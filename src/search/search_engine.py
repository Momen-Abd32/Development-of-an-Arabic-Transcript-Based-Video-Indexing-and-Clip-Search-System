from rapidfuzz import fuzz
from src.database.database_manager import DatabaseManager
from src.indexing.text_processor import ArabicTextProcessor


class SearchEngine:

    def __init__(self, database_path="data/database/videos.db"):
        self.db = DatabaseManager(database_path)

    @staticmethod
    def _validate_limit(limit: int):
        if not isinstance(limit, int) or limit <= 0:
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


    def bm25_search(
        self,
        query: str,
        limit: int = 20,
        video_id: str | None = None,
    ) -> list[dict]:
        """Retrieve segments matching any query term, ranked by FTS5 BM25."""
        self._validate_limit(limit)

        tokens = ArabicTextProcessor.tokenize(query)
        if not tokens:
            return []

        # Quote each token so user input is treated as FTS5 phrase content,
        # not as FTS5 operators or query syntax.
        match_query = " OR ".join(
            '"' + token.replace('"', '""') + '"'
            for token in tokens
        )

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
        params = [match_query]

        if video_id is not None:
            sql += " AND segments.video_id = ?"
            params.append(video_id)

        # FTS5 BM25 scores are lower for more relevant matches.
        sql += " ORDER BY score ASC LIMIT ?"
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

        if not isinstance(threshold, (int, float)) or not 0 <= threshold <= 100:
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

        results = []

        for row in cursor.fetchall():
            row = dict(row)

            if not row["normalized_text"]:
                continue

            score = fuzz.partial_ratio(
                normalized_query,
                row["normalized_text"],
            )

            if score >= threshold:
                row["similarity"] = round(score, 2)
                results.append(row)

        results.sort(
            key=lambda item: item["similarity"],
            reverse=True,
        )

        return results[:limit]


    def hybrid_search(
        self,
        query: str,
        limit: int = 20,
        video_id: str | None = None,
        fuzzy_threshold: int = 75,
        rrf_k: int = 60,
    ) -> list[dict]:
        """Fuse BM25 and fuzzy rankings using Reciprocal Rank Fusion."""
        self._validate_limit(limit)
        if not isinstance(rrf_k, int) or rrf_k <= 0:
            raise ValueError("RRF k must be a positive integer.")

        bm25_results = self.bm25_search(
            query, limit=limit, video_id=video_id
        )
        fuzzy_results = self.fuzzy_search(
            query,
            threshold=fuzzy_threshold,
            limit=limit,
            video_id=video_id,
        )

        fused = {}
        for ranked_results, source in (
            (bm25_results, "bm25"),
            (fuzzy_results, "fuzzy"),
        ):
            for rank, result in enumerate(ranked_results, start=1):
                segment_id = result["id"]
                if segment_id not in fused:
                    fused[segment_id] = dict(result)
                    fused[segment_id]["hybrid_score"] = 0.0
                    fused[segment_id]["matched_by"] = []
                fused[segment_id]["hybrid_score"] += 1.0 / (rrf_k + rank)
                fused[segment_id]["matched_by"].append(source)

        results = sorted(
            fused.values(),
            key=lambda item: item["hybrid_score"],
            reverse=True,
        )
        return results[:limit]

    def close(self):
        self.db.close()