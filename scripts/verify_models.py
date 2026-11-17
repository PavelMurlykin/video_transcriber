import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from local_transcriber.cli import main

raise SystemExit(main([*sys.argv[1:], "verify-models"]))
