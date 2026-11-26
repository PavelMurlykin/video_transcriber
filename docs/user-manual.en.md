# Local Transcriber — user manual

The CLI prepares audio from media files and transcribes Russian speech. Full
processing uses Large V3, Russian Wav2Vec2 and Community-1, then saves version 1
JSON with timestamps and speakers. See the [stage 0 report](stage-0-report.md)
and the [stage 1 report](stage-1-report.md) for validation results.

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

Default profile: Russian, CUDA, `float16`, `batch_size=4`, `beam_size=5`,
`num_speakers=2`. For automatic speaker counting, set `num_speakers: null`.
If memory is insufficient, explicitly select `batch_size: 2`, then
`compute_type: "int8_float16"`, or `device: "cpu"` with
`compute_type: "float32"`. The model remains Large V3. There is no automatic
OOM retry or silent CPU fallback; any profile change needs another test.
CPU inference can be much slower.
Alternative CPU/int8 profiles were not separately tested in stage 0.

Incomplete alignment, speaker boundaries and overlapping speech have
`requires_review` and review reasons. Missing word times are `null`; an
uncertain speaker is `unknown`. Laughter is not classified as a separate event
and can affect recognition or speaker assignment. Real names are not inferred.
WER/CER/DER are not measured without a manually annotated reference.

## Testing without internet

Runtime always enables offline flags and blocks Python socket/DNS APIs.
To verify blocking at OS level:

```powershell
.\.venv\Scripts\python.exe scripts\verify_offline.py --config config.local.json --input 'sample\Дуэт Да.mp4' --run-dir artifacts\my-offline-run
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
