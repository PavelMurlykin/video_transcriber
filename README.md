# Local Transcriber

Windows offline transcription prototype. Current scope: **stage 0 only** of
[the primary specification](Local_Transcriber_Codex_Development_Plan.md).

Pipeline: local media → 16 kHz mono WAV → Whisper Large V3 / WhisperX → Russian
Wav2Vec2 alignment → pyannote Community-1 → JSON. Models run sequentially in
separate processes. There is no UI or document export yet.

- [Русское руководство](docs/user-manual.ru.md)
- [English user manual](docs/user-manual.en.md)
- [Preparation](docs/offline-install.md), [architecture](docs/architecture.md), [tests](docs/testing.md)
- [Stage 0 results and limitations](docs/stage-0-report.md)

Python 3.11–3.13; vendor-compatible CUDA 12.8 / Torch 2.8 stack. The agreed local
model store is `%USERPROFILE%\.lmstudio\models\local-transcriber`; LM Studio
is not used as a service. Prepare dependencies/models online, then run locally:

```powershell
.\.venv\Scripts\python.exe -m local_transcriber --config config.local.json verify-models
.\.venv\Scripts\python.exe -m local_transcriber --config config.local.json transcribe 'sample\Дуэт Да.mp3' --run-dir artifacts\example
```

Use a fresh output directory. Audio, transcripts, local configuration, tools and
models must remain outside Git. Stage acceptance requires real GPU and OS-isolated
offline runs; see the report for measured results.
