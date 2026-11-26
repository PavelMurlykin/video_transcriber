# Local Transcriber — user manual

The CLI prepares audio from media files and recognizes Russian and English
speech. Full Russian transcription uses Large V3, Russian Wav2Vec2 and
Community-1, then saves version 1 JSON with timestamps and speakers. See the
[stage 0 report](stage-0-report.md), [stage 1 report](stage-1-report.md),
[stage 2 report](stage-2-report.md), and [stage 3 report](stage-3-report.md)
for validation results.

## Preparation

Windows x64, Python 3.11–3.13, a compatible NVIDIA driver and sufficient free
space for CUDA libraries and models are required. This machine uses Python
3.13.12 and an RTX 5070 Laptop with 8 GB VRAM. Install libraries, FFmpeg and
models online following `docs/offline-install.md`. After the GPU smoke test,
use the tested `requirements.lock`. User recordings are not transmitted during
preparation or inference.
The lock file has been tested on Windows/Python 3.13; separate runs on
3.11–3.12 have not been performed.

Models are stored under `%USERPROFILE%\.lmstudio\models\local-transcriber`:
`whisper-large-v3`, `wav2vec2-ru`, `pyannote-community-1`, `vad`, `nltk_data`.
LM Studio does not need to run. Set paths in the Git-ignored
`config.local.json`; see `config.example.json`. All model and FFmpeg/ffprobe
paths must be absolute local paths.

To download Community-1 initially, accept its Hugging Face conditions and run
`scripts\prepare_community.ps1`: its Read token prompt is masked, the token is
used temporarily and the script does not save it. Inference needs no token.
Never send tokens in chat or place them in `.env`.

## Preparing audio only

```powershell
.\.venv\Scripts\python.exe -m local_transcriber --config .tools/ffmpeg-install.json prepare-media 'sample\Дуэт Да.mp4' --run-dir artifacts\my-audio
```

This command needs FFmpeg/ffprobe and a configuration file with their absolute
paths. It extracts the first audio stream to `audio.wav` in a new directory and
reports duration, source codec and channel count. The output is 16-bit PCM,
16 kHz, mono. The disk check estimates the output size from the duration, with
a 16 MiB reserve. Use a new directory on a local drive for each run.

Ctrl+C during media preparation stops FFmpeg/ffprobe and removes the partial
WAV. If a command fails, check `error_code` and `hint` in the terminal.
`NO_AUDIO_STREAM` means the file has no audio track, `INVALID_MEDIA` means the
container could not be read, and `INSUFFICIENT_DISK_SPACE` means the drive has
too little space. For a WAV above the format's approximately 4 GiB limit, split
the recording into parts.

## Transcribing a recording

For speech recognition without alignment or diarization:

```powershell
.\.venv\Scripts\python.exe -m local_transcriber --config config.local.json asr 'sample\Дуэт Да.mp3' --language auto --run-dir artifacts\my-asr
.\.venv\Scripts\python.exe scripts\check_run.py artifacts\my-asr --asr-only --expected-language ru
```

`asr` supports `--language ru` (the default), `en`, and `auto`. In `auto` mode
WhisperX detects the language from the beginning of the recording. The
configuration needs paths to Large V3, VAD, the manifest, FFmpeg, and ffprobe.
`transcript.json` includes the language, text, and segment times in
milliseconds. In this mode speaker IDs are `unknown` and the word list is empty.
`asr.json` contains the original recognition result.

The CLI saves a project checkpoint after media preparation and updates the
JSON with text after ASR. If a later phase of full processing fails, the ASR
result remains available.

For either command, pass `--terms-file artifacts\terms.txt` with one name,
term, or abbreviation per line in a UTF-8 file of up to 4096 bytes. Terms act
as hints. The model may omit or misspell them. Keep the file in a local
directory ignored by Git.

Use `transcribe` for speech recognition, alignment and diarization. This
command uses Russian.

From the repository root in PowerShell:

```powershell
.\.venv\Scripts\python.exe scripts\diagnose.py
.\.venv\Scripts\python.exe -m local_transcriber --config config.local.json verify-models
.\.venv\Scripts\python.exe -m local_transcriber --config config.local.json transcribe 'sample\Дуэт Да.mp3' --run-dir artifacts\my-run
.\.venv\Scripts\python.exe scripts\check_run.py artifacts\my-run --expected-speakers 2
```

For MP4, change the input path. Use a new `--run-dir` for each run. The working
WAV is removed after successful transcript saving. After a model failure, a
fully extracted WAV and other intermediate data remain for diagnosis. A retry
processes the recording from the start.

The result directory contains `transcript.json` with text, words, millisecond
times and conditional speaker IDs; original `asr.json`, `alignment.json`,
`diarization.json`; and technical `metrics.json` with phase statuses.
The private directories `sample/` and `artifacts/` are ignored by Git.
Metrics and CLI messages contain technical information only.

The ASR defaults are CUDA, `float16`, `batch_size=4`, and `beam_size=5`. Set
`batch_size` and `compute_type` in the configuration. The `transcribe` command
defaults to two speakers. For automatic speaker counting, set
`num_speakers: null`. On an ASR GPU memory error, the CLI reports
`ASR_GPU_OUT_OF_MEMORY` and suggests a single manual retry with
`--profile memory` and a new `--run-dir`. Memory mode limits the batch to two
items and selects `int8_float16` on CUDA or `int8` on CPU. It retains Large V3.
Stage 2 tested the memory profile on CUDA.

Russian Wav2Vec2 places word timestamps within the phrase. Tokens with digits
or letters outside the model vocabulary, text annotations such as
`[неразборчиво]`, and words without a valid time range have `null` in
`start_ms` and `end_ms`. These words have
`alignment_missing` set. The segment retains its original text and interval,
along with word times that could be aligned. The `requires_review` flag and
`alignment_incomplete` reason identify incomplete alignment.

Speaker boundaries and overlapping speech can also require review. An uncertain
speaker is marked `unknown`. Laughter can affect text and speaker assignment.
Measuring WER/CER/DER requires a manually annotated reference.

## Testing without internet

Runtime always enables offline flags and blocks Python socket/DNS APIs.
To verify blocking at OS level:

```powershell
.\.venv\Scripts\python.exe scripts\verify_offline.py --config config.local.json --input 'sample\Дуэт Да.mp4' --run-dir artifacts\my-offline-run
.\.venv\Scripts\python.exe scripts\verify_offline.py --config config.local.json --asr-only --language auto --input 'sample\Дуэт Да.mp4' --run-dir artifacts\my-offline-asr
```

The script checks a Windows AppContainer without network capabilities and
direct connections before enabling the Python guard. In the restricted Codex
environment this allows a real full-pipeline test without networking. In an
ordinary PowerShell it returns 3 if that isolation cannot be proved. This
version recognizes AppContainer only; disabled adapters or an external firewall
need separate verification. Offline flags alone do not establish successful
OS-level isolation.

`0` means success, `1` a processing failure, `2` a configuration, verification
or input error, and `130` a Ctrl+C interruption. `verify_offline.py` returns
`3` without proven isolation, otherwise the CLI code. `check_run.py` returns
`0` for successful structural validation or `1` for validation errors.

VRAM samples cover the entire GPU, including other applications, and periodic
sampling can miss short peaks. Torch allocation metrics exclude CTranslate2.
Read actual timings, RSS and VRAM in each run's `metrics.json`.
