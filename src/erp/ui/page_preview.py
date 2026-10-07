"""Source page preview (M8.1): show a cited PDF page as an image, with the cited figure or sentence
highlighted when it can be found on the page.

Reads the PDFs in data/raw/ (the author's private data checkout) and nothing else. The PDF is opened
read-only; the highlight is drawn on the in-memory copy and never saved, and the rendered image is only
sent to the browser. No PDF or page image is ever written into the repo. In a fresh clone data/raw/ is
missing, and the page says so instead.

Which file a citation points at: the document title in the citation is looked up in the company config
(config/companies/<ticker>.yaml, `sources[].title` -> `file_name`), so this works in --demo mode without
the database.
"""
import re
from pathlib import Path

import pymupdf
import yaml
from pydantic import BaseModel

ZOOM = 1.5                                # 1.5 x 72 dpi = 108 dpi: readable, small enough for 8 GB RAM


class PreviewError(RuntimeError):
    pass


class PagePreview(BaseModel):
    png: bytes
    found: list[str]                      # needles found (and highlighted) on the page
    note: str


# ---------- what to look for ----------

def _indian_grouping(n: int) -> str:
    """267021 -> '2,67,021' (lakh/crore grouping, as TCS filings print figures)."""
    s = str(n)
    if len(s) <= 3:
        return s
    head, tail = s[:-3], s[-3:]
    pairs = []
    while len(head) > 2:
        pairs.insert(0, head[-2:])
        head = head[:-2]
    return ",".join([head, *pairs, tail])


def number_needles(value: float) -> list[str]:
    """Ways a filing may print a figure: Indian grouping first, then international, then plain.
    The sign is dropped (filings often print negatives in brackets)."""
    v = abs(float(value))
    if v.is_integer():
        whole, frac = int(v), ""
    else:
        whole_text, frac_text = repr(v).split(".")
        whole, frac = int(whole_text), "." + frac_text
    out = []
    for text in (_indian_grouping(whole), f"{whole:,}", str(whole)):
        if text + frac not in out:
            out.append(text + frac)
    return out


def passage_needles(text: str, min_chars: int = 25, limit: int = 8) -> list[str]:
    """Whole sentences of a retrieved passage, long enough to be distinctive."""
    flat = " ".join(text.split())
    sentences = re.split(r"(?<=[.!?])\s+", flat)
    return [s for s in sentences if len(s) >= min_chars and s[-1] in ".!?"][:limit]


# ---------- which file ----------

def source_files(company_config) -> dict[str, str]:
    """Document title -> file name, from the company config."""
    with open(company_config) as f:
        cfg = yaml.safe_load(f)
    return {s["title"]: s["file_name"] for s in cfg.get("sources", [])}


def pdf_for_title(title: str, files: dict[str, str], raw_dir) -> tuple[Path | None, str | None]:
    """(path, None) if the PDF is on this machine, else (None, a reason the page can show)."""
    if title not in files:
        return None, f"'{title}' is not a document listed in the company config, so there is no PDF to show."
    raw = Path(raw_dir)
    if not raw.is_dir():
        return None, ("The source PDFs are not in this checkout (data/raw/ is the author's private data repo). "
                      "Use the document and PDF page shown above to find the page in the official filing.")
    path = raw / files[title]
    if not path.is_file():
        return None, f"{files[title]} is not in data/raw/ on this machine."
    return path, None


# ---------- rendering ----------

def _joined_word_matches(page, needle: str, max_words: int = 6) -> list:
    """Areas of runs of whole words that spell `needle` once the spaces between them are dropped.
    PDF extraction sometimes splits a printed figure into words ("49, 454" for 49,454)."""
    words = page.get_text("words")       # (x0, y0, x1, y1, text, block, line, word_no)
    matches = []
    for i in range(len(words)):
        joined, rects = "", []
        for w in words[i:i + max_words]:
            joined += w[4]
            rects.append(pymupdf.Rect(w[:4]))
            if joined == needle or joined.rstrip(".;:)") == needle:   # sentence punctuation after a figure
                matches.extend(rects)
                break
            if not needle.startswith(joined):
                break
    return matches


def render_page(pdf_path, page_number: int, needles: list[str], zoom: float = ZOOM) -> PagePreview:
    """Render one page (1-based PDF index) as PNG, highlighting every needle found on it."""
    with pymupdf.open(pdf_path) as doc:
        if not 1 <= page_number <= doc.page_count:
            raise PreviewError(f"page {page_number} is outside {Path(pdf_path).name} (1-{doc.page_count})")
        page = doc[page_number - 1]
        found = []
        for needle in needles:
            drawn = 0
            areas = page.search_for(needle, quads=True) or _joined_word_matches(page, needle)
            for quad in areas:
                try:
                    page.add_highlight_annot(quad)
                    drawn += 1
                except ValueError:        # degenerate match area on some designed pages: skip it
                    continue
            if drawn:
                found.append(needle)
        png = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom)).tobytes("png")
        # The document is closed without saving, so the highlight never reaches the file on disk.
    if len(found) == 1:
        note = f"Highlighted on the page: {found[0]}"
    elif found:
        note = f"Highlighted {len(found)} of {len(needles)} sentences of the passage."
    elif needles:
        note = "The cited text was not found on this page as extracted, so nothing is highlighted."
    else:
        note = "Nothing to highlight for this citation."
    return PagePreview(png=png, found=found, note=note)
