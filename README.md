# Local Transcriber

Windows offline transcription prototype. Stages **0–4** of
[the primary specification](Local_Transcriber_Codex_Development_Plan.md).

Pipeline: local media → 16 kHz mono WAV → Whisper Large V3 / WhisperX → Russian
Wav2Vec2 alignment → pyannote Community-1 → JSON. Models run sequentially in
separate processes. There is no UI or document export yet.

- [Русское руководство](docs/user-manual.ru.md)
- [English user manual](docs/user-manual.en.md)
- [Preparation](docs/offline-install.md), [architecture](docs/architecture.md), [tests](docs/testing.md)
- [Stage 0 results and limitations](docs/stage-0-report.md)
- [Stage 1 media and project schema validation](docs/stage-1-report.md)
- [Stage 2 standalone speech recognition](docs/stage-2-report.md)
- [Stage 3 word alignment](docs/stage-3-report.md)
- [Stage 4 speaker diarization](docs/stage-4-report.md)

Python 3.11–3.13; vendor-compatible CUDA 12.8 / Torch 2.8 stack. The agreed local
model store is `%USERPROFILE%\.lmstudio\models\local-transcriber`; LM Studio
is not used as a service. Prepare dependencies/models online, then run locally:

```powershell
.\.venv\Scripts\python.exe -m local_transcriber --config .tools/ffmpeg-install.json prepare-media 'sample\Дуэт Да.mp4' --run-dir artifacts\audio-example
.\.venv\Scripts\python.exe -m local_transcriber --config config.local.json verify-models
.\.venv\Scripts\python.exe -m local_transcriber --config config.local.json asr 'sample\Дуэт Да.mp3' --language auto --run-dir artifacts\asr-example
.\.venv\Scripts\python.exe -m local_transcriber --config config.local.json transcribe 'sample\Дуэт Да.mp3' --run-dir artifacts\example
```

Use a fresh output directory. The media command produces a 16 kHz mono PCM WAV
using FFmpeg and ffprobe. Standalone ASR supports Russian, English, and automatic
language detection. Both recognition commands remove their working WAV after
saving the transcript. Keep audio, transcripts, local configuration, tools and
models outside Git.
