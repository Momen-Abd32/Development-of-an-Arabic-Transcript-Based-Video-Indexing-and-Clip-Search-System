"""Fuse transcript and visual retrieval into one timestamped result list."""
from __future__ import annotations


class CrossModalSearch:
    """Combine lexical transcript ranks and CLIP keyframe ranks with RRF.

    The transcript and visual encoders live in different embedding spaces, so
    raw similarity scores are never compared directly. Reciprocal Rank Fusion
    combines their ranked lists without pretending their scores are calibrated.
    """

    def __init__(self, search_engine, keyframe_index):
        self.search_engine = search_engine
        self.keyframe_index = keyframe_index

    @staticmethod
    def _validate_limit(limit: int) -> None:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError("Limit must be a positive integer.")

    @staticmethod
    def _fuse(rankings: list[tuple[str, list[dict]]], limit: int) -> list[dict]:
        fused: dict[tuple, dict] = {}
        for source, results in rankings:
            for rank, result in enumerate(results, start=1):
                if source == "visual":
                    key = ("keyframe", result["media_id"], result["frame_index"])
                    entry = fused.setdefault(key, {
                        **result,
                        "result_type": "keyframe",
                        "timestamp_seconds": result["timestamp_seconds"],
                    })
                else:
                    key = ("transcript", result["video_id"], result["id"])
                    entry = fused.setdefault(key, {
                        **result,
                        "result_type": "transcript",
                        "media_id": result["video_id"],
                        "timestamp_seconds": float(result["start"]),
                    })
                entry["cross_modal_score"] = entry.get("cross_modal_score", 0.0) + (
                    1.0 / (60 + rank)
                )
                sources = entry.setdefault("matched_by", [])
                if source not in sources:
                    sources.append(source)

        ranked = sorted(
            fused.values(),
            key=lambda item: (
                -item["cross_modal_score"],
                item["media_id"],
                item["timestamp_seconds"],
                item["result_type"],
            ),
        )
        return ranked[:limit]

    def search_text(
        self,
        query: str,
        *,
        limit: int = 20,
        media_ids: list[str] | None = None,
        speaker: str | None = None,
        visual_provider=None,
        include_visual: bool = True,
        fuzzy_threshold: int = 65,
    ) -> list[dict]:
        self._validate_limit(limit)
        if not isinstance(query, str) or not query.strip() or media_ids == []:
            return []

        rankings: list[tuple[str, list[dict]]] = []
        exact = self.search_engine.exact_search(
            query, limit=limit * 3, media_ids=media_ids, speaker=speaker
        )
        fuzzy = self.search_engine.fuzzy_search(
            query,
            threshold=fuzzy_threshold,
            limit=limit * 3,
            media_ids=media_ids,
            speaker=speaker,
        )
        if exact:
            rankings.append(("exact", exact))
        if fuzzy:
            rankings.append(("fuzzy", fuzzy))

        if include_visual and visual_provider is not None:
            visual = self.keyframe_index.search_text(
                query,
                visual_provider,
                limit=limit * 3,
                media_ids=media_ids,
            )
            if visual:
                rankings.append(("visual", visual))

        return self._fuse(rankings, limit)

    def search_image(
        self,
        image_path,
        visual_provider,
        *,
        limit: int = 20,
        media_ids: list[str] | None = None,
    ) -> list[dict]:
        self._validate_limit(limit)
        if media_ids == []:
            return []
        visual = self.keyframe_index.search_image(
            image_path,
            visual_provider,
            limit=limit,
            media_ids=media_ids,
        )
        return self._fuse([("visual", visual)], limit)
