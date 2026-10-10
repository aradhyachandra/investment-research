"""Turn a PDF into text chunks, each tied to the PDF page it came from.

No embedding and no database here: this module only reads the PDF (PyMuPDF) and returns
chunks with page, printed page label, section and a table flag. index_chroma.py adds the
document metadata (source_id, title, ...) and stores them.

How a PDF becomes chunks:
1. Each PDF page is read line by line, in the order the PDF stores its text (for the TCS
   report this follows the columns; sorting by position would interleave the two columns).
   A two-page spread (configured in page_labels with per_pdf_page: 2) is read as a left half
   and a right half, so each half gets its own printed page number.
2. Running headers and footers (top/bottom bands of the page) are dropped.
3. A bold line clearly larger than the body text is a heading. It starts a new section;
   the section name carries over to later pages until the next heading.
4. Each section on a page is cut into chunks of at most ~max_chars, on line boundaries, with
   a small overlap. Chunks stay on one page, except that a very short piece at the end of a
   page joins the first chunk of the next page when no new heading starts there; that chunk
   records both pages (page .. page_end).

Printed page numbers come from config (page_labels), not from the page footer: in the TCS
report some footer digits are missing from the PDF text layer ("90" reads as "9"). The footer
(and, since D3, the page header, where the FY25 and FY24 reports print it) is still read and
compared with the config, and disagreements are reported.

Chunk text is for qualitative questions only. Numbers in it can be mangled by extraction
(e.g. "2, 7 1, 423"); figures always come from SQLite, never from chunk text.
"""
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf
import yaml

REPO = Path(__file__).resolve().parents[3]
INGEST_CONFIG = REPO / "config" / "ingest.yaml"


@dataclass
class Chunk:
    text: str
    page: int                 # PDF page index, 1-based (first page if the chunk spans pages)
    page_end: int             # last PDF page the chunk covers (= page for most chunks)
    page_label: str           # printed page number of `page` ("" if none is printed)
    page_label_end: str
    section: str              # latest heading seen ("" before the first heading)
    is_table_heavy: bool
    starts_with_heading: bool = False


@dataclass
class ExtractResult:
    chunks: list
    label_warnings: list = field(default_factory=list)
    n_pages: int = 0


@dataclass
class _Line:
    text: str
    size: float
    bold: bool


@dataclass
class _Part:
    """One printed page: a whole PDF page, or one half of a two-page spread."""
    page: int
    label: str
    lines: list


def load_ingest_config(path=INGEST_CONFIG) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def parse_page_labels(page_labels) -> dict:
    """Config ranges -> {pdf_page: [printed labels]} (two labels for a two-page spread).

    Each range: {pdf_pages: [first, last], first_printed: N, per_pdf_page: 1 or 2}.
    """
    labels = {}
    for r in page_labels or []:
        try:
            first, last = r["pdf_pages"]
            printed = r["first_printed"]
        except (KeyError, TypeError, ValueError):
            raise ValueError(f"page_labels entry needs pdf_pages: [first, last] and first_printed: {r!r}") from None
        per = r.get("per_pdf_page", 1)
        if not all(isinstance(v, int) for v in (first, last, printed, per)):
            raise ValueError(f"page_labels entry must use whole numbers: {r!r}")
        if first < 1 or last < first or printed < 1 or per not in (1, 2):
            raise ValueError(f"page_labels entry is out of range: {r!r}")
        for pdf_page in range(first, last + 1):
            if pdf_page in labels:
                raise ValueError(f"page_labels: PDF page {pdf_page} is in two ranges")
            start = printed + (pdf_page - first) * per
            labels[pdf_page] = [str(start + k) for k in range(per)]
    return labels


def _is_bold(span) -> bool:
    return bool(span["flags"] & 16) or "bold" in span["font"].lower()


def _read_lines(page, clip, header_band, footer_band) -> list:
    lines = []
    top, bottom = clip.y0 + header_band, clip.y1 - footer_band
    for block in page.get_text("dict", clip=clip)["blocks"]:
        for line in block.get("lines", []):
            spans = [s for s in line["spans"] if s["text"].strip()]
            if not spans:
                continue
            y0 = line["bbox"][1]
            if y0 < top or y0 > bottom:
                continue    # running header / footer
            text = re.sub(r"\s+", " ", "".join(s["text"] for s in line["spans"])).strip()
            main = max(spans, key=lambda s: len(s["text"].strip()))
            lines.append(_Line(text=text, size=round(main["size"], 1), bold=_is_bold(main)))
    return lines


