from pathlib import Path

from .document import ExportDocument, ExportOptions


def write_txt(path: Path, document: ExportDocument, options: ExportOptions) -> None:
    separator = "\n\n" if options.separate_phrases else "\n"
    body = separator.join(document.phrases)
    text = "\n".join((document.title, *document.metadata, "", document.heading, "", body))
    encoding = "utf-8-sig" if options.bom else "utf-8"
    path.write_text(text if text.endswith("\n") else f"{text}\n", encoding=encoding, newline="\r\n")
