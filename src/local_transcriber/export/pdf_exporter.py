from pathlib import Path
from xml.sax.saxutils import escape

from local_transcriber.domain.errors import ExportError

from .document import ExportDocument, ExportOptions

FONTS = Path(__file__).with_name("fonts")
REGULAR = "TranscriberSans"
BOLD = "TranscriberSans-Bold"


def write_pdf(path: Path, document: ExportDocument, options: ExportOptions) -> None:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import Paragraph, SimpleDocTemplate

    for name, filename in ((REGULAR, "DejaVuSans.ttf"), (BOLD, "DejaVuSans-Bold.ttf")):
        if name not in pdfmetrics.getRegisteredFontNames():
            font_path = FONTS / filename
            if not font_path.is_file():
                raise ExportError("PDF_FONT_MISSING", "Reinstall the bundled DejaVu Sans fonts.")
            pdfmetrics.registerFont(TTFont(name, str(font_path)))

    regular = pdfmetrics.getFont(REGULAR).face.charToGlyph
    bold = pdfmetrics.getFont(BOLD).face.charToGlyph
    for texts, glyphs in (((*document.metadata, *document.phrases), regular), ((document.title, document.heading), bold)):
        if any(not char.isspace() and ord(char) not in glyphs for text in texts for char in text):
            raise ExportError("PDF_UNSUPPORTED_CHARACTER", "Some characters require another font. Use TXT or DOCX.")

    body = ParagraphStyle("Phrase", fontName=REGULAR, fontSize=10, leading=14,
                          spaceAfter=8 if options.separate_phrases else 0, splitLongWords=True)
    meta = ParagraphStyle("Metadata", parent=body, fontSize=9, leading=13,
                          textColor=colors.HexColor("#414b58"), spaceAfter=3)
    title = ParagraphStyle("Title", parent=body, fontName=BOLD, fontSize=21, leading=26,
                           spaceAfter=11, keepWithNext=True)
    heading = ParagraphStyle("Heading", parent=body, fontName=BOLD, fontSize=13, leading=18,
                             spaceBefore=10, spaceAfter=6, keepWithNext=True)

    def paragraph(text, style):
        return Paragraph(escape(text).replace("\n", "<br/>"), style)

    story = [paragraph(document.title, title), *(paragraph(line, meta) for line in document.metadata)]
    story.append(paragraph(document.heading, heading))
    story.extend(paragraph(text, body) for text in document.phrases)
    margins = 50
    page = SimpleDocTemplate(str(path), pagesize=A4, title=document.title, author="Local Transcriber",
                             leftMargin=margins, rightMargin=margins, topMargin=64, bottomMargin=56)

    def margins_text(canvas, template):
        width, height = template.pagesize
        canvas.saveState()
        canvas.setFont(REGULAR, 9)
        canvas.setFillColor(colors.HexColor("#414b58"))
        canvas.drawString(margins + 6, height - 37, document.heading)
        canvas.drawRightString(width - margins - 6, 33, str(template.page))
        canvas.restoreState()

    page.build(story, onFirstPage=margins_text, onLaterPages=margins_text)
