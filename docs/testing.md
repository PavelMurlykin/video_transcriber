# Verification

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

Stage 1 adds automated tests for a synthetic hour-long MKV, WAV with IMA ADPCM,
low disk space, stopping a running FFmpeg subprocess, cleanup of partial output,
and round-tripping the original version 1 project schema. To run the focused
tests:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:debugging tests/test_media.py tests/test_transcript_schema.py
```

The [stage 1 report](stage-1-report.md) includes the measurements and the
regression run through the complete pipeline.

Stage 2 tests check offline model selection, language forwarding, local glossary
validation, project checkpoints and the one-time suggestion for CUDA memory
errors. The acceptance run uses a Russian recording lasting 15–30 minutes and
checks the JSON under OS network isolation. Use `verify_offline.py --asr-only`
and then `check_run.py --asr-only --expected-language ru`. A run in `auto` mode
reports the detected language. The [stage 2 report](stage-2-report.md) includes
the exact inputs and measurements.

Stage 3 tests cover partial word alignment, unsupported digits and characters,
Cyrillic abbreviations, ambiguous repeats, digital silence, and times invalid
after millisecond rounding. The acceptance runs exercise a supplied recording
through the full pipeline and a synthetic sample through the alignment worker.
See the [stage 3 report](stage-3-report.md) for measurements and results.

Stage 4 tests cover the three count modes, local Community-1 loading, word-level
speaker changes, conflicting timelines, and overlaps with and without word
times. For a recording with predicted overlap, use `check_run.py --expect-overlap`
to check the version 1 JSON, including interval bounds and exclusive tracks.
See the [stage 4 report](stage-4-report.md) for the real offline runs.

Stage 5 tests verify project reopen, legacy JSON import, undo/redo,
save-conflict detection and recovery after an abrupt exit during a SQLite
write. The acceptance run uses separate CLI processes for editing and reopening
with OS network isolation. See the [stage 5 report](stage-5-report.md).

Stage 6 tests exercise Qt import and media inspection, saved settings, editor
controls, and restoring edits after reopening. With the Qt dependencies, run
the standard suite and opt in to the real Windows AppContainer acceptance test.
Use a new ignored artifacts directory for each run. The sample directory must
contain a local MP4 and the matching MP3. The current acceptance test also
requires the export dependencies from stage 7.

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:debugging -m 'not integration'
$env:QT_QPA_PLATFORM = 'windows'
$env:LOCAL_TRANSCRIBER_UI_ACCEPTANCE = 'artifacts\stage6-ui-acceptance'
.\.venv\Scripts\python.exe -m pytest -q -p no:debugging -m integration tests\test_desktop_ui.py
```

The integration test checks network isolation from the Qt process, cancels and
retries a real job, switches tabs during processing, and verifies playing,
seeking and pausing MP4 and MP3. It saves network evidence and metrics in the
artifacts directory. See the [stage 6 report](stage-6-report.md).

Stage 7 tests verify export from the editor, the shared transcript template,
TXT encoding, DOCX text and page fields, and PDF font embedding and pagination.
Install the locked export dependencies before running the standard suite.
The acceptance run compares the three outputs from one edited project under
AppContainer and checks page layout on synthetic transcripts. See the
[stage 7 report](stage-7-report.md).

Stage 8 extends the Windows AppContainer acceptance test to verify startup
checks, mixed Latin and Cyrillic paths, no administrator privileges, worker
failure, and restoring the last saved project. It exports TXT, DOCX and PDF
after the successful retry and checks that the run log includes neither the
source file name nor the synthetic transcript and token markers. See the
[stage 8 report](stage-8-report.md).

Full pipeline acceptance requires all three model phases to complete on the
RTX 5070, a readable JSON with two conditional speakers, word times and Russian
text, and a run under OS network isolation with local resources.

`verify_offline.py` returns 3 if it cannot prove OS isolation. In the Codex
restricted Windows execution environment, AppContainer capability inspection
and direct TCP probes can provide that evidence. In an ordinary PowerShell,
use externally established Windows network isolation; do not label a normal
connected run as OS-isolated. This script currently recognizes AppContainer
evidence only. Reboot testing, long meetings, WER/CER/DER evaluation, export and
UI checks belong to later stages and are not reported as passed at stage 0.
