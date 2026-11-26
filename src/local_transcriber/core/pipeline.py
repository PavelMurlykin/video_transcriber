import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys
import threading
import time

from local_transcriber.domain.entities import StageStatus, TranscriptionJob
from local_transcriber.domain.errors import MediaError
from local_transcriber.domain.transcript_schema import SCHEMA_VERSION, project_from_dict, project_to_dict

from .media import create_run_directory, prepare_audio
from .model_manager import sha256, verify_models
from .offline_guard import offline_environment
from .speaker_merge import merge


def gpu_memory_mib():
    try:
        result = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                                capture_output=True, text=True, timeout=5, check=True)
        return int(result.stdout.splitlines()[0].strip())
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


class Sampler:
    """Sample whole-device VRAM and parent/child RSS (not just Torch's allocator)."""
    def __init__(self):
        self.stop = threading.Event()
        self.max_vram_mib = None
        self.max_rss_bytes = 0
        self.samples = 0
        self.thread = threading.Thread(target=self.sample, daemon=True)

    def sample(self):
        import psutil
        parent = psutil.Process()
        while not self.stop.is_set():
            value = gpu_memory_mib()
            if value is not None:
                self.max_vram_mib = max(self.max_vram_mib or 0, value)
            rss = 0
            try:
                processes = [parent, *parent.children(recursive=True)]
            except psutil.Error:
                processes = [parent]
            for process in processes:
                try:
                    rss += process.memory_info().rss
                except psutil.Error:
                    pass
            self.max_rss_bytes = max(self.max_rss_bytes, rss)
            self.samples += 1
            self.stop.wait(0.5)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.stop.set()
        self.thread.join(timeout=6)

    def result(self):
        return {"sampled_peak_gpu_used_mib": self.max_vram_mib, "sampled_peak_process_tree_rss_bytes": self.max_rss_bytes,
                "samples": self.samples, "sampling_interval_seconds": 0.5,
                "gpu_measurement_scope": "whole_device_including_other_processes"}


def run_pipeline(config_path: Path, config: dict, source: Path, directory: Path, *, event=print) -> dict:
    directory = create_run_directory(directory)
    job = TranscriptionJob(media_path=source, run_dir=directory)
    audio_path = job.run_dir / "audio.wav"
    metrics = {"schema_version": 1, "status": "running", "stages": [], "offline_environment": True,
               "python_network_guard": True, "os_network_block_verified": False,
               "python_version": sys.version.split()[0], "versions": {},
               "stage_statuses": job.stages,
               "profile": {"device": config["device"], "compute_type": config["compute_type"],
                           "batch_size": config["batch_size"], "num_speakers": config.get("num_speakers"),
                           "beam_size": 5, "language": "ru"}}
    for name in ("torch", "torchaudio", "torchvision", "whisperx", "ctranslate2", "faster-whisper", "pyannote.audio", "transformers"):
        try:
            metrics["versions"][name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            metrics["versions"][name] = None
    def save():
        (directory / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    started = time.perf_counter()
    try:
        errors = verify_models(config)
        if errors:
            metrics["verification_errors"] = errors
            raise ValueError("MODEL_VERIFICATION_FAILED")
        event(json.dumps({"stage": "audio", "status": "started"}))
        audio_start = time.perf_counter()
        with job.stage("audio"):
            metadata = prepare_audio(job.media_path, audio_path, config)
            metrics.update(metadata)
            metrics["prepared_audio_sha256"] = sha256(audio_path)
        metrics["stages"].append({"stage": "audio", "wall_seconds": time.perf_counter() - audio_start, "status": job.stages["audio"]})
        for stage in ("asr", "alignment", "diarization"):
            event(json.dumps({"stage": stage, "status": "started"}))
            stage_start = time.perf_counter()
            with job.stage(stage):
                with Sampler() as sampler:
                    # Library output can contain transcript text.
                    process = subprocess.run(
                        [sys.executable, "-m", "local_transcriber.workers.transcription_worker", stage,
                         "--config", str(config_path.resolve()), "--run-dir", str(directory)],
                        env=offline_environment(directory / "runtime-cache"),
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    )
                status_path = directory / f"{stage}-status.json"
                status = (json.loads(status_path.read_text(encoding="utf-8")) if status_path.exists()
                          else {"status": "failed", "error_type": "NativeWorkerExit"})
                measurement = {**status, "stage": stage, "exit_code": process.returncode,
                               "wall_seconds": time.perf_counter() - stage_start, **sampler.result(),
                               "gpu_used_mib_after_worker_exit": gpu_memory_mib()}
                metrics["stages"].append(measurement)
                if process.returncode != 0 or status["status"] != StageStatus.COMPLETED:
                    raise RuntimeError("INFERENCE_STAGE_FAILED")
            save()
            event(json.dumps({"stage": stage, "status": status["status"], "wall_seconds": measurement["wall_seconds"]}))
        event(json.dumps({"stage": "merge", "status": "started"}))
        merge_start = time.perf_counter()
        with job.stage("merge"):
            asr, aligned, turns = [json.loads((directory / f"{stage}.json").read_text(encoding="utf-8"))
                                   for stage in ("asr", "alignment", "diarization")]
            merged = merge(asr, aligned, turns, metadata["duration_ms"])
            if not merged["segments"]:
                raise ValueError("NO_SPEECH_SEGMENTS")
            project = project_from_dict({
                "schema_version": SCHEMA_VERSION, "project_id": job.project_id, "media_path": str(job.media_path.resolve()),
                "language": "ru", **{key: metadata[key] for key in ("duration_ms", "sample_rate", "channels")},
                **merged, "original_asr": asr, "original_alignment": aligned,
                "completed_stages": [*job.completed_stages, "merge"],
                "models_manifest_sha256": sha256(Path(config["manifest"])),
            })
            payload = json.dumps(project_to_dict(project), ensure_ascii=False, indent=2, allow_nan=False)
            temporary_json = directory / "transcript.json.tmp"
            temporary_json.write_text(payload, encoding="utf-8")
            temporary_json.replace(directory / "transcript.json")
        metrics["stages"].append({"stage": "merge", "status": "completed", "wall_seconds": time.perf_counter() - merge_start,
                                  "gpu_used_mib_after_worker_exit": gpu_memory_mib()})
        audio_path.unlink()
        metrics.update(status="completed", speaker_count=len(project.speakers), segment_count=len(project.segments),
                       segments_requiring_review=sum(s.requires_review for s in project.segments))
    except KeyboardInterrupt:
        metrics["status"] = "cancelled"
        raise
    except MediaError as error:
        metrics.update(status="failed", error_type=type(error).__name__, error_code=error.code)
        raise
    except Exception as error:
        metrics.update(status="failed", error_type=type(error).__name__)
        raise
    finally:
        metrics["wall_seconds"] = time.perf_counter() - started
        save()
    return metrics
