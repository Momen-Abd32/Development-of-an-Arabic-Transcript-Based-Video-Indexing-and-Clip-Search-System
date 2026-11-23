# Dukkan Media — Product Expansion Roadmap

## Objective

Evolve the existing Arabic media archiving, transcription, indexing, and clip-search application into a dependable media archive platform for Dukkan Media. This roadmap is additive: existing workflows and stored data must remain compatible.

## Preservation requirements

- Preserve current video and standalone-audio upload and playback.
- Preserve FFmpeg audio preparation, Faster-Whisper transcription, transcript review/editing, Arabic normalization, SQLite FTS5 exact search, RapidFuzz fuzzy search, archive-wide search, clip extraction/metadata, CSV exports, batch folder import, SHA-256 duplicate detection, and WER/CER evaluation.
- Do not replace a working component without a compatibility layer and migration tests.
- Keep existing transcript JSON, media catalog JSON, clip metadata JSON, and SQLite data readable. Any schema change must include a safe migration and backup/rollback strategy.
- Add tests for new behavior and regression tests for existing behavior. A feature is not complete until its tests pass.
- Keep optional AI capabilities optional: the core archive must remain usable when embedding, diarization, summarization, or vision models are unavailable.

## Phase 1 — Better Arabic search

1. Multilingual Arabic semantic embeddings with a replaceable embedding-provider interface.
2. Hybrid retrieval combining SQLite FTS5 lexical results and semantic-vector results.
3. Search filters: media type, source, date, tags/collection, speaker, and selected media.
4. Stable ranking, explainable result metadata, and timestamp/source links.
5. Evaluation dataset and metrics for lexical, semantic, and hybrid retrieval; include Arabic MSA samples and spelling/diacritic variants.

## Phase 2 — Understanding and reviewing media

1. Speaker diarization with timestamped speaker labels; gracefully mark speaker identity as unknown when unavailable.
2. Automatic per-media summaries and topic/keyword extraction, stored separately from the verbatim transcript.
3. Interactive transcript synchronized with video/audio playback; selecting a segment seeks to its timestamp.
4. Thumbnail and keyframe extraction for video browsing.
5. Preserve verbatim Arabic transcripts; never silently rewrite dialect into Modern Standard Arabic.

## Phase 3 — Archive management and reliability

1. Collections and tags with persistent metadata and filters.
2. Processing queue with explicit stages, retries, progress, cancellation, and recovery after restart.
3. Dashboard for archive size, media counts, processing states, failures, and model/runtime health.
4. Processing/event history and auditable metadata changes.
5. Role-based access control (administrator, editor, search-only user) before exposing the archive to multiple users.
6. Modular ingestion adapters: local folders first, then watched folders/shared NAS, cloud storage, and supported URLs. Each adapter must validate sources and use the same deduplication and processing pipeline.

## Phase 4 — Advanced discovery and collaboration

1. Visual search across extracted keyframes, with optional image-reference search.
2. Question answering over the archive with citations to media IDs and timestamps; answer only from retrieved evidence and say when evidence is insufficient.
3. Timestamped notes/comments and review collaboration.
4. Advanced media discovery and cross-modal search, introduced behind optional dependencies and feature flags.

## Implementation status (not a completion claim)

The current feature branch contains initial foundations for multilingual semantic embeddings, hybrid lexical/fuzzy/semantic ranking, optional speaker diarization, transcript timestamp playback, and extractive transcript summaries with keyword frequencies. These are partial vertical slices, not completion of their roadmap phases.

- Semantic ranking currently scans stored embeddings in application code; a scalable vector index and retrieval evaluation remain future work.
- Exact, fuzzy, and hybrid transcript search now accept filters for media type, source filename, added-date range, collection, tags, selected media, and speaker (including unassigned speakers). Speaker labels are stored in the segments table with an additive SQLite migration and are rebuilt into the search index after diarization. Search evaluation datasets/metrics and scalable vector retrieval remain outstanding.
- Transcript insights currently select original transcript sentences and rank term frequencies. They are not abstractive AI summaries or a full topic-modeling system.
- Video keyframe extraction now produces sampled JPEGs and previews them in the transcript workspace; timestamp-aware visual search and keyframe indexing are still outstanding.
- Media catalog records now support optional collection names and normalized tags, with backward-compatible JSON loading, archive management UI, and collection/tag filtering of the archive list.
- A separate SQLite processing queue now persists folder-import jobs, attempts, status, per-file progress, failures, immediate queued-job cancellation, cooperative active-job cancellation between files, manual retry, and expired-worker-lease recovery. An independent CLI worker now supports continuous polling and heartbeat leases. Stage-level progress remains future work; running jobs now accept a persisted cancellation request and stop between files at the next progress callback. The Streamlit UI retains a synchronous run-one-job option.
- An append-only SQLite audit history now records media registration/status/metadata changes and processing-job lifecycle transitions, with UTC timestamps, actor labels, entity IDs, and JSON change details. The default actor is `system` until authenticated identities exist; tamper-evident storage and retention policies remain future work.
- The archive dashboard now reports media-type and processing-state counts, stored media size, transcript file count, missing source files, SQLite integrity, and availability of FFmpeg and optional model packages. Runtime metrics are read-only and do not imply that a model is downloaded or loaded.
- Speaker diarization requires optional pyannote dependencies, model access, and validation against representative Arabic recordings.
- The previous CI run passed 230 tests on commit `0d4a27740ac157cc51c993e46f14e0b9bde93b7c`. Audit-history additions include new focused tests; the current branch must pass a fresh CI run before these additions are considered verified.

## Delivery order

Implement in small vertical slices. Start with a codebase audit and baseline regression tests, then deliver Phase 1 before Phase 2, and so on. For each slice:
- inspect current interfaces and persisted formats;
- implement the smallest compatible change;
- add focused unit/integration tests;
- run the full existing test suite;
- update README, configuration examples, and known limitations;
- record actual verification results (never mark untested features complete).

## Non-goals and constraints

- Whisper Arabic transcription does not guarantee conversion to Modern Standard Arabic. Keep source speech verbatim; any optional normalization or editorial rewrite must be a separate, clearly labeled operation.
- Do not claim support for a source type until its adapter is implemented and tested.
- Do not require GPU or paid cloud APIs for the core application.
- Do not introduce a mandatory vector database or external service until scale and operational requirements justify it.
