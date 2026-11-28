import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, copy_metadata

windows = Path(SPECPATH)
root = windows.parent.parent
assets = Path(os.environ["LOCAL_TRANSCRIBER_BUILD_ASSETS"])
ffmpeg = Path(os.environ["LOCAL_TRANSCRIBER_FFMPEG_ROOT"])

datas = [
    (str(root / "config.example.json"), "."),
    (str(root / "third-party-notices.txt"), "."),
    (str(root / "LICENSE"), "."),
    (str(ffmpeg / "bin" / "ffmpeg.exe"), "tools"),
    (str(ffmpeg / "bin" / "ffprobe.exe"), "tools"),
    (str(ffmpeg / "LICENSE"), "licenses/ffmpeg"),
    (str(ffmpeg / "README.txt"), "licenses/ffmpeg"),
    (str(assets / "licenses"), "licenses"),
]
datas += collect_data_files("local_transcriber.export", includes=["fonts/*"])
datas += collect_data_files("whisperx", excludes=["**/*.bin", "**/*.pt", "**/*.safetensors"])
datas += collect_data_files("pyannote.audio")
datas += collect_data_files("lightning_fabric", includes=["**/*.txt", "**/*.json", "**/*.yaml"])
for package in ("whisperx", "faster-whisper", "ctranslate2", "pyannote.audio", "torch", "torchaudio",
                "torchvision", "torchcodec", "transformers", "nltk", "reportlab", "python-docx",
                "PySide6_Essentials", "PySide6_Addons", "shiboken6"):
    datas += copy_metadata(package)

hidden = [
    "whisperx.asr", "whisperx.alignment",
    # The Community-1 configuration and checkpoints refer to Python classes by name.
    "pyannote.audio.pipelines.speaker_diarization",
    "pyannote.audio.models.segmentation.PyanNet",
    "pyannote.audio.models.embedding.wespeaker",
    "transformers.models.wav2vec2.modeling_wav2vec2",
    "transformers.models.wav2vec2.processing_wav2vec2",
    "transformers.models.wav2vec2.feature_extraction_wav2vec2",
    "transformers.models.wav2vec2.tokenization_wav2vec2",
]
binaries = collect_dynamic_libs("ctranslate2") + collect_dynamic_libs("torchaudio")

analysis = Analysis(
    [str(windows / "desktop.py"), str(windows / "console.py")],
    pathex=[str(root / "src")],
    binaries=binaries, datas=datas, hiddenimports=hidden,
    hookspath=[str(windows / "hooks")],
    excludes=["pytest", "IPython", "tkinter", "PyQt5", "PyQt6", "PySide2", "tensorboard",
              "wandb", "tensorflow", "jax", "jaxlib"],
    module_collection_mode={"pyannote.audio": "pyz+py", "whisperx": "pyz+py"},
)
pyz = PYZ(analysis.pure)

def executable(script, name, *, console):
    scripts = [entry for entry in analysis.scripts
               if entry[0] == script or Path(entry[1]).name not in ("desktop.py", "console.py")]
    return EXE(pyz, scripts, name=name, console=console, exclude_binaries=True,
               icon=str(assets / "local-transcriber.ico"), upx=False)


desktop = executable("desktop", "LocalTranscriber", console=False)
console = executable("console", "LocalTranscriberCLI", console=True)
bundle = COLLECT(desktop, console, analysis.binaries, analysis.datas,
                 upx=False, name="LocalTranscriber")
