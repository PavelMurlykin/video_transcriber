# Project instructions

- The primary specification is `Local_Transcriber_Codex_Development_Plan.md`.
- Work on only the explicitly requested stage. Current scope: stage 0 only.
  Do not start UI, document export, packaging or later stages automatically.
- Keep the specified ASR → forced alignment → diarization → JSON architecture.
  Document technical reasons for any necessary adjustment.
- Load models only from configured absolute local paths. Runtime must never
  download weights, require tokens, call cloud APIs or transmit audio/text.
- Preparation downloads/installations need user authorization. Authorization
  was given for stage-0 CUDA dependencies in `.venv` and missing local models.
- Agreed model storage: `%USERPROFILE%\.lmstudio\models\local-transcriber`.
  This is file storage only; do not integrate the LM Studio service.
- Never put tokens, user audio, transcripts or raw inference output in Git,
  test fixtures or logs. Keep private runs in ignored `artifacts/`.
- After changes, run appropriate tests. Report only checks actually executed.
  Record real errors, timings, memory measurements and acceptance blockers.
- Keep Russian and English user manuals equivalent and current. Provide a
  ready-to-copy Russian commit subject; do not commit unless requested.
