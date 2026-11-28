import argparse
import os
from pathlib import Path
import sys

from local_transcriber.launch import default_path, prepare_default_config
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
    parser.add_argument("--config", type=Path)
    parser.add_argument("--preferences", type=Path, default=default_path("config.ui.local.json"))
    args = parser.parse_args(argv)
    configure_media_environment()
    try:
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication, QMessageBox
        from .window import MainWindow
    except ModuleNotFoundError as error:
        if not (error.name or "").startswith(("PySide6", "shiboken6")):
            raise
        print("Install the optional desktop dependencies from requirements-ui.lock.", file=sys.stderr)
        return 2

    try:
        config = local_path(args.config or default_path("config.local.json"))
        preferences = local_path(args.preferences)
        if config == preferences:
            raise ValueError("Configuration and preferences must use separate files")
        if args.config is None and not preferences.is_file():
            prepare_default_config(config)
        settings = Settings.load(config, preferences)
    except (OSError, ValueError, ProjectStoreError) as error:
        message = f"Cannot load desktop settings ({type(error).__name__}); check --config and --preferences."
        if getattr(sys, "frozen", False):
            app = QApplication([sys.argv[0]])
            QMessageBox.critical(None, "Local Transcriber", message)
        else:
            print(message, file=sys.stderr)
        return 2
    app = QApplication([sys.argv[0]])
    window = MainWindow(settings)
    window.show()
    QTimer.singleShot(0, window.check_startup)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
