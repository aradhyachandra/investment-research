"""Build small test PDFs with known text on known pages (layout loosely copies the TCS annual
report: running header at the top, printed page number in the footer, 9pt body, bold headings).

A page is a dict:
    {"blocks": [("h", "Heading"), ("p", "Body text ..."), ...], "footer": "12"}
A two-page spread (one PDF page holding two printed pages side by side):
    {"left": [...blocks...], "right": [...blocks...], "footers": ("4", "5")}
"""
import pymupdf

PAGE_W, PAGE_H = 594, 756
BODY_SIZE, HEADING_SIZE = 9, 12


def _write_blocks(page, blocks, x0, x1):
    y = 80
    for kind, text in blocks:
        size, font = (HEADING_SIZE, "hebo") if kind == "h" else (BODY_SIZE, "helv")
        rect = pymupdf.Rect(x0, y, x1, PAGE_H - 60)
        spare = page.insert_textbox(rect, text, fontsize=size, fontname=font)
        if spare < 0:
            raise ValueError(f"test text does not fit on the page: {text[:40]!r}")
        used = (rect.height - spare)
        y += used + 10


def _header_footer(page, x_footer, footer_text, header_x=60):
    page.insert_text((header_x, 40), "Statutory Reports  Corporate Overview", fontsize=8, fontname="helv")
    if footer_text:
        page.insert_text((x_footer, 735), footer_text, fontsize=9, fontname="helv")


def build_pdf(path, pages):
    doc = pymupdf.open()
    for spec in pages:
        if "left" in spec:
            page = doc.new_page(width=2 * PAGE_W, height=PAGE_H)
            left_f, right_f = spec.get("footers", (None, None))
            _header_footer(page, 47, left_f)
            _header_footer(page, 2 * PAGE_W - 56, right_f, header_x=PAGE_W + 60)
            _write_blocks(page, spec["left"], 50, PAGE_W - 50)
            _write_blocks(page, spec["right"], PAGE_W + 50, 2 * PAGE_W - 50)
        else:
            page = doc.new_page(width=PAGE_W, height=PAGE_H)
            _header_footer(page, 538, spec.get("footer"))
            _write_blocks(page, spec.get("blocks", []), 60, PAGE_W - 60)
    doc.save(path)
    doc.close()
    return path


def sentences(word, n):
    """n distinct sentences that all contain `word`, to fill a page with known text."""
    return " ".join(f"Sentence {i} about {word} and the business of the company." for i in range(n))
