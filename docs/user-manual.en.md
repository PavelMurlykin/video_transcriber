# Local Transcriber — user manual

The current application is a stage-0 CLI prototype for Russian speech. It runs
Large V3 ASR, Russian Wav2Vec2 word alignment and Community-1 diarization
sequentially, then saves JSON. There is no GUI, editor, document export,
project database or installer yet. See `docs/stage-0-report.md` for actual
validation status; implemented code alone does not establish stage acceptance.
The full offline pipeline has been tested on the supplied short MP3 and MP4
recordings with two speakers. Recognition and speaker assignment can still fail.

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

## Processing a recording

From the repository root in PowerShell:

```powershell
.\.venv\Scripts\python.exe scripts\diagnose.py
.\.venv\Scripts\python.exe -m local_transcriber --config config.local.json verify-models
.\.venv\Scripts\python.exe -m local_transcriber --config config.local.json transcribe 'sample\Дуэт Да.mp3' --run-dir artifacts\my-run
.\.venv\Scripts\python.exe scripts\check_run.py artifacts\my-run --expected-speakers 2
```

For MP4, change the input path. FFmpeg creates a separate 16 kHz mono PCM WAV;
the original remains unchanged. Each run requires a new, nonexistent
`--run-dir`. Intermediate data remains after failures. Choose another directory
name to retry. This prototype does not resume interrupted runs.

The result directory contains `transcript.json` with text, words, millisecond
times and conditional speaker IDs; original `asr.json`, `alignment.json`,
`diarization.json`; the prepared `audio.wav`; and technical `metrics.json`.
These files can contain confidential data. Both `sample/` and `artifacts/`
are ignored by Git. Metrics and CLI messages contain no speech or tokens.

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

CLI exit codes: `0` success, `1` processing failure, `2` configuration,
verification or input error, `130` Ctrl+C interruption. Fully managed
cancellation and recovery belong to later stages. `verify_offline.py` returns
`3` without proven isolation, otherwise the CLI code. `check_run.py` returns
`0` for successful structural validation or `1` for validation errors.

VRAM samples cover the entire GPU, including other applications, and periodic
sampling can miss short peaks. Torch allocation metrics exclude CTranslate2.
Read actual timings, RSS and VRAM in each run's `metrics.json`.
