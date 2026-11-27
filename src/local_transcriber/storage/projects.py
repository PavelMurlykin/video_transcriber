"""Keep the catalog and the current versioned transcript in one SQLite transaction."""

from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

from local_transcriber.domain.entities import Project
from local_transcriber.domain.paths import NonLocalPath, resolve_local
from local_transcriber.domain.transcript_schema import project_from_dict, project_to_dict

DATABASE_FILENAME = "projects.sqlite3"
DATABASE_VERSION = 1
APPLICATION_ID = 0x4C545231


class ProjectStoreError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def local_path(path: Path) -> Path:
    try:
        return resolve_local(path)
    except NonLocalPath:
        raise ProjectStoreError("PROJECT_PATH_NOT_LOCAL") from None


@dataclass(frozen=True)
class SavedProject:
    project: Project
    status: str
    revision: int


class ProjectStore:
    def __init__(self, path: Path):
        self.path = local_path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            app_id = db.execute("PRAGMA application_id").fetchone()[0]
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if app_id == version == 0 and db.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone() is None:
                db.execute("""
                    CREATE TABLE projects (
                        project_id TEXT PRIMARY KEY NOT NULL,
                        source_name TEXT NOT NULL,
                        language TEXT NOT NULL,
                        last_stage TEXT,
                        status TEXT NOT NULL CHECK(status IN ('incomplete', 'completed', 'failed', 'cancelled')),
                        revision INTEGER NOT NULL CHECK(revision > 0),
                        updated_at TEXT NOT NULL,
                        transcript_json TEXT NOT NULL
                    )
                """)
                db.execute(f"PRAGMA application_id = {APPLICATION_ID}")
                db.execute(f"PRAGMA user_version = {DATABASE_VERSION}")
            elif app_id != APPLICATION_ID:
                raise ProjectStoreError("NOT_A_PROJECT_DATABASE")
            elif version != DATABASE_VERSION:
                raise ProjectStoreError("UNSUPPORTED_PROJECT_DATABASE_VERSION")

    @contextmanager
    def _connect(self):
        with closing(sqlite3.connect(self.path, timeout=5)) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA synchronous = FULL")
            with db:
                yield db

    def list_projects(self) -> list[dict]:
        with self._connect() as db:
            rows = db.execute("""
                SELECT project_id, source_name, language, last_stage, status, revision, updated_at
                FROM projects ORDER BY updated_at DESC, project_id
            """)
            return [dict(row) for row in rows]

    def load(self, project_id: str) -> SavedProject:
        with self._connect() as db:
            row = db.execute(
                "SELECT transcript_json, status, revision FROM projects WHERE project_id = ?", (project_id,),
            ).fetchone()
        if row is None:
            raise ProjectStoreError("PROJECT_NOT_FOUND")
        return SavedProject(project_from_dict(json.loads(row["transcript_json"])), row["status"], row["revision"])

    def create(self, project: Project, *, status: str) -> int:
        with self._connect() as db:
            cursor = db.execute("""
                INSERT INTO projects
                    (source_name, language, last_stage, status, updated_at, transcript_json, project_id, revision)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                ON CONFLICT(project_id) DO NOTHING
            """, self._values(project, status))
            if cursor.rowcount != 1:
                raise ProjectStoreError("PROJECT_ALREADY_EXISTS")
        return 1

    def save(self, project: Project, *, status: str, revision: int) -> int:
        with self._connect() as db:
            cursor = db.execute("""
                UPDATE projects SET source_name = ?, language = ?, last_stage = ?, status = ?,
                    updated_at = ?, transcript_json = ?, revision = revision + 1
                WHERE project_id = ? AND revision = ?
            """, (*self._values(project, status), revision))
            if cursor.rowcount != 1:
                raise ProjectStoreError("PROJECT_CHANGED")
        return revision + 1

    def set_status(self, project_id: str, *, status: str, revision: int) -> None:
        with self._connect() as db:
            cursor = db.execute("""
                UPDATE projects SET status = ?, updated_at = ?, revision = revision + 1
                WHERE project_id = ? AND revision = ?
            """, (status, _now(), project_id, revision))
            if cursor.rowcount != 1:
                raise ProjectStoreError("PROJECT_CHANGED")

    @staticmethod
    def _values(project: Project, status: str) -> tuple:
        if not isinstance(project.project_id, str) or not project.project_id.strip():
            raise ProjectStoreError("INVALID_PROJECT_ID")
        snapshot = json.dumps(project_to_dict(project), ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        return (Path(project.media_path).name, project.language,
                project.completed_stages[-1] if project.completed_stages else None,
                status, _now(), snapshot, project.project_id)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")
