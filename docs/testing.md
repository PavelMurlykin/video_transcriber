# Stage 0 verification

Run from the repository root with the prepared `.venv`:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:debugging
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe scripts\diagnose.py
.\.venv\Scripts\python.exe -m local_transcriber --config config.local.json verify-models
.\.venv\Scripts\python.exe -m local_transcriber --config config.local.json transcribe 'sample\Дуэт Да.mp3' --run-dir artifacts\mp3-first
.\.venv\Scripts\python.exe scripts\verify_offline.py --config config.local.json --input 'sample\Дуэт Да.mp4' --run-dir artifacts\mp4-offline
```

Use a fresh `--run-dir` for every attempt; failed results are retained for
diagnosis. Never commit private audio or transcripts. `sample/`, `artifacts/`,
`.tools/`, `.venv/` and local configuration are ignored by Git.

Unit tests cover network denial and token removal, local-path requirements,
hash corruption and LFS pointers, incomplete alignment without fabricated
timestamps or dropped text, speaker changes/overlaps, and FFmpeg conversion of
synthetic media with Cyrillic/spaced paths, a corrupt file and a video without
audio. FFmpeg tests skip when the local tools have not been prepared.

The test command disables pytest's PDB plugin in the noninteractive Windows
console: its transitive `pyreadline3` dependency otherwise emits an ignored
invalid-console-handle exception during shutdown. This changes debugger
integration only; assertions and test execution remain enabled.

Real acceptance additionally requires all three model phases to complete on the
RTX 5070, a readable JSON with two conditional speakers, word times and Russian
text, no runtime token, and a repeat under OS network isolation. A successful
unit test run does not establish these criteria. Do not advance to stage 1 or UI
without a separate user instruction.

`verify_offline.py` returns 3 if it cannot prove OS isolation. In the Codex
restricted Windows execution environment, AppContainer capability inspection
and direct TCP probes can provide that evidence. In an ordinary PowerShell,
use externally established Windows network isolation; do not label a normal
connected run as OS-isolated. This script currently recognizes AppContainer
evidence only. Reboot testing, long meetings, WER/CER/DER evaluation, export and
UI checks belong to later stages and are not reported as passed at stage 0.
