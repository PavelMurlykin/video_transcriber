"""Exercise the configured compute device without importing or loading models."""

import sys

from local_transcriber.core.offline_guard import offline_runtime

TORCH_FAILED = 10
CUDA_UNAVAILABLE = 11
CT2_FAILED = 12
COMPUTE_UNSUPPORTED = 13


def check_compute(device: str, compute_type: str) -> int:
    with offline_runtime():
        try:
            from local_transcriber.core.gpu_memory import prepare_cuda_dlls
            if device == "cuda":
                prepare_cuda_dlls()
            import torch
            if device == "cuda" and not torch.cuda.is_available():
                return CUDA_UNAVAILABLE
            matrix = torch.ones((2, 2), device=device)
            if not torch.all(matrix @ matrix == 2).item():
                return TORCH_FAILED
        except Exception:
            return TORCH_FAILED
        try:
            import ctranslate2
            supported = ctranslate2.get_supported_compute_types(device)
        except Exception:
            return CT2_FAILED
        return 0 if compute_type in supported else COMPUTE_UNSUPPORTED


if __name__ == "__main__":
    raise SystemExit(check_compute(*sys.argv[1:]))
