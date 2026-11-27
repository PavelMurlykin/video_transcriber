from datetime import datetime, timezone
from pathlib import Path

from .document import ExportDocument, ExportOptions


def write_docx(path: Path, document: ExportDocument, options: ExportOptions) -> None:
    from docx import Document
    from docx.enum.style import WD_STYLE_TYPE
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Mm, Pt, RGBColor

    output = Document()
    section = output.sections[0]
    section.page_width, section.page_height = Mm(210), Mm(297)
    section.top_margin = section.bottom_margin = Mm(20)
    section.left_margin = section.right_margin = Mm(21)

    normal = output.styles["Normal"]
    normal.font.name = "Arial"
    normal.font.size = Pt(11)
    normal.paragraph_format.space_after = Pt(3)
    for name, size in (("Title", 22), ("Heading 1", 14)):
        heading = output.styles[name]
        heading.font.name = "Arial"
        heading.font.color.rgb = RGBColor(0, 0, 0)
        heading.font.size = Pt(size)
        heading.font.bold = True
        heading.paragraph_format.space_after = Pt(8)
        properties = heading.element.find(qn("w:pPr"))
        if properties is not None:
            border = properties.find(qn("w:pBdr"))
            if border is not None:
                properties.remove(border)

    phrase = output.styles.add_style("Transcript Phrase", WD_STYLE_TYPE.PARAGRAPH)
    phrase.base_style = normal
    phrase.paragraph_format.space_after = Pt(9 if options.separate_phrases else 0)
    phrase.paragraph_format.keep_together = False
    phrase.paragraph_format.widow_control = True

    properties = output.core_properties
    properties.title = document.title
    properties.subject = document.heading
    properties.author = "Local Transcriber"
    properties.created = properties.modified = datetime.now(timezone.utc)
    output.add_heading(document.title, level=0)
    for metadata in document.metadata:
        output.add_paragraph(metadata)
    output.add_heading(document.heading, level=1)
    for text in document.phrases:
        output.add_paragraph(text, style=phrase)

    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    page_number = OxmlElement("w:fldSimple")
    page_number.set(qn("w:instr"), "PAGE")
    result = OxmlElement("w:r")
    value = OxmlElement("w:t")
    value.text = "1"
    result.append(value)
    page_number.append(result)
    footer._p.append(page_number)
    output.save(path)
