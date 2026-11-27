"""Measure a real desktop run under Windows AppContainer without logging speech."""

import argparse
from dataclasses import replace
import json
from pathlib import Path
import sys
import time

from check_run import check
from verify_offline import probe_network, windows_network_isolation

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from local_transcriber.domain.paths import resolve_local
from local_transcriber.domain.transcript_schema import write_json
from local_transcriber.ui.__main__ import configure_media_environment
from local_transcriber.ui.settings import Settings


def wait(app, condition, timeout):
    deadline = time.perf_counter() + timeout
    while not condition() and time.perf_counter() < deadline:
        app.processEvents()
        time.sleep(0.01)
    return condition()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--run", type=Path, required=True, help="new local private output directory")
    parser.add_argument("--config", type=Path, default=Path("config.local.json"))
    parser.add_argument("--speakers", type=int, choices=range(1, 5), required=True)
    parser.add_argument("--profile", choices=("default", "memory"), default="default")
    parser.add_argument("--expect-overlap", action="store_true")
    parser.add_argument("--timeout", type=float, default=3600)
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be positive")

    isolation = windows_network_isolation()
    probes = probe_network() if isolation["verified"] else []
    verified = isolation["verified"] and all(probe["blocked"] for probe in probes)
    if not verified:
        print(json.dumps({"status": "failed", "error_code": "OS_NETWORK_ISOLATION_NOT_VERIFIED"}))
        return 3
    root = resolve_local(args.run)
    root.mkdir(parents=True, exist_ok=False)
    evidence = {"verified": True, "os_isolation": isolation, "unguarded_probes": probes}
    write_json(root / "network.json", evidence)

    configure_media_environment()
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from local_transcriber.ui.window import MainWindow

    settings = replace(Settings.load(resolve_local(args.config), root / "ui.local.json"), results=root)
    settings.save()
    app = QApplication([])
    window = MainWindow(settings)
    window.show()
    timer = QTimer(window)
    timer.setInterval(50)
    ticks = 0
    previous_tick = None
    max_gap = 0

    def tick():
        nonlocal ticks, previous_tick, max_gap
        now = time.perf_counter()
        if previous_tick is not None:
            max_gap = max(max_gap, now - previous_tick)
        previous_tick = now
        ticks += 1

    timer.timeout.connect(tick)
    try:
        window.select_source(str(resolve_local(args.input)))
        if not wait(app, lambda: window.task is None, 40) or not window.start.isEnabled():
            print(json.dumps({"status": "failed", "error_code": "BENCHMARK_MEDIA_IMPORT_FAILED"}))
            return 2
        window.speakers.setValue(args.speakers)
        window.profile.setCurrentIndex(window.profile.findData(args.profile))
        timer.start()
        started = time.perf_counter()
        window.start.click()
        done = wait(app, lambda: window.task is None, args.timeout)
        wall_seconds = time.perf_counter() - started
        timer.stop()
        if not done:
            window.cancel.click()
            wait(app, lambda: window.task is None, 60)
        outcome = {
            "status": "completed" if window.finished_project_id else "failed",
            "ui_wall_seconds": wall_seconds, "ui_timer_ticks": ticks,
            "ui_timer_max_gap_seconds": max_gap, "ui_timer_interval_seconds": 0.05,
            "qt_platform": app.platformName(), "network_verified": True,
        }
        if not window.finished_project_id:
            outcome["error_code"] = window.response.get("error_code", "BENCHMARK_INCOMPLETE")
            write_json(root / "benchmark.json", outcome)
            print(json.dumps(outcome))
            return 1

        metrics_path, = root.glob("desktop-*/metrics.json")
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        metrics.update(os_network_block_verified=True, os_network_evidence=evidence)
        write_json(metrics_path, metrics)
        validation = check(metrics_path.parent, args.speakers, expected_language="ru", expect_overlap=args.expect_overlap)
        outcome["validation"] = validation
        outcome["status"] = "completed" if validation["status"] == "completed" and ticks >= 2 and max_gap < 1 else "failed"
        write_json(root / "benchmark.json", outcome)
        print(json.dumps(outcome))
        return 0 if outcome["status"] == "completed" else 1
    finally:
        timer.stop()
        window.close()
        if window.task is not None:
            wait(app, lambda: window.task is None, 60)


if __name__ == "__main__":
    raise SystemExit(main())
