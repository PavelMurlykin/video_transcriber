import argparse
import os
from pathlib import Path
import sys

from local_transcriber.storage.projects import ProjectStoreError, local_path

from .settings import Settings


def configure_media_environment() -> None:
    os.environ.update(QT_MEDIA_BACKEND="ffmpeg", QT_FFMPEG_PROTOCOL_WHITELIST="file")
    # Qt's FFmpeg info logging can include source paths and embedded metadata.
    os.environ.pop("QT_FFMPEG_DEBUG", None)
    rules = os.environ.get("QT_LOGGING_RULES", "")
    os.environ["QT_LOGGING_RULES"] = f"{rules};qt.multimedia.*=false"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Local Transcriber desktop client")
    parser.add_argument("--config", type=Path, default=Path("config.local.json"))
    parser.add_argument("--preferences", type=Path, default=Path("config.ui.local.json"))
    args = parser.parse_args(argv)
    configure_media_environment()
    try:
        from PySide6.QtWidgets import QApplication
        from .window import MainWindow
    except ModuleNotFoundError as error:
        if not (error.name or "").startswith(("PySide6", "shiboken6")):
            raise
        print("Install the optional desktop dependencies from requirements-ui.lock.", file=sys.stderr)
        return 2

    try:
        config, preferences = local_path(args.config), local_path(args.preferences)
        if config == preferences:
            raise ValueError("Configuration and preferences must use separate files")
        settings = Settings.load(config, preferences)
    except (OSError, ValueError, ProjectStoreError) as error:
        print(f"Cannot load desktop settings ({type(error).__name__}); check --config and --preferences.",
              file=sys.stderr)
        return 2
    app = QApplication([sys.argv[0]])
    window = MainWindow(settings)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
