"""Run the real CLI under demonstrable OS network isolation, in addition to Python guards."""
import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import socket
import subprocess
import sys


def windows_network_isolation() -> dict:
    if os.name != "nt":
        return {"verified": False, "reason": "requires_windows_appcontainer_or_external_firewall_evidence"}
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    token = wintypes.HANDLE()
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    advapi.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    advapi.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
    if not advapi.OpenProcessToken(kernel.GetCurrentProcess(), 8, ctypes.byref(token)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        value, needed = wintypes.DWORD(), wintypes.DWORD()
        if not advapi.GetTokenInformation(token, 29, ctypes.byref(value), ctypes.sizeof(value), ctypes.byref(needed)):
            raise ctypes.WinError(ctypes.get_last_error())
        if not value.value:
            return {"verified": False, "is_appcontainer": False, "reason": "no_os_isolation_evidence"}
        advapi.GetTokenInformation(token, 30, None, 0, ctypes.byref(needed))
        buffer = ctypes.create_string_buffer(needed.value)
        if not advapi.GetTokenInformation(token, 30, buffer, needed, ctypes.byref(needed)):
            raise ctypes.WinError(ctypes.get_last_error())
        class SidAndAttributes(ctypes.Structure):
            _fields_ = [("sid", ctypes.c_void_p), ("attributes", wintypes.DWORD)]
        class TokenGroups(ctypes.Structure):
            _fields_ = [("count", wintypes.DWORD), ("groups", SidAndAttributes * 1)]
        count = ctypes.cast(buffer, ctypes.POINTER(wintypes.DWORD)).contents.value
        groups = (SidAndAttributes * count).from_buffer(buffer, TokenGroups.groups.offset)
        capabilities = []
        for group in groups:
            value_string = wintypes.LPWSTR()
            if advapi.ConvertSidToStringSidW(group.sid, ctypes.byref(value_string)):
                capabilities.append(value_string.value)
                kernel.LocalFree(value_string)
        network_caps = {"S-1-15-3-1", "S-1-15-3-2", "S-1-15-3-3"}
        return {"verified": not bool(network_caps.intersection(capabilities)), "is_appcontainer": True,
                "network_capabilities_present": sorted(network_caps.intersection(capabilities))}
    finally:
        kernel.CloseHandle(token)


def probe_network() -> list[dict]:
    """Unguarded probes; no user data is sent. Numeric addresses avoid a DNS-only false pass."""
    outcomes = []
    for address in ("1.1.1.1", "8.8.8.8"):
        try:
            with socket.create_connection((address, 443), timeout=2):
                outcomes.append({"probe": address + ":443", "blocked": False})
        except OSError as error:
            outcomes.append({"probe": address + ":443", "blocked": True, "winerror": getattr(error, "winerror", None),
                             "error_type": type(error).__name__})
    try:
        socket.getaddrinfo("huggingface.co", 443)
        outcomes.append({"probe": "dns:huggingface.co", "blocked": False})
    except OSError as error:
        outcomes.append({"probe": "dns:huggingface.co", "blocked": True, "error_type": type(error).__name__})
    return outcomes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config.local.json"))
    parser.add_argument("--input", type=Path)
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--evidence", type=Path, default=Path("artifacts/network-isolation.json"))
    args = parser.parse_args()
    evidence = {"os_isolation": windows_network_isolation(), "unguarded_probes": probe_network()}
    evidence["verified"] = evidence["os_isolation"]["verified"] and all(p["blocked"] for p in evidence["unguarded_probes"])
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    args.evidence.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(json.dumps(evidence), flush=True)
    if not evidence["verified"]:
        return 3
    if not args.input:
        return 0
    if not args.run_dir:
        parser.error("--run-dir required with --input")
    result = subprocess.run([sys.executable, "-m", "local_transcriber", "--config", str(args.config),
                             "transcribe", str(args.input), "--run-dir", str(args.run_dir)])
    path = args.run_dir / "metrics.json"
    if path.exists():
        metrics = json.loads(path.read_text(encoding="utf-8"))
        metrics.update(os_network_block_verified=True, os_network_evidence=evidence)
        path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
