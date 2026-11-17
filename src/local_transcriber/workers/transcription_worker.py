"""One short-lived process per inference phase. stdout/stderr contain no transcript."""
import argparse
from contextlib import redirect_stdout, redirect_stderr
import gc
import json
import logging
import os
from pathlib import Path
import traceback
import warnings

from local_transcriber.config import load_config
from local_transcriber.core.offline_guard import block_network, offline_environment


def read_audio(path: Path):
    import numpy as np
    import wave
    with wave.open(str(path), "rb") as stream:
        return np.frombuffer(stream.readframes(stream.getnframes()), dtype="<i2").astype(np.float32) / 32768.0


def execute(stage: str, config: dict, directory: Path):
    from local_transcriber.core.gpu_memory import prepare_cuda_dlls, release_cuda
    prepare_cuda_dlls()
    import torch
    if config["device"] == "cuda":
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA_UNAVAILABLE")
        torch.cuda.reset_peak_memory_stats()
    audio = read_audio(directory / "audio.wav")
    if stage == "asr":
        from local_transcriber.core.transcription import transcribe
        result = transcribe(config, audio)
    elif stage == "alignment":
        from local_transcriber.core.alignment import align
        result = align(config, audio, json.loads((directory / "asr.json").read_text(encoding="utf-8")))
    else:
        from local_transcriber.core.diarization import diarize
        result = diarize(config, audio)
    (directory / f"{stage}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    del audio, result
    gc.collect()
    peak = torch.cuda.max_memory_allocated() if torch.cuda.is_available() else 0
    released = release_cuda()
    return {"torch_peak_allocated_bytes": peak, "after_release": released}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["asr", "alignment", "diarization"])
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args()
    env = offline_environment()
    os.environ.clear()
    os.environ.update(env)
    logging.disable(logging.CRITICAL)
    warnings.filterwarnings("ignore")
    status = {"stage": args.stage, "status": "failed"}
    try:
        config = load_config(args.config)
        with block_network(), open(os.devnull, "w") as quiet, redirect_stdout(quiet), redirect_stderr(quiet):
            status.update(execute(args.stage, config, args.run_dir))
        status["status"] = "completed"
    except Exception as error:
        # Store type and stack locations only, never exception values (which may quote speech).
        status.update(error_type=type(error).__name__,
                      stack=[{"file": Path(frame.filename).name, "function": frame.name, "line": frame.lineno}
                             for frame in traceback.extract_tb(error.__traceback__)])
    (args.run_dir / f"{args.stage}-status.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
    return 0 if status["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
