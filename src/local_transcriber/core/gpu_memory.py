import gc
import importlib.util
import os
from pathlib import Path

_dll_handles = []


def prepare_cuda_dlls():
    """Use CUDA/cuDNN DLLs from the selected Torch wheel, without a global PATH change."""
    if os.name == "nt":
        spec = importlib.util.find_spec("torch")
        if spec and spec.origin:
            directory = Path(spec.origin).parent / "lib"
            _dll_handles.append(os.add_dll_directory(str(directory)))
            os.environ["PATH"] = str(directory) + os.pathsep + os.environ.get("PATH", "")


def release_cuda():
    import torch
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.synchronize()
        torch.cuda.empty_cache()
        return {"allocated_bytes": torch.cuda.memory_allocated(), "reserved_bytes": torch.cuda.memory_reserved()}
    return {"allocated_bytes": 0, "reserved_bytes": 0}
