"""CLI access to saved projects without loading media or inference models."""

import json
from pathlib import Path
import sys

from local_transcriber.domain.transcript_schema import project_from_dict, project_to_dict

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


def run_project_command(args) -> int:
    store = ProjectStore(args.project_db or Path("artifacts") / DATABASE_FILENAME)
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
