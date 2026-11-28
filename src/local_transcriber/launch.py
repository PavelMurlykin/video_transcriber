"""Resolve entry points for both source runs and the Windows onedir bundle."""

import json
import os
from pathlib import Path
import sys
from tempfile import NamedTemporaryFile

from .domain.paths import resolve_local


def cli_command(*args: str) -> list[str]:
    if getattr(sys, "frozen", False):
        return [str(Path(sys.executable).with_name("LocalTranscriberCLI.exe")), *args]
    return [sys.executable, "-u", "-m", "local_transcriber", *args]


def worker_command(module: str, *args: str) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, f"--internal-{module}", *args]
    return [sys.executable, "-m", f"local_transcriber.workers.{module}", *args]


def default_path(filename: str) -> Path:
    if getattr(sys, "frozen", False):
        return Path(os.environ["LOCALAPPDATA"]) / "LocalTranscriber" / filename
    return Path(filename)


def prepare_default_config(path: Path) -> None:
    if not getattr(sys, "frozen", False) or path.exists():
        return
    path = resolve_local(path)
    resources = Path(sys._MEIPASS)
    data = json.loads((resources / "config.example.json").read_text(encoding="utf-8"))
    for tool in ("ffmpeg", "ffprobe"):
        data[tool] = str(resources / "tools" / f"{tool}.exe")
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            json.dump(data, stream, indent=2)
            stream.close()
            # Windows rename is atomic and fails if another launch already wrote the config.
            temporary.rename(path)
        except FileExistsError:
            pass
        finally:
            temporary.unlink(missing_ok=True)
