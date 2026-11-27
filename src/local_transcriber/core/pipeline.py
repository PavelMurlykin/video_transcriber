from datetime import datetime, timezone
import importlib.metadata
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading
import time

from local_transcriber.config import ConfigurationError, speaker_count_options
from local_transcriber.domain.entities import Project, Segment, Speaker, StageStatus, TranscriptionJob
from local_transcriber.domain.errors import ASROutOfMemory, MediaError
from local_transcriber.domain.transcript_schema import project_to_dict, segment_from_dict, write_json
from local_transcriber.storage.projects import DATABASE_FILENAME, ProjectStore, ProjectStoreError

from .media import create_run_directory, prepare_audio
from .model_manager import sha256, verify_models
from .offline_guard import offline_environment
from .speaker_merge import interval, merge
from .transcription import ASROptions, BEAM_SIZE


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


def _asr_segments(asr: dict, duration_ms: int) -> list[Segment]:
    segments = []
    for item in asr["segments"]:
        bounds = interval(item)
        if bounds is None or not item["text"].strip():
            continue
        start_ms, end_ms = (min(duration_ms, round(seconds * 1000)) for seconds in bounds)
        if end_ms > start_ms:
            segments.append(Segment(
                id=f"seg_{len(segments) + 1}", start_ms=start_ms, end_ms=end_ms,
                speaker_id="unknown", text=item["text"], requires_review=True,
                review_reasons=["alignment_pending", "speaker_unknown"],
            ))
    return segments


def _run_inference(stage: str, job: TranscriptionJob, config_path: Path, options: ASROptions) -> dict:
    started = time.perf_counter()
    command = [
        sys.executable, "-m", "local_transcriber.workers.transcription_worker", stage,
        "--config", str(config_path.resolve()), "--run-dir", str(job.run_dir),
    ]
    if stage == "asr":
        command.extend(["--language", options.language, "--profile", options.profile])
        if options.terms_file is not None:
            command.extend(["--terms-file", str(options.terms_file)])
    with Sampler() as sampler:
        # Library output can contain transcript text and the glossary.
        job.check_cancelled()
        with subprocess.Popen(
            command, env=offline_environment(job.run_dir / "runtime-cache"),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        ) as process:
            try:
                while True:
                    job.check_cancelled()
                    try:
                        exit_code = process.wait(timeout=0.2)
                        break
                    except subprocess.TimeoutExpired:
                        continue
            except BaseException:
                if process.poll() is None:
                    process.kill()
                raise
    status_path = job.run_dir / f"{stage}-status.json"
    status = (json.loads(status_path.read_text(encoding="utf-8")) if status_path.exists()
              else {"status": "failed", "error_type": "NativeWorkerExit"})
    return {**status, "stage": stage, "exit_code": exit_code,
            "wall_seconds": time.perf_counter() - started, **sampler.result(),
            "gpu_used_mib_after_worker_exit": gpu_memory_mib()}


