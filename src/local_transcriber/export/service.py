import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from local_transcriber.domain.entities import Project
from local_transcriber.domain.errors import ExportError
from local_transcriber.storage.projects import local_path

from .document import ExportOptions, build_document
from .docx_exporter import write_docx
from .pdf_exporter import write_pdf
from .txt_exporter import write_txt

WRITERS = {"txt": write_txt, "docx": write_docx, "pdf": write_pdf}
FORMATS = tuple(WRITERS)


def export_project(
    project: Project, target: Path, file_format: str, options: ExportOptions, *, overwrite: bool = False,
) -> None:
    target = local_path(target)
    if file_format not in WRITERS or target.suffix.lower() != f".{file_format}":
        raise ExportError("INVALID_EXPORT_FORMAT", "Use the file extension for the selected format.")
    if options.bom and file_format != "txt":
        raise ExportError("INVALID_EXPORT_OPTIONS", "The UTF-8 BOM option applies to TXT only.")
    document = build_document(project, options)
    temporary = None
    try:
        if not overwrite and target.exists():
            raise FileExistsError
        with NamedTemporaryFile(dir=target.parent, prefix=".transcriber-", suffix=target.suffix, delete=False) as stream:
            temporary = Path(stream.name)
        WRITERS[file_format](temporary, document, options)
        if overwrite:
            temporary.replace(target)
        elif os.name == "nt":
            temporary.rename(target)
        else:
            os.link(temporary, target)
    except FileExistsError:
        raise ExportError("EXPORT_FILE_EXISTS", "Choose another file name or confirm replacement.") from None
    except ImportError:
        raise ExportError("EXPORT_DEPENDENCIES_MISSING", "Install the packages from requirements-export.lock.") from None
    except OSError:
        raise ExportError("EXPORT_WRITE_FAILED", "Check that the destination directory is writable and the file is closed.") from None
    except ExportError:
        raise
    except Exception:
        raise ExportError("EXPORT_RENDER_FAILED", "The document could not be generated with the selected format.") from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
