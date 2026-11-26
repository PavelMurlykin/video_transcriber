# Architecture

The technical specification is `Local_Transcriber_Codex_Development_Plan.md` v1.0.
Stage 0 proved the offline flow. Stage 1 adds a domain model and media preparation.

The CLI converts a local media file to a separate 16 kHz mono PCM WAV with
FFmpeg, then runs three short-lived Python worker processes **sequentially**:
WhisperX + faster-whisper Large V3 and its local pyannote VAD; Russian Wav2Vec2
forced alignment; Community-1 speaker diarization. A deterministic merge writes
the JSON result. Worker boundaries guarantee native CUDA allocations are
released when a phase exits; each worker also removes model references, runs
garbage collection and empties the Torch cache. This implements the specification's
worker-process boundary without introducing a GUI or local server.

Baseline: CUDA, float16 ASR, batch size 4, beam size 5, Russian, two speakers.
Configuration can select batch size 2, `int8_float16`, or CPU explicitly. The
prototype does not silently change models or select CPU following an error.
English and automatic language detection remain outside stage 0 because only
the Russian aligner has been prepared.

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

WhisperX interpolation is disabled (`interpolate_method="ignore"`). Missing word
times remain null. If upstream alignment drops text, the original segment is
retained and flagged for review. Speaker assignment uses interval intersections;
equal assignments use `unknown`, overlaps remain in the raw turns, and speaker
changes split fully aligned segments. These are prototype reconciliation rules,
not a measured guarantee of diarization quality. Laughter is not explicitly
classified and can require manual review.

Each run uses a new private output directory. FFprobe checks the first audio
stream and supplies a duration estimate for the disk-space check. FFmpeg writes
inside a temporary subdirectory on the same drive. The CLI validates the resulting
PCM WAV and moves it into place. Cancellation stops the media subprocess and
removes partial audio. The standalone `prepare-media` command keeps the WAV it
produces. Full transcription removes the working WAV after saving its transcript.

The version 1 project JSON has typed `Project`, `Speaker`, `Segment` and `Word`
representations. It preserves original ASR and alignment output alongside the
editable segments. A `TranscriptionJob` records phase statuses for diagnostics,
and completed phases appear in the transcript. Technical metrics are separate.
Third-party stdout/stderr is captured and discarded; structured errors contain
exception classes and stack locations, never exception messages or speech.
Sampling reports process-tree RSS and **whole-device** VRAM (including other
applications), not a claimed exact model-only memory peak. Torch allocator peaks
do not include CTranslate2 allocations. Sampling can miss short peaks.

Preparation scripts alone may access the internet. Community-1 terms must be
accepted by the user. The token is supplied using masked input in a separate
PowerShell process and is not stored. HF-cache symlinks are materialized and
hash-checked when reusing ASR; shared cache blobs are preserved to avoid breaking
other applications. Large HTTP downloads may use verified byte ranges when
ordinary pip/HF full-response downloads stall.