def _footer_numbers(page, clip, footer_band) -> list:
    """Digit groups printed in the footer band near the left edge, right edge or centre."""
    return _band_numbers(page, clip, pymupdf.Rect(clip.x0, clip.y1 - footer_band, clip.x1, clip.y1))


def _page_numbers(page, clip, footer_band, header_band) -> list:
    """Digit groups in the footer band, then in the header band. The FY26 report prints its page
    numbers in the footer; the FY25 and FY24 reports print them in the page header (D3)."""
    header = pymupdf.Rect(clip.x0, clip.y0, clip.x1, clip.y0 + header_band)
    return _footer_numbers(page, clip, footer_band) + _band_numbers(page, clip, header)


def _band_numbers(page, clip, band) -> list:
    chars = set()
    for block in page.get_text("rawdict", clip=band)["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                for ch in span["chars"]:
                    x0 = ch["bbox"][0]
                    near = (x0 - clip.x0 < 110 or clip.x1 - x0 < 110
                            or abs(x0 - (clip.x0 + clip.x1) / 2) < 60)
                    if ch["c"].isdigit() and near:
                        # Row = rounded baseline: digits only join within one printed line, so a
                        # body-text digit just below a header page number is not glued onto it (D3).
                        chars.add((round(ch["bbox"][3] / 3), round(x0, 1), ch["c"]))
    groups, last = [], None
    for row, x, c in sorted(chars):
        if last is not None and row == last[0] and x - last[1] < 12:
            groups[-1] += c
        else:
            groups.append(c)
        last = (row, x)
    return groups


def _is_subsequence(short: str, long: str) -> bool:
    it = iter(long)
    return all(c in it for c in short)


def _check_label(page_no, label, found) -> str | None:
    # Footers may print leading zeros ("0 9"), so compare as numbers and as padded strings.
    if any(int(f) == int(label) for f in found):
        return None
    # Soft warnings end in "(config kept)": the footer is unreadable, not contradicting.
    if not found:
        return f"PDF page {page_no}: no readable page number in the footer, config says {label!r} (config kept)"
    if any(_is_subsequence(f, label) or _is_subsequence(f, label.zfill(2)) for f in found):
        return (f"PDF page {page_no}: footer reads {found}, config says {label!r}: "
                f"footer is missing digits in the text layer (config kept)")
    return f"PDF page {page_no}: footer reads {found}, config says {label!r}: check page_labels"


def _is_heading(line: _Line, body_size: float, pdf_cfg) -> bool:
    return (line.bold
            and line.size >= body_size + pdf_cfg["heading_min_size_gap"]
            and len(line.text) <= pdf_cfg["heading_max_chars"]
            and re.search(r"[A-Za-z]", line.text) is not None)


def _numeric(s: str) -> bool:
    return re.search(r"\d", s) is not None and re.search(r"[A-Za-z]", s) is None


def _is_table_heavy(text: str, table_cfg) -> bool:
    lines = [ln for ln in text.split("\n") if ln.strip()]
    tokens = text.split()
    if not tokens:
        return False
    line_share = sum(1 for ln in lines if _numeric(ln)) / len(lines)
    token_share = sum(1 for t in tokens if _numeric(t)) / len(tokens)
    return line_share >= table_cfg["numeric_line_share"] or token_share >= table_cfg["numeric_token_share"]


def _split_lines(lines, max_chars, overlap_chars):
    """Cut a list of lines into chunks (lists of lines) of about max_chars, with overlap."""
    chunks, current, size = [], [], 0
    for line in lines:
        if current and size + len(line) + 1 > max_chars:
            chunks.append(current)
            carry, carried = [], 0
            for prev in reversed(current):
                if carried + len(prev) + 1 > overlap_chars:
                    break
                carry.insert(0, prev)
                carried += len(prev) + 1
            current, size = carry, carried
        current.append(line)
        size += len(line) + 1
    if current:
        chunks.append(current)
    return chunks


def _part_chunks(part: _Part, section: str, body_size, cfg):
    """Chunks for one printed page. Returns (chunks, section at the end of the page)."""
    pdf_cfg, chunk_cfg = cfg["pdf"], cfg["chunking"]
    # Group lines into segments, one per heading.
    segments = []          # [section, starts_with_heading, [line texts]]
    for line in part.lines:
        if _is_heading(line, body_size, pdf_cfg):
            if segments and segments[-1][1] and segments[-1][3]:
                # Heading line directly after another heading: a heading over two lines.
                seg = segments[-1]
                seg[0] = f"{seg[0]} {line.text}"
                seg[2].append(line.text)
                continue
            section = line.text
            segments.append([section, True, [line.text], True])
            continue
        if not segments:
            segments.append([section, False, [], False])
        segments[-1][2].append(line.text)
        segments[-1][3] = False   # body text seen: the next heading starts a new segment

    chunks = []
    for seg_section, starts_with_heading, lines, _ in segments:
        for i, piece in enumerate(_split_lines(lines, chunk_cfg["max_chars"], chunk_cfg["overlap_chars"])):
            text = "\n".join(piece)
            chunks.append(Chunk(
                text=text, page=part.page, page_end=part.page, page_label=part.label,
                page_label_end=part.label, section=seg_section,
                is_table_heavy=_is_table_heavy(text, cfg["tables"]),
                starts_with_heading=starts_with_heading and i == 0,
            ))
        section = seg_section
    return chunks, section


def extract_chunks(pdf_path, page_labels=None, settings=None) -> ExtractResult:
    cfg = settings or load_ingest_config()
    pdf_cfg = cfg["pdf"]
    labels = parse_page_labels(page_labels)
    warnings = []

    parts = []
    with pymupdf.open(pdf_path) as doc:
        n_pages = doc.page_count
        for index in range(n_pages):
            page, page_no = doc[index], index + 1
            rect = page.rect
            page_labels_here = labels.get(page_no, [])
            if len(page_labels_here) == 2:
                mid = rect.x0 + rect.width / 2
                clips = [pymupdf.Rect(rect.x0, rect.y0, mid, rect.y1), pymupdf.Rect(mid, rect.y0, rect.x1, rect.y1)]
            else:
                clips = [rect]
            for k, clip in enumerate(clips):
                label = page_labels_here[k] if page_labels_here else ""
                if label:
                    w = _check_label(page_no, label, _page_numbers(page, clip, pdf_cfg["footer_band"],
                                                                  pdf_cfg["header_band"]))
                    if w:
                        warnings.append(w)
                lines = _read_lines(page, clip, pdf_cfg["header_band"], pdf_cfg["footer_band"])
                parts.append(_Part(page=page_no, label=label, lines=lines))

    # Body text size = the most common font size, weighted by characters.
    sizes = Counter()
    for part in parts:
        for line in part.lines:
            sizes[line.size] += len(line.text)
    body_size = sizes.most_common(1)[0][0] if sizes else 0.0

    per_part, section = [], ""
    for part in parts:
        chunks, section = _part_chunks(part, section, body_size, cfg)
        per_part.append(chunks)

    # A very short piece at the end of a page joins the next page's first chunk,
    # unless that chunk starts with a new heading.
    min_chars = cfg["chunking"]["min_chars"]
    for i in range(len(per_part) - 1):
        here, nxt = per_part[i], per_part[i + 1]
        if not here or not nxt:
            continue
        tail, head = here[-1], nxt[0]
        if len(tail.text) < min_chars and not head.starts_with_heading and head.section == tail.section:
            text = f"{tail.text}\n{head.text}"
            nxt[0] = Chunk(
                text=text, page=tail.page, page_end=head.page_end, page_label=tail.page_label,
                page_label_end=head.page_label_end, section=tail.section,
                is_table_heavy=_is_table_heavy(text, cfg["tables"]),
                starts_with_heading=tail.starts_with_heading,
            )
            here.pop()

    chunks = [c for part_chunks in per_part for c in part_chunks if c.text.strip()]
    return ExtractResult(chunks=chunks, label_warnings=warnings, n_pages=n_pages)
