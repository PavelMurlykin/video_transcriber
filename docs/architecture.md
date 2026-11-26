# Architecture

The technical specification is `Local_Transcriber_Codex_Development_Plan.md` v1.0.
Stage 0 proved the offline flow. Stage 1 adds a domain model and media preparation.
Stage 2 adds a standalone ASR command. Stage 3 validates word alignment.
Stage 4 adds speaker count modes and overlap-aware speaker assignment.
Stage 5 adds transactional local project storage.

The CLI converts a local media file to a separate 16 kHz mono PCM WAV with
FFmpeg, then runs three short-lived Python worker processes **sequentially**:
WhisperX + faster-whisper Large V3 and its local pyannote VAD; Russian Wav2Vec2
forced alignment; Community-1 speaker diarization. A deterministic merge writes
the JSON result. Worker boundaries guarantee native CUDA allocations are
released when a phase exits; each worker also removes model references, runs
garbage collection and empties the Torch cache. This implements the specification's
worker-process boundary without introducing a GUI or local server.

The standalone command uses the same ASR worker as full transcription. It
verifies the recognizer and VAD files, runs audio preparation and ASR, and
supports `ru`, `auto` and `en`. Full transcription uses the existing Russian
alignment model and two speakers by default. The ASR worker loads the
configured local checkpoint and weights, then exits after emitting results.
An optional local glossary is passed to WhisperX as `hotwords`.

The baseline is CUDA, float16, batch size 4 and beam size 5. Memory mode uses
`int8_float16` on CUDA or `int8` on CPU and limits the ASR batch to two. A
recognized GPU allocation failure produces a single suggestion for a manual
retry. The caller chooses the device and whether to retry.

All runtime model paths are absolute local directories/files. A manifest records
sources, revisions, license references, sizes and SHA-256 for every resource,
including the separate VAD and NLTK punkt_tab data. Runtime sets HF/Transformers
offline flags, removes HF token variables, disables pyannote/OpenTelemetry
telemetry, and denies Python socket/DNS calls before importing ML packages.
Workers use a fresh per-run HF/Torch/matplotlib cache under the private run
directory, so inference does not depend on a logged-in user's Hub cache or
attempt to create Torch directories elsewhere in the user profile.
`verify_offline.py` independently checks Windows AppContainer network capabilities
and unguarded network probes; environment flags alone do not count as OS isolation.

The alignment worker only loads the local Russian Wav2Vec2 model, its processor
and the local Russian sentence tokenizer. WhisperX runs with interpolation
disabled (`interpolate_method="ignore"`). The adapter reconciles its output with
the original words in order and accepts time ranges within the ASR segment and
audio. Ranges must remain ordered and positive after rounding to milliseconds.
Words that depend on wildcard characters, annotation text, ambiguous repetitions
and words over digital silence can have two null times. With incomplete alignment,
the original segment text and bounds are kept, along with the valid word times.
Complete alignment can use the sentence boundaries from WhisperX.

The local Community-1 worker runs with an automatic, exact or ranged speaker
count and returns the raw and exclusive timelines. The merge derives the
project's simultaneous-speech regions from the raw timeline. It assigns IDs
by first appearance and intersects each timed word with the speech intervals.
A raw candidate needs over half the word and a lead of at least one tenth of
its duration. The exclusive timeline can settle an uncertain boundary when
its candidate has majority raw coverage and at least one tenth of the word
with that speaker alone in the raw timeline. A conflict between otherwise
supported candidates yields `unknown`. These thresholds are merge rules.

Speaker changes split display segments. If a phrase has missing word times
and two supported speakers, timed groups keep their own labels and untimed
words keep `unknown` and null times. The display interval for an untimed
group uses adjacent timed boundaries where available, with the phrase bounds
as a fallback. The original alignment remains in the project's model results.

Each run uses a new private output directory. FFprobe checks the first audio
stream and supplies a duration estimate for the disk-space check. FFmpeg writes
inside a temporary subdirectory on the same drive. The CLI validates the resulting
PCM WAV and moves it into place. Cancellation stops the media subprocess and
removes partial audio. The standalone `prepare-media` command keeps the WAV it
produces. The `asr` and `transcribe` commands remove their working WAV after
saving the completed result.

The version 1 project JSON has typed `Project`, `Speaker`, `Segment` and `Word`
representations. It preserves original ASR and alignment output alongside the
editable segments. The worker writes raw ASR output atomically. The CLI saves a
project checkpoint after media preparation and replaces it after recognition.
Full transcription replaces that checkpoint after merging alignment and
diarization. A `TranscriptionJob` records phase statuses for diagnostics.
Completed phases appear in the transcript and in separate technical metrics.
Third-party stdout/stderr is captured and discarded; structured errors contain
exception classes and stack locations, never exception messages or speech.
Sampling reports process-tree RSS and **whole-device** VRAM (including other
applications), not a claimed exact model-only memory peak. Torch allocator peaks
do not include CTranslate2 allocations. Sampling can miss short peaks.

SQLite stores the catalog, status, revision and version 1 JSON snapshot in a
single row per project. The transaction keeps the status and snapshot consistent
across a crash without coordinating writes to separate files. The normal
`transcript.json` remains a compatible copy for pipeline runs. SQLite stores
the source path without copying audio. A database application ID and
`user_version` identify the database and its schema.

The pipeline commits a snapshot after media preparation, ASR, alignment,
diarization and merge. Completed ASR-only runs commit after ASR. A failed or
cancelled run retains the last committed stage. A hard termination leaves the
last stage and status `incomplete`. The catalog and original model results are
available without launching models. Edits, undo and redo each commit to the
same database. The undo/redo stacks keep the changed entities in memory for
the current editor session. Revision checks reject stale saves.

Preparation scripts alone may access the internet. Community-1 terms must be
accepted by the user. The token is supplied using masked input in a separate
PowerShell process and is not stored. HF-cache symlinks are materialized and
hash-checked when reusing ASR; shared cache blobs are preserved to avoid breaking
other applications. Large HTTP downloads may use verified byte ranges when
ordinary pip/HF full-response downloads stall.
