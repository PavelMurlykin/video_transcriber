import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--models-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("config.local.json"))
    args = parser.parse_args()
    root = args.models_root.resolve()
    tools = json.loads(Path(".tools/ffmpeg-install.json").read_text(encoding="utf-8-sig"))
    config = {"models_root": str(root), "asr": str(root / "whisper-large-v3"), "alignment": str(root / "wav2vec2-ru"),
              "diarization": str(root / "pyannote-community-1"), "vad": str(root / "vad/pytorch_model.bin"),
              "nltk_data": str(root / "nltk_data"), "manifest": str(root / "models-manifest.json"),
              "ffmpeg": tools["ffmpeg"], "ffprobe": tools["ffprobe"], "device": "cuda", "compute_type": "float16",
              "batch_size": 4, "num_speakers": 2}
    args.output.write_text(json.dumps(config, indent=2), encoding="utf-8")
    print("Local config created")


if __name__ == "__main__":
    main()
