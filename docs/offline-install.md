# Local preparation (stage 0)

Preparation needs internet; inference does not. Python 3.11–3.13 x64 is supported
by the selected WhisperX 3.8.6 release. This machine uses the existing Python
3.13 interpreter. The matching vendor stack is Torch/torchaudio 2.8.0,
torchvision 0.23.0, CUDA 12.8 wheels. CUDA/cuDNN DLLs are loaded from the Torch
wheel's `torch/lib` within the process, without a machine-wide PATH change.
`nvidia-smi`'s driver CUDA number is not the Torch runtime version.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install torch==2.8.0 torchvision==0.23.0 torchaudio==2.8.0 --index-url https://download.pytorch.org/whl/cu128
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip install --no-deps --no-build-isolation -e .
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\setup_ffmpeg.ps1
```

`constraints-whisperx-3.8.6.txt` preserves the vendor's release constraints,
including Windows/Python 3.13 branches and the source lock's SHA-256.
`requirements.lock` records the 111 installed distributions from the environment
that passed the real GPU and offline tests. It targets Windows x64 / Python 3.13;
Python 3.11–3.12 have not been tested separately. `requirements.in` records the
initial vendor constraints. FFmpeg is fetched from the Windows builds linked
by FFmpeg, unpacked under `.tools`, and its source and archive hash are recorded.
Its bundled license notices stay alongside the binaries. Redistribution of
models or binaries needs a separate license review; none is packaged here.

```powershell
$modelsRoot = Join-Path $env:USERPROFILE '.lmstudio\models\local-transcriber'
.\.venv\Scripts\python.exe scripts\download_models.py --models-root $modelsRoot --only asr
.\.venv\Scripts\python.exe scripts\download_models.py --models-root $modelsRoot --only alignment
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\prepare_community.ps1
.\.venv\Scripts\python.exe scripts\download_models.py --models-root $modelsRoot --only resources
.\.venv\Scripts\python.exe scripts\make_local_config.py --models-root $modelsRoot
```

Community-1 preparation requires accepting its conditions on Hugging Face and
a Read token. `prepare_community.ps1` uses the system `python` (which needs
`huggingface_hub`) and a masked token prompt; it restores its prior environment
on exit. Never put a token in source, `.env`, command-line arguments or chat.
The runtime explicitly removes token environment variables and disables
implicit Hub authentication. Open model downloads explicitly disable tokens.

Use `--reuse-asr ABSOLUTE_SNAPSHOT_PATH` when preparing ASR to materialize an
existing recommended Large V3 snapshot without downloading it again. Existing
shared HF-cache links/blobs are not removed. There is no interaction with
LM Studio: its agreed directory is used solely for local file storage, under
a dedicated `local-transcriber` subdirectory.

Model manifest entries include upstream revisions and content hashes. VAD and
NLTK resource license references are explicitly marked for upstream license
review; they must not be treated as cleared for redistribution. For large files
whose ordinary downloads stall, `download_file.py` supports resumable ranges
and requires an expected SHA-256 obtained from the publisher. Do not bypass
hash verification. After manually completing a model, use
`download_models.py --models-root $modelsRoot --only alignment --inventory-existing`
to record its already downloaded metadata/revision and file hashes, without
network access.

The preparation script pins the three tested model revisions and reuses an
existing manifest's revision. Updating a model requires an intentional revision
change and another smoke test.

Authoritative references: [WhisperX 3.8.6 dependency constraints](https://github.com/m-bain/whisperX/blob/v3.8.6/pyproject.toml),
[PyTorch previous versions](https://pytorch.org/get-started/previous-versions/),
[Community-1 offline loading](https://huggingface.co/pyannote/speaker-diarization-community-1#offline-use),
[FFmpeg downloads](https://ffmpeg.org/download.html).
