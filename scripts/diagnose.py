import importlib.metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from local_transcriber.core.offline_guard import offline_environment, block_network
from local_transcriber.core.gpu_memory import prepare_cuda_dlls


def main():
    os.environ.update(offline_environment(Path("artifacts/diagnostic-cache")))
    report = {"python": platform.python_version(), "executable": sys.executable, "platform": platform.platform(), "packages": {}}
    for name in ("torch", "torchaudio", "torchvision", "whisperx", "ctranslate2", "faster-whisper", "transformers", "pyannote.audio", "torchcodec"):
        try:
            report["packages"][name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            report["packages"][name] = None
    try:
        report["nvidia_smi"] = subprocess.run(["nvidia-smi", "--query-gpu=name,driver_version,memory.total", "--format=csv,noheader"],
                                               capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        report["nvidia_smi"] = None
    with block_network():
        prepare_cuda_dlls()
        import torch
        import ctranslate2
        report.update(torch_cuda_runtime=torch.version.cuda, cuda_available=torch.cuda.is_available(),
                      torch_arch_list=torch.cuda.get_arch_list(), ct2_cuda_devices=ctranslate2.get_cuda_device_count(),
                      ct2_compute_types=sorted(ctranslate2.get_supported_compute_types("cuda")))
        tensor = torch.randn(512, 512, device="cuda")
        product = tensor @ tensor.T
        torch.cuda.synchronize()
        report.update(device_name=torch.cuda.get_device_name(0), compute_capability=torch.cuda.get_device_capability(0),
                      gpu_tensor_test=bool(torch.isfinite(product).all().item()))
    target = Path("artifacts/diagnostics.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["gpu_tensor_test"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
