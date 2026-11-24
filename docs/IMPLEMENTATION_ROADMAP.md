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
7. Verified archive backup and restore with consistent SQLite snapshots, checksums, and safe non-overwriting restoration.
8. Optional local account authentication and role-based permissions before enabling multi-user collaboration.

## Phase 4 — Advanced discovery and collaboration

1. Visual search across extracted keyframes, with optional image-reference search.
2. Question answering over the archive with citations to media IDs and timestamps; answer only from retrieved evidence and say when evidence is insufficient.
3. Timestamped notes/comments and review collaboration.
4. Advanced media discovery beyond the initial cross-modal retrieval slice, introduced behind optional dependencies and feature flags.

## Implementation status (not a completion claim)

The current feature branch contains initial foundations for multilingual semantic embeddings, hybrid lexical/fuzzy/semantic ranking, optional speaker diarization, transcript timestamp playback, and extractive transcript summaries with keyword frequencies. These are partial vertical slices, not completion of their roadmap phases.

- Semantic ranking has two optional paths: the existing exact Python/SQLite heap fallback, which retains only the best `k` candidates in O(k) ranking memory, and a separately installed `sqlite-vec` `vec0` KNN backend for unfiltered or single-media queries. The vector table is derived from the authoritative JSON embeddings and is rebuilt lazily; the extension is never required to open or search the archive. Speaker and multi-media filters continue through the exact fallback. `sqlite-vec` is not an approximate HNSW/ANN index, and no large-archive latency or recall gain is claimed yet; a true ANN backend and representative performance/recall benchmarks remain future work.
- Unified cross-modal search now combines exact/fuzzy transcript ranks and CLIP keyframe ranks with Reciprocal Rank Fusion (RRF); reference-image queries return similar timestamped frames. This is an initial retrieval slice, not archive question answering. A separate evaluation CLI now measures the fused ranking with mixed transcript/frame relevance judgments; real archive labels are still required before reporting retrieval quality.
- Archive Q&A has an evidence-first extractive mode: exact/fuzzy transcript retrieval is fused with optional semantic results, and the top verbatim passage is cited by media ID, segment ID, and timestamps. Users can scope questions to the current media or archive and filter by media type, source name, added-date range, collection, tags, and speaker (including unassigned speakers). An optional loopback-only Ollama adapter can generate multi-passage claims; each claim must cite retrieved media/segment IDs, with fallback to the extractive quote when validation fails. Citation membership is validated, but semantic entailment is not proven. The system abstains when no evidence is retrieved; visual-only Q&A remains future work.
- Timestamped review notes support create/list/update/delete against a media ID and timestamp, source playback, and append-only audit events. When optional authentication is enabled, author/editor values come from the authenticated account; otherwise they are user-entered labels. Cross-instance real-time collaboration is not implemented.
- Exact, fuzzy, and hybrid transcript search accept filters for media type, source filename, added-date range, collection, tags, selected media, and speaker (including unassigned speakers). Speaker labels are stored in the segments table with an additive SQLite migration and are rebuilt into the search index after diarization.
- Search retrieval evaluation includes macro Precision@k, Recall@k, and MRR, a CLI for exact/fuzzy/hybrid modes, a human-judgment template, and a Streamlit labeling workspace that searches exact, fuzzy, and hybrid transcript results or unified cross-modal transcript/keyframe results, can build the optional semantic index, previews source media/keyframes, and saves reviewed transcript or mixed-modality relevance judgments atomically to Git-ignored local datasets. Real Dukkan Media labels are still required before measured quality claims can be made; scalable vector retrieval remains outstanding.
- Transcript insights currently select original transcript sentences and rank term frequencies. They are not abstractive AI summaries or a full topic-modeling system.
- Video keyframe extraction now records FFmpeg presentation timestamps. Keyframes are persisted in a separate SQLite index and can be searched using Arabic text descriptions or reference images through an optional multilingual CLIP provider. The Streamlit search UI can build/refresh the index and display matched frames with source media and timestamps. Matched frames can open a preview of the original video at the recorded timestamp. Visual retrieval evaluation now includes macro Precision@k, Recall@k, and MRR, a CLI supporting Arabic text and reference-image queries, and a human-judgment template. The template still needs real archive relevance labels before measured quality claims can be made; scalable vector retrieval remains outstanding.
- Media catalog records now support optional collection names and normalized tags, with backward-compatible JSON loading, archive management UI, and collection/tag filtering of the archive list.
- A separate SQLite processing queue now persists folder-import jobs, attempts, status, overall progress, current processing stage, current file, within-stage progress, failures, immediate queued-job cancellation, cooperative active-job cancellation between files, manual retry, and expired-worker-lease recovery. The new stage fields use additive SQLite migrations for existing queue databases. The batch processor reports stages such as source verification/copying, audio extraction, transcription, transcript saving/indexing, and catalog updates. Both the independent heartbeat-based CLI worker and the Streamlit run-one-job UI persist and display stage details. Stage progress currently reports operation start/completion boundaries; it does not claim live progress inside a long-running Whisper inference call.
- A polling-based watched-folder adapter now monitors one or more local or mounted folders, waits for stable file size/mtime across consecutive scans, persists per-file signatures, and enqueues explicit file-import jobs. The normal worker dispatches those files through the existing SHA-256, transcription, and indexing pipeline.
- A direct-media URL adapter now downloads HTTPS files only from exact operator-allowlisted hosts, validates redirects and public DNS answers, disables environment proxies, enforces content-type/size/time limits, and queues the downloaded file through the same processing pipeline. Authenticated streaming pages, playlists, and direct cloud-provider APIs remain future adapters.
- Archive backup tooling now snapshots the `data/` and `exports/` trees, uses SQLite's online backup API for `.db` files, writes per-file SHA-256 manifests, verifies archive membership and checksums, and restores only into a new target directory. Source code, secrets, and model caches are intentionally excluded.
- Optional account authentication now uses PBKDF2-HMAC-SHA256 password hashes with per-user salts, an additive user/attempt schema in the processing database, temporary lockout after repeated failures, and audited user/role/password changes. The UI gates upload/edit/queue/notes/admin sections by administrator, editor, and search-only roles; authentication remains opt-in and is not a replacement for SSO/MFA or a hardened public-facing identity service.
- An append-only SQLite audit history now records media registration/status/metadata changes and processing-job lifecycle transitions, with UTC timestamps, actor labels, entity IDs, and JSON change details. The default actor is `system` until authenticated identities exist; tamper-evident storage and retention policies remain future work.
- The archive dashboard now reports media-type and processing-state counts, stored media size, transcript file count, missing source files, SQLite integrity, and availability of FFmpeg and optional model packages. Runtime metrics are read-only and do not imply that a model is downloaded or loaded.
- Speaker diarization requires optional pyannote dependencies, model access, and validation against representative Arabic recordings.
- CI compiles the application and source modules and runs the full pytest suite on pushes and pull requests; consult the latest branch workflow run for the current verification result.

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
