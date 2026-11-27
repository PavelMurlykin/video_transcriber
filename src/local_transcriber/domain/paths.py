from pathlib import Path
import os


class NonLocalPath(ValueError):
    pass


def _is_network_path(path: Path) -> bool:
    if str(path).startswith(("\\\\", "//")):
        return True
    if os.name == "nt" and path.drive:
        from ctypes import windll
        return windll.kernel32.GetDriveTypeW(path.drive + "\\") == 4
    return False


def resolve_local(path: Path, *, strict: bool = False) -> Path:
    if _is_network_path(path):
        raise NonLocalPath
    resolved = path.resolve(strict=strict)
    if _is_network_path(resolved):
        raise NonLocalPath
    return resolved