def run_pipeline(
    config_path: Path, config: dict, source: Path, directory: Path, *,
    asr_only: bool = False, options: ASROptions = ASROptions(), project_db: Path | None = None,
    cancel_file: Path | None = None, event=print,
) -> dict:
    directory = create_run_directory(directory)
    job = TranscriptionJob(media_path=source, run_dir=directory, cancel_file=cancel_file)
    audio_path = job.run_dir / "audio.wav"
    project_path = job.run_dir / "transcript.json"
    compute_type, batch_size = options.inference_settings(config)
    speaker_options = speaker_count_options(config) if not asr_only else {}
    metrics = {"schema_version": 1, "status": "running", "stages": [], "offline_environment": True,
               "project_id": job.project_id, "project_checkpoints": [],
               "python_network_guard": True, "os_network_block_verified": False,
               "python_version": sys.version.split()[0], "versions": {},
               "stage_statuses": job.stages,
               "mode": "asr" if asr_only else "transcribe",
               "profile": {"device": config["device"], "compute_type": compute_type,
                           "batch_size": batch_size, "num_speakers": speaker_options.get("num_speakers"),
                           **{key: speaker_options[key] for key in ("min_speakers", "max_speakers") if key in speaker_options},
                           "beam_size": BEAM_SIZE, "language": options.language, "asr_profile": options.profile,
                           "terms_file_supplied": options.terms_file is not None}}
    for name in ("torch", "torchaudio", "torchvision", "whisperx", "ctranslate2", "faster-whisper", "pyannote.audio", "transformers"):
        try:
            metrics["versions"][name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            metrics["versions"][name] = None
    def save():
        (directory / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    revision = None

    def checkpoint(status: str = "incomplete"):
        nonlocal revision
        checkpoint_start = time.perf_counter()
        if revision is None:
            revision = store.create(project, status=status)
        else:
            revision = store.save(project, status=status, revision=revision)
        write_json(project_path, project_to_dict(project))
        metrics["project_checkpoints"].append({
            "stage": project.completed_stages[-1], "revision": revision,
            "wall_seconds": time.perf_counter() - checkpoint_start,
        })

    started = time.perf_counter()
    try:
        job.check_cancelled()
        errors = verify_models(config, asr_only=asr_only)
        if errors:
            metrics["verification_errors"] = errors
            raise ValueError("MODEL_VERIFICATION_FAILED")
        job.check_cancelled()
        store = ProjectStore(project_db or directory.parent / DATABASE_FILENAME)
        event(json.dumps({"stage": "audio", "status": "started"}))
        audio_start = time.perf_counter()
        processing_started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with job.stage("audio"):
            metadata = prepare_audio(job.media_path, audio_path, config, **({"cancel": job} if cancel_file else {}))
            metrics.update(metadata)
            metrics["prepared_audio_sha256"] = sha256(audio_path)
            project = Project(
                project_id=job.project_id, media_path=str(job.media_path.resolve()), language=options.language,
                duration_ms=metadata["duration_ms"], sample_rate=metadata["sample_rate"], channels=metadata["channels"],
                speakers=[], segments=[], completed_stages=["audio"],
                models_manifest_sha256=sha256(Path(config["manifest"])),
                processing_started_at=processing_started_at,
            )
            checkpoint()
        metrics["stages"].append({"stage": "audio", "wall_seconds": time.perf_counter() - audio_start, "status": job.stages["audio"]})
        save()
        event(json.dumps(metrics["stages"][-1]))
        inference_stages = ("asr",) if asr_only else ("asr", "alignment", "diarization")
        for stage in inference_stages:
            event(json.dumps({"stage": stage, "status": "started"}))
            with job.stage(stage):
                measurement = _run_inference(stage, job, config_path, options)
                metrics["stages"].append(measurement)
                if measurement["exit_code"] != 0 or measurement["status"] != StageStatus.COMPLETED:
                    if measurement.get("error_code") == ASROutOfMemory.code:
                        raise ASROutOfMemory
                    if measurement.get("error_code") == "INVALID_CONFIG":
                        raise ConfigurationError("Check the local ASR settings and the UTF-8 terms file (at most 4096 bytes).")
                    raise RuntimeError("INFERENCE_STAGE_FAILED")
                if stage == "asr":
                    asr = json.loads((directory / "asr.json").read_text(encoding="utf-8"))
                    project.original_asr = asr
                    project.language = asr["language"]
                    project.segments = _asr_segments(asr, project.duration_ms)
                    metrics["recognized_language"] = project.language
                elif stage == "alignment":
                    project.original_alignment = json.loads((directory / "alignment.json").read_text(encoding="utf-8"))
                else:
                    project.original_diarization = json.loads((directory / "diarization.json").read_text(encoding="utf-8"))
                project.completed_stages = [*job.completed_stages, stage]
                checkpoint("completed" if asr_only else "incomplete")
            save()
            event(json.dumps({"stage": stage, "status": measurement["status"], "wall_seconds": measurement["wall_seconds"]}))
        if not asr_only:
            job.check_cancelled()
            _merge_project(project, job, checkpoint, metrics, event)
        audio_path.unlink()
        metrics.update(status="completed", speaker_count=len(project.speakers), segment_count=len(project.segments),
                       segments_requiring_review=sum(s.requires_review for s in project.segments))
    except KeyboardInterrupt:
        metrics["status"] = "cancelled"
        raise
    except (MediaError, ASROutOfMemory, ProjectStoreError) as error:
        metrics.update(status="failed", error_type=type(error).__name__, error_code=error.code)
        raise
    except Exception as error:
        metrics.update(status="failed", error_type=type(error).__name__)
        raise
    finally:
        if revision is not None and metrics["status"] in ("failed", "cancelled"):
            try:
                store.set_status(job.project_id, status=metrics["status"], revision=revision)
            except (ProjectStoreError, sqlite3.Error, OSError) as error:
                metrics["project_status_error"] = type(error).__name__
        metrics["wall_seconds"] = time.perf_counter() - started
        save()
    return metrics


def _merge_project(project: Project, job: TranscriptionJob, checkpoint, metrics: dict, event) -> None:
    event(json.dumps({"stage": "merge", "status": "started"}))
    started = time.perf_counter()
    with job.stage("merge"):
        aligned, diarization = project.original_alignment, project.original_diarization
        merged = merge(project.original_asr, aligned, diarization["turns"], project.duration_ms,
                       exclusive_turns=diarization["exclusive_turns"])
        if not merged["segments"]:
            raise ValueError("NO_SPEECH_SEGMENTS")
        project.speakers = [Speaker(**item) for item in merged["speakers"]]
        project.segments = [segment_from_dict(item) for item in merged["segments"]]
        project.diarization_turns = merged["diarization_turns"]
        project.exclusive_diarization_turns = merged["exclusive_diarization_turns"]
        project.overlap_regions = merged["overlap_regions"]
        project.completed_stages = [*job.completed_stages, "merge"]
        checkpoint("completed")
    metrics["stages"].append({"stage": "merge", "status": "completed", "wall_seconds": time.perf_counter() - started,
                              "gpu_used_mib_after_worker_exit": gpu_memory_mib()})
    event(json.dumps({"stage": "merge", "status": "completed", "wall_seconds": metrics["stages"][-1]["wall_seconds"]}))
