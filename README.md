# Local Transcriber

Windows offline transcription prototype. Stages **0–9** of
[the primary specification](Local_Transcriber_Codex_Development_Plan.md).

Pipeline: local media → 16 kHz mono WAV → Whisper Large V3 / WhisperX → Russian
Wav2Vec2 alignment → pyannote Community-1 → JSON. Models run sequentially in
separate processes. The PySide6 desktop client imports recordings, controls
processing, edits saved transcripts and exports them to TXT, DOCX and PDF.

- [Русское руководство](docs/user-manual.ru.md)
- [English user manual](docs/user-manual.en.md)
- [Preparation](docs/offline-install.md), [architecture](docs/architecture.md), [tests](docs/testing.md)
- [Stage 0 results and limitations](docs/stage-0-report.md)
- [Stage 1 media and project schema validation](docs/stage-1-report.md)
- [Stage 2 standalone speech recognition](docs/stage-2-report.md)
- [Stage 3 word alignment](docs/stage-3-report.md)
- [Stage 4 speaker diarization](docs/stage-4-report.md)
- [Stage 5 project storage and recovery](docs/stage-5-report.md)
- [Stage 6 desktop client](docs/stage-6-report.md)
- [Stage 7 transcript export](docs/stage-7-report.md)
- [Stage 8 offline runtime and recovery](docs/stage-8-report.md)
- [Stage 9 performance on Legion Pro 5](docs/stage-9-report.md)

Python 3.11–3.13; vendor-compatible CUDA 12.8 / Torch 2.8 stack. The agreed local
model store is `%USERPROFILE%\.lmstudio\models\local-transcriber`; LM Studio
is not used as a service. Prepare dependencies/models online, then run locally:

```powershell
.\.venv\Scripts\python.exe -m local_transcriber --config .tools/ffmpeg-install.json prepare-media 'sample\Дуэт Да.mp4' --run-dir artifacts\audio-example
.\.venv\Scripts\python.exe -m local_transcriber --config config.local.json check-runtime
.\.venv\Scripts\python.exe -m local_transcriber --config config.local.json asr 'sample\Дуэт Да.mp3' --language auto --run-dir artifacts\asr-example
.\.venv\Scripts\python.exe -m local_transcriber --config config.local.json transcribe 'sample\Дуэт Да.mp3' --run-dir artifacts\example
.\.venv\Scripts\python.exe -m local_transcriber projects list
```

Use a fresh output directory. The media command produces a 16 kHz mono PCM WAV
using FFmpeg and ffprobe. Standalone ASR supports Russian, English, and automatic
language detection. Both recognition commands save project checkpoints to
SQLite and remove their working WAV after completion. Use `projects open`
to reopen a saved transcript without running inference. Keep audio, transcripts,
local configuration, tools and models outside Git.

The desktop client uses the separately pinned Qt components from
`requirements-ui.lock`. Launch with `.\.venv\Scripts\python.exe -m local_transcriber.ui`.
For DOCX and PDF exports, install the optional packages in `requirements-export.lock`.
