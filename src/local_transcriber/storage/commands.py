"""CLI access to saved projects without loading media or inference models."""

import argparse
import json
from pathlib import Path
import sys

from local_transcriber.domain.errors import ExportError
from local_transcriber.domain.transcript_schema import project_from_dict, project_to_dict
from local_transcriber.export.document import ExportOptions, LANGUAGES, PRECISIONS
from local_transcriber.export.service import FORMATS, export_project
from local_transcriber.launch import default_path

from .editing import EditSession
from .projects import DATABASE_FILENAME, ProjectStore, ProjectStoreError, local_path


def add_project_commands(subparsers) -> None:
    parser = subparsers.add_parser("projects", help="list, import, open or edit saved projects")
    commands = parser.add_subparsers(dest="project_command", required=True)
    commands.add_parser("list")
    commands.add_parser("import").add_argument("transcript", type=Path)
    open_project = commands.add_parser("open")
    open_project.add_argument("project_id")
    open_project.add_argument("--output", type=Path, required=True, help="new path for the reopened JSON snapshot")
    edit = commands.add_parser("edit")
    edit.add_argument("project_id")
    edit.add_argument("--commands", type=Path, help="UTF-8 JSON Lines file (default: stdin)")
    export = commands.add_parser("export", help="save the current transcript as a document")
    export.add_argument("project_id")
    export.add_argument("--format", choices=FORMATS, required=True)
    export.add_argument("--output", type=Path, required=True, help="local file with the selected extension")
    export.add_argument("--language", choices=LANGUAGES, default="ru", help="document headings and labels")
    export.add_argument("--precision", choices=PRECISIONS, default="seconds")
    export.add_argument("--no-timestamps", action="store_true")
    export.add_argument("--no-speakers", action="store_true")
    export.add_argument("--compact", action="store_true")
    export.add_argument("--bom", action="store_true", help="write a UTF-8 BOM for TXT")
    export.add_argument("--overwrite", action="store_true")
    export.add_argument("--revision", type=int, help=argparse.SUPPRESS)


def run_project_command(args) -> int:
    store = ProjectStore(args.project_db or default_path("artifacts") / DATABASE_FILENAME)
    if args.project_command == "list":
        print(json.dumps({"projects": store.list_projects()}))
    elif args.project_command == "import":
        data = json.loads(local_path(args.transcript).read_text(encoding="utf-8-sig"))
        project = project_from_dict(data)
        status = "completed" if "merge" in project.completed_stages else "incomplete"
        revision = store.create(project, status=status)
        print(json.dumps({"project_id": project.project_id, "status": status, "revision": revision}))
    elif args.project_command == "open":
        saved = store.load(args.project_id)
        data = json.dumps(project_to_dict(saved.project), ensure_ascii=False, indent=2, allow_nan=False)
        try:
            with local_path(args.output).open("x", encoding="utf-8") as stream:
                stream.write(data)
        except FileExistsError:
            raise ProjectStoreError("PROJECT_OUTPUT_ALREADY_EXISTS") from None
        print(json.dumps({"project_id": saved.project.project_id, "status": saved.status, "revision": saved.revision}))
    elif args.project_command == "export":
        saved = store.load(args.project_id)
        if args.revision is not None and saved.revision != args.revision:
            raise ProjectStoreError("PROJECT_CHANGED")
        target = local_path(args.output)
        if target == store.path or target == Path(saved.project.media_path):
            raise ExportError("INVALID_EXPORT_TARGET", "Choose a different file from the source media or project database.")
        options = ExportOptions(
            show_timestamps=not args.no_timestamps, precision=args.precision, show_speakers=not args.no_speakers,
            separate_phrases=not args.compact, bom=args.bom, language=args.language,
        )
        export_project(saved.project, target, args.format, options, overwrite=args.overwrite)
        print(json.dumps({"status": "exported", "format": args.format, "revision": saved.revision}))
    else:
        session = EditSession(store, args.project_id)
        if args.commands is None:
            _edit(session, sys.stdin)
        else:
            with local_path(args.commands).open(encoding="utf-8-sig") as stream:
                _edit(session, stream)
    return 0


def _edit(session: EditSession, lines) -> None:
    for line in lines:
        if not line.strip():
            continue
        try:
            command = json.loads(line)
            op = command["op"]
            if op == "exit":
                return
            if op == "rename_speaker":
                session.rename_speaker(command["speaker_id"], command["display_name"])
            elif op == "set_segment_speaker":
                session.set_segment_speaker(command["segment_id"], command["speaker_id"])
            elif op == "set_segment_text":
                session.set_segment_text(command["segment_id"], command["text"])
            elif op == "undo":
                session.undo()
            elif op == "redo":
                session.redo()
            else:
                raise ProjectStoreError("INVALID_EDIT_COMMAND")
        except (KeyError, TypeError, ValueError):
            raise ProjectStoreError("INVALID_EDIT_COMMAND") from None
        print(json.dumps({"status": "saved", "op": op, "revision": session.saved.revision}), flush=True)
