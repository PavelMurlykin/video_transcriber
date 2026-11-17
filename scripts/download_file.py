"""Range downloader for large public binaries when the full HTTP response stalls."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
from pathlib import Path
import shutil
import time
import urllib.request


def download(url: str, target: Path, expected_hash: str, workers: int = 8):
    target.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"Range": "bytes=0-0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        total = int(response.headers["Content-Range"].split("/")[-1])
    chunk_size = 16 * 1024 * 1024
    parts = target.with_suffix(target.suffix + ".parts")
    parts.mkdir(exist_ok=True)
    count = (total + chunk_size - 1) // chunk_size
    started = time.perf_counter()
    def fetch(index):
        start, end = index * chunk_size, min((index + 1) * chunk_size, total) - 1
        part = parts / f"{index:05d}"
        if part.exists() and part.stat().st_size == end - start + 1:
            return
        for attempt in range(4):
            try:
                request = urllib.request.Request(url, headers={"Range": f"bytes={start}-{end}"})
                with urllib.request.urlopen(request, timeout=120) as response:
                    if response.status != 206 or response.headers.get("Content-Range") != f"bytes {start}-{end}/{total}":
                        raise ValueError("INVALID_RANGE_RESPONSE")
                    with part.open("wb") as stream:
                        shutil.copyfileobj(response, stream, 1024 * 1024)
                if part.stat().st_size != end - start + 1:
                    raise ValueError("INCOMPLETE_RANGE")
                return
            except Exception:
                if attempt == 3:
                    raise
    with ThreadPoolExecutor(max_workers=workers) as pool:
        completed = 0
        for future in as_completed([pool.submit(fetch, i) for i in range(count)]):
            future.result()
            completed += 1
            if completed % 8 == 0 or completed == count:
                print(f"downloaded_chunks={completed}/{count} elapsed_seconds={time.perf_counter() - started:.1f}", flush=True)
    digest = hashlib.sha256()
    temporary = target.with_suffix(target.suffix + ".tmp")
    with temporary.open("wb") as stream:
        for index in range(count):
            with (parts / f"{index:05d}").open("rb") as part:
                for block in iter(lambda: part.read(8 * 1024 * 1024), b""):
                    stream.write(block)
                    digest.update(block)
    if digest.hexdigest() != expected_hash:
        raise ValueError("SHA256_MISMATCH")
    temporary.replace(target)
    # Delete only the explicit part files created by this invocation, no recursive path removal.
    for index in range(count):
        (parts / f"{index:05d}").unlink()
    parts.rmdir()
    print(f"verified_sha256={expected_hash}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    download(args.url, args.output, args.sha256, args.workers)
