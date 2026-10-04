"""Answer verifier (M6, plan 8.4 and risks 5-6). Deterministic code, no LLM.

It reads the composed answer text and checks it against the tool results of the same turn:

1. Numeric grounding. Every number written in the text must be a tool number, allowing for
   formatting (267,021 = 2,67,021 = 267021; "INR", "Rs.", "₹") and rounding to fewer decimals
   than displayed (18.43% -> 18.4% or 18%). The unit written must fit (a crore figure written as
   "million" is a conversion, which the LLM may not do). Not figures: period labels (FY26,
   2025-26), dates (checked separately), citation ids. Page numbers must be pages of the
   evidence. A number found only in a passage's text is allowed with a warning (passages are
   filing text, not checked figures); a number found nowhere is an error.
2. Citations. Every evidence id the composer cites, in the text or in its id lists, must exist
   in the tool results, and a bracketed citation must support the figures in its sentence.
   `numbers_in_text` is the list of tool numbers the text actually says (so numbers_used matches
   the text, not the LLM's list).
3. Comparisons. A sentence that says a figure increased/decreased/rose/fell/was higher/lower
   needs both values in the tool results, and their order must match the word. "<figure> ...
   higher/lower than <figure>" orders the two figures as written (same kind of unit), and is
   not read as a direction of change. "X to Y",
   "increases to Y", "decreases to Y" are checked against the base or earlier value. A DCF
   sensitivity-grid value must be the cell for the WACC / terminal growth the sentence states.
4. Interpretive words ("stable", "strong") with no tool figure behind them: warnings only.

Errors make the loop throw the text away and use the code-written template answer.
"""
import json
import re
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from erp.agent.tools import ToolNumber, ToolResult


class VerifierIssue(BaseModel):
    check: str                          # e.g. number_unsupported, citation_unknown, comparison_unsupported
    severity: Literal["error", "warning"]
    span: str                           # the words in the answer the issue is about
    message: str


class VerifierReport(BaseModel):
    ok: bool                            # no errors (warnings allowed)
    issues: list[VerifierIssue] = []
    numbers_in_text: list[ToolNumber] = []   # tool numbers the text says, in order, each once

    @property
    def errors(self) -> list[VerifierIssue]:
        return [i for i in self.issues if i.severity == "error"]


# ---------- recognising things in text ----------

_MONTHS = {m: i + 1 for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
     "november", "december"])}
_MONTHS.update({m[:3]: i for m, i in list(_MONTHS.items())})
_MONTHS["sept"] = 9
_MON = r"(?P<mon>" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")\.?"

DATE_RES = [  # 2026-03-31, 31 March 2026, March 31, 2026, March 2026
    re.compile(r"\b(?P<y>\d{4})-(?P<m>\d{2})-(?P<d>\d{2})\b"),
    re.compile(r"\b(?P<d>\d{1,2})(?:st|nd|rd|th)?\s+" + _MON + r",?\s+(?P<y>\d{4})\b", re.I),
    re.compile(r"\b" + _MON + r"\s+(?P<d>\d{1,2})(?:st|nd|rd|th)?,?\s+(?P<y>\d{4})\b", re.I),
    re.compile(r"\b" + _MON + r",?\s+(?P<y>\d{4})\b", re.I),
]
PERIOD_RES = [  # Q1 FY27, FY 2025-26, FY26, FY2026, fiscal year 2025-26, fiscal 2026, 2025-26 -> a period label
    re.compile(r"\bQ(?P<q>[1-4])\s*(?:of\s+)?FY\s?'?(?P<y>\d{4}|\d{2})\b", re.I),
    re.compile(r"\bFY\s?'?\d{4}\s?[-–/]\s?(?P<y>\d{4}|\d{2})\b", re.I),
    re.compile(r"\bFY\s?'?(?P<y>\d{4}|\d{2})\b", re.I),
    re.compile(r"\b(?:fiscal|financial)(?:\s+year)?\s+\d{4}\s?[-–/]\s?(?P<y>\d{4}|\d{2})\b", re.I),
    re.compile(r"\b(?:fiscal|financial)(?:\s+year)?\s+(?P<y>\d{4})\b", re.I),
    re.compile(r"\b20\d{2}\s?[-–/]\s?(?P<y>20\d{2}|\d{2})\b"),
]
NUM_RE = re.compile(r"""
    (?<![\w.,/:#§-])
    (?P<sign>[-−]\s?)?
    (?P<cur>(?:INR|Rs\.?|₹|USD|US\$|\$)\s?)?
    (?P<num>\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d+(?:\.\d+)?)
    (?P<unit>\s?%|\s?per\s?cent\b|\s?percent\b|\s+crore\s+shares\b|\s?(?:crore|cr)\b
       |\s?(?:lakhs?|thousand|k|million|mn|billion|bn|trillion|x)\b)?
    (?P<ps>\s+per\s+share\b)?
""", re.X | re.I)
PAGE_BEFORE = re.compile(r"(?:\bpages?|\bp\.|\bpp\.)\s*$", re.I)
CITE_RE = re.compile(r"\[([^\[\]]*)\]")
ID_RE = re.compile(r"\b(?:fact|calc|dcf|chunk|period):[^\s,;\]]+")
SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'(₹])|\n+")
CLAUSE_SPLIT = re.compile(r";|,\s*(?:and|but|while|whereas|although|though)\b|\s(?:but|while|whereas|although|though)\s")

_UP = ["increase", "increased", "increases", "rise", "rises", "rose", "risen", "higher", "improved", "improves",
       "expanded", "climbed", "jumped", "surged", "up from", "went up", "goes up", "go up"]
_DOWN = ["decrease", "decreased", "decreases", "decline", "declined", "declines", "fall", "falls", "fell",
         "fallen", "lower", "dropped", "drops", "drop", "reduced", "shrank", "contracted", "dipped", "slipped",
         "down from", "went down", "goes down", "go down"]
_SAME = ["unchanged", "flat", "remained at", "remains at", "stayed at", "the same as"]
_UP_TO = _UP + ["grow", "grows", "grew", "grown", "moves up", "move up"]
_DOWN_TO = _DOWN + ["moves down", "move down"]


def _alt(words):
    """One regex alternative for a list of words or phrases, longest first, whole words."""
    phrases = sorted(words, key=len, reverse=True)
    return r"\b(?:" + "|".join(r"\s+".join(re.escape(w) for w in p.split()) for p in phrases) + r")\b"


DIR_RE = re.compile(rf"(?P<up>{_alt(_UP)})|(?P<down>{_alt(_DOWN)})|(?P<same>{_alt(_SAME)})|(?P<grew>\bgrew\b)", re.I)
TO_CLAIM_RE = re.compile(
    rf"(?:(?P<up>{_alt(_UP_TO)})|(?P<down>{_alt(_DOWN_TO)})|(?P<same>{_alt(_SAME)}))"
    r"(?:\s+(?!from\b)[^\s⟨]+){0,3}?\s+to\s+⟨N(?P<n>\d+)⟩", re.I)
THAN_FIGURE_RE = re.compile(r"\s+than\s+(?:[^\s⟨]+\s+){0,3}?⟨N(?P<n>\d+)⟩", re.I)
FROM_TO_RE = re.compile(r"\bfrom\s+⟨N(?P<a>\d+)⟩(?:\s+(?:in|for)\s+⟨P\d+⟩)?\s*,?\s+to\s+⟨N(?P<b>\d+)⟩", re.I)
ATTACHED_PERIOD = re.compile(r"^\s*,?\s*(?:in|for|during|as of|at the end of)\s+(?:the\s+)?$", re.I)


def _fy_label(y: str, q: str | None = None) -> str:
    fy = f"FY{int(y[-2:]):02d}"
    return f"Q{q} {fy}" if q else fy


def period_key(label: str):
    """Sort key for 'FY26' / 'Q1 FY27' (a full year sorts after its quarters); None if not a label."""
    m = re.fullmatch(r"(?:Q([1-4]) )?FY(\d{2})", label or "")
    return (int(m.group(2)), int(m.group(1)) if m.group(1) else 5) if m else None


def periods_in(text: str) -> list[str]:
    """Period labels mentioned in a text ('fiscal 2026' -> 'FY26'), in order."""
    return [t.period for t in _tokens(text) if t.kind == "period"]


def _prior_label(label: str) -> str | None:
    m = re.fullmatch(r"(Q[1-4] )?FY(\d{2})", label or "")
    return f"{m.group(1) or ''}FY{int(m.group(2)) - 1:02d}" if m else None


class _Token(BaseModel):
    kind: Literal["date", "period", "number"]
    start: int
    end: int
    text: str
    period: str | None = None           # period label for kind=period
    ymd: tuple | None = None            # (y, m, d or None) for kind=date
    value: Decimal | None = None        # numbers: as written (negative only if a minus sign is written)
    decimals: int = 0
    signed: bool = False
    unit: str | None = None             # PERCENT, INR_CRORE, ..., INR_ANY, UNSUPPORTED, or None
    plain: bool = False                 # no unit, currency, comma or decimals (could be a year)
    cands: list[ToolNumber] = []        # tool numbers it matches

    model_config = {"arbitrary_types_allowed": True}


def _unit_of(m) -> str | None:
    u = re.sub(r"\s+", " ", (m.group("unit") or "").strip().lower())
    if m.group("ps"):
        return "INR_PER_SHARE" if not u else "UNSUPPORTED"
    if u in ("%", "per cent", "percent"):
        return "PERCENT"
    if u == "crore shares":
        return "SHARES_CRORE"
    if u in ("crore", "cr"):
        return "INR_CRORE"
    if u in ("million", "mn"):
        return "INR_MILLION"
    if u:
        return "UNSUPPORTED"
    return "INR_ANY" if m.group("cur") else None


def _tokens(text: str) -> list[_Token]:
    """Dates, then periods, then numbers; each found on the text with earlier finds masked."""
    masked = text
    found = []

    def mask(s, e):
        nonlocal masked
        masked = masked[:s] + "§" * (e - s) + masked[e:]

    for rx in DATE_RES:
        for m in rx.finditer(masked):
            gd = m.groupdict()
            month = int(gd["m"]) if gd.get("m") else _MONTHS[gd["mon"].lower().rstrip(".")]
            found.append(_Token(kind="date", start=m.start(), end=m.end(), text=m.group(0),
                                ymd=(int(gd["y"]), month, int(gd["d"]) if gd.get("d") else None)))
            mask(m.start(), m.end())
    for rx in PERIOD_RES:
        for m in rx.finditer(masked):
            found.append(_Token(kind="period", start=m.start(), end=m.end(), text=m.group(0),
                                period=_fy_label(m.group("y"), m.groupdict().get("q"))))
            mask(m.start(), m.end())
    for m in NUM_RE.finditer(masked):
        unit = _unit_of(m)
        end = m.end()
        if unit is None and end < len(masked) and masked[end].isalpha():
            unit = "UNSUPPORTED"                     # glued to letters, e.g. "20M"
        raw = m.group("num")
        found.append(_Token(kind="number", start=m.start(), end=end, text=text[m.start():end].strip(),
                            value=Decimal(raw.replace(",", "")) * (-1 if m.group("sign") else 1),
                            decimals=len(raw.split(".")[1]) if "." in raw else 0, signed=bool(m.group("sign")),
                            unit=unit, plain=unit is None and "," not in raw and "." not in raw))
    return sorted(found, key=lambda t: t.start)


# ---------- matching numbers ----------

def _shown(value: float, decimals: int) -> Decimal:
    return Decimal(f"{value:.{decimals}f}")


def _value_matches(tok: _Token, n: ToolNumber, shown_decimals: int) -> bool:
    v = n.value if tok.signed else abs(n.value)
    if tok.decimals <= shown_decimals:
        return _shown(v, tok.decimals) == tok.value
    # More decimals than displayed: only trailing zeros are allowed (18.430% for 18.43%).
    return tok.value == tok.value.quantize(Decimal(1).scaleb(-shown_decimals)) and _shown(v, shown_decimals) == tok.value


def _unit_fits(tok_unit: str | None, unit: str) -> bool:
    if tok_unit is None:
        return True
    if tok_unit == "INR_ANY":
        return unit.startswith("INR")
    return tok_unit == unit


def _numbers_in(strings) -> list[_Token]:
    return [t for s in strings for t in _tokens(s) if t.kind == "number"]


def _units_compatible(a: str | None, b: str | None) -> bool:
    """Two written units that can describe the same kind of figure (no unit written fits any)."""
    units = {a, b}
    return None in units or len(units) == 1 or ("INR_ANY" in units and all(u.startswith("INR") for u in units))


def _same_number(tok: _Token, other: _Token) -> bool:
    """Two numbers found in text (answer vs passage or note) that say the same thing."""
    return abs(tok.value) == abs(other.value) and _units_compatible(tok.unit, other.unit)


# ---------- the verifier ----------

class _Context:
    def __init__(self, results: list[ToolResult], cfg: dict):
        self.cfg = cfg
        self.decimals = cfg["display"]["decimals"]
        self.numbers = list({n.number_id: n for r in results for n in r.numbers}.values())
        self.evidence = {e.evidence_id: e for r in results for e in r.evidence}
        # A calc supports its input facts; a fact cited for a ratio's input is fine too.
        self.supports = {eid: {eid} for eid in self.evidence}
        for e in self.evidence.values():
            for i in e.input_evidence_ids:
                self.supports.setdefault(i, {i}).add(e.evidence_id)
        self.passages = [p.text for r in results for p in r.passages]
        self.passage_numbers = _numbers_in(self.passages)
        tool_strings = [x for r in results for x in r.notes] + [n.label for n in self.numbers] + \
            [s for e in self.evidence.values() for s in (e.formula, e.source_title) if s] + \
            [p.section for r in results for p in r.passages]
        self.note_numbers = _numbers_in(tool_strings)
        corpus = tool_strings + self.passages + [json.dumps(r.detail, default=str) for r in results if r.detail]
        self.dates = {t.ymd for s in corpus for t in _tokens(s) if t.kind == "date"}
        self.years = {int(y) for s in corpus for y in re.findall(r"\b((?:19|20)\d{2})\b", s)}
        for n in self.numbers:
            if period_key(n.period or ""):
                fy = 2000 + period_key(n.period)[0]
                self.years |= {fy, fy - 1}
        self.pages = set()
        for e in self.evidence.values():
            if e.page:
                self.pages |= set(range(e.page, (e.page_end or e.page) + 1))
            self.pages |= {int(x) for x in re.findall(r"\d+", e.page_label or "")}
        self.aliases = self._aliases()

    def _aliases(self) -> dict[str, set]:
        out: dict[str, set] = {}
        extra = self.cfg.get("verifier", {}).get("quantity_aliases", {})
        for n in (n for n in self.numbers if n.quantity):
            names = {n.quantity.replace("_", " ")} | set(extra.get(n.quantity, []))
            if not n.variant:
                names.add(n.label.split(",")[0].split(" (")[0])
            for a in names:
                out.setdefault(a.lower(), set()).add(n.quantity)
        for q, words in extra.items():         # a named quantity with no tool numbers is still a quantity
            for a in words:
                out.setdefault(a.lower(), set()).add(q)
        return out

    def match(self, tok: _Token) -> list[ToolNumber]:
        return [n for n in self.numbers if _unit_fits(tok.unit, n.unit)
                and _value_matches(tok, n, self.decimals.get(n.unit, 2))]

    def values(self, quantities: set) -> dict[str, ToolNumber]:
        """period label -> the (non-variant) tool number, for the first quantity that has figures."""
        for q in sorted(quantities):
            by_period = {n.period: n for n in self.numbers if n.quantity == q and not n.variant and n.period}
            if by_period:
                return by_period
        return {}

    def shown(self, n: ToolNumber) -> Decimal:
        return _shown(n.value, self.decimals.get(n.unit, 2))


def _direction(a: Decimal, b: Decimal) -> str:
    return "up" if b > a else "down" if b < a else "same"


def verify_answer(text: str, results: list[ToolResult], *, cfg: dict, listed_number_ids=(),
                  cited_ids=()) -> VerifierReport:
    ctx = _Context([r for r in results if r.ok], cfg)
    issues: list[VerifierIssue] = []

    def issue(check, severity, span, message):
        issues.append(VerifierIssue(check=check, severity=severity, span=span, message=message))

    all_ids = {n.number_id for n in ctx.numbers}
    for i in listed_number_ids:
        if i not in all_ids:
            issue("number_id_unknown", "error", i, f"composer listed number id {i} that is not in the tool results")
    for i in cited_ids:
        if i not in ctx.evidence:
            issue("citation_unknown", "error", i, f"composer cited {i}, which is not in the tool results")

    in_text: dict[str, ToolNumber] = {}
    uncited = []
    for sentence in (s for s in SENTENCE_SPLIT.split(text) if s and s.strip()):
        cited = [i.split("#")[0] for b in CITE_RE.findall(sentence) for i in ID_RE.findall(b)]
        for i in dict.fromkeys(cited):
            if i not in ctx.evidence:
                issue("citation_unknown", "error", f"[{i}]", f"the text cites {i}, which is not in the tool results")
        known_cited = {i for i in cited if i in ctx.evidence}
        plain = CITE_RE.sub(lambda m: " " * len(m.group(0)) if ID_RE.search(m.group(1)) else m.group(0), sentence)
        tokens = _tokens(plain)
        grounded = _ground(plain, tokens, ctx, issue)
        clauses = _clauses(plain, tokens)
        for clause in clauses:
            _check_grid_values(clause.numbers, grounded, ctx, issue)
        grounded = [t for t in grounded if t.cands]
        for t in grounded:
            best = sorted(t.cands, key=lambda n: (n.number_id not in listed_number_ids,
                                                  not (ctx.supports.get(n.evidence_id, set()) & known_cited),
                                                  n.variant))[0]
            in_text.setdefault(best.number_id, best)
            if known_cited and not any(ctx.supports.get(n.evidence_id, set()) & known_cited for n in t.cands):
                issue("citation_mismatch", "error", t.text, f"{t.text} is cited to {sorted(known_cited)}, which do "
                      f"not contain it (it comes from {sorted({n.evidence_id for n in t.cands})})")
        if grounded and not known_cited:
            uncited.append(sentence.strip()[:80])
        for clause in clauses:
            _check_comparisons(clause, ctx, issue)
        if not grounded:
            for w in ctx.cfg.get("verifier", {}).get("interpretive_words", []):
                for m in re.finditer(rf"\b{re.escape(w)}\b", plain, re.I):
                    if not any(re.search(rf"\b{re.escape(w)}\b", p, re.I) for p in ctx.passages):
                        issue("interpretive_word", "warning", m.group(0),
                              f"'{m.group(0)}' judges rather than reports, and no tool figure backs it")

    if uncited:   # citations are attached by code anyway; this only reports that the prose lacks [ids]
        issue("citation_missing", "warning", uncited[0], f"{len(uncited)} sentence(s) with a figure have no [id] citation")
    listed = [i for i in dict.fromkeys(listed_number_ids) if i in all_ids]
    unused = [i for i in listed if i not in in_text]
    if unused:
        issue("numbers_used_not_in_text", "warning", ", ".join(unused),
              f"composer listed numbers it did not write, dropped: {unused}")
    missing = [i for i in in_text if i not in listed]
    if missing:
        issue("numbers_used_missing", "warning", ", ".join(missing),
              f"composer did not list the numbers it wrote: {missing}; added")
    issues = list({(i.check, i.span, i.message): i for i in issues}.values())
    return VerifierReport(ok=not any(i.severity == "error" for i in issues), issues=issues,
                          numbers_in_text=list(in_text.values()))


def _ground(plain: str, tokens: list[_Token], ctx: _Context, issue) -> list[_Token]:
    """Check dates and numbers in one sentence. Returns the number tokens matched to tool numbers."""
    grounded = []
    for k, t in enumerate(tokens):
        if t.kind == "date":
            y, m, d = t.ymd
            if not any(k2[0] == y and k2[1] == m and (d is None or k2[2] in (d, None)) for k2 in ctx.dates):
                issue("date_unknown", "error", t.text, f"the date '{t.text}' is not in the tool results")
            continue
        if t.kind != "number":
            continue
        if PAGE_BEFORE.search(plain[:t.start]):
            if t.decimals or t.unit or int(abs(t.value)) not in ctx.pages:
                issue("page_unknown", "error", t.text, f"page {t.text} is not a page of the cited evidence")
            continue
        t.cands = ctx.match(t)
        nxt = tokens[k + 1] if k + 1 < len(tokens) else None
        if t.cands and nxt is not None and nxt.kind == "period" and ATTACHED_PERIOD.match(plain[t.end:nxt.start]):
            dated = [n for n in t.cands if period_key(n.period or "")]
            if dated:
                t.cands = [n for n in t.cands if n.period == nxt.period]
                if not t.cands:
                    issue("period_mismatch", "error", f"{t.text} {plain[t.end:nxt.end].strip()}",
                          f"{t.text} is the figure for {sorted({n.period for n in dated})}, not {nxt.period}")
                    continue
        if t.cands:
            grounded.append(t)
            continue
        if t.plain and 1900 <= t.value <= 2100:
            if int(t.value) not in ctx.years:
                issue("year_unknown", "warning", t.text, f"the year {t.text} is not in the tool results")
            continue
        if any(_same_number(t, o) and o.decimals == t.decimals for o in ctx.note_numbers):
            continue                                   # written by code in the notes or labels
        if any(_same_number(t, o) for o in ctx.passage_numbers):
            issue("passage_number", "warning", t.text, f"{t.text} appears only in passage text, not as a checked figure")
            continue
        near = [n.display for n in ctx.numbers if _value_matches(t, n, ctx.decimals.get(n.unit, 2))]
        hint = f" (same digits as {near[0]}, but the unit differs)" if near else ""
        issue("number_unsupported", "error", t.text, f"{t.text} is not a number in the tool results{hint}")
    return grounded


# ---------- sensitivity-grid values ----------

def _cell_fits(n: ToolNumber, scope: list[_Token], ctx: _Context) -> bool:
    """A grid value fits if each of its conditions (WACC, terminal growth) is the value the text
    states for it, or, if the text states none, the scenario's own (base) value."""
    for q, v in n.conditions.items():
        shown = _shown(v, ctx.decimals.get("PERCENT", 2))
        stated = {ctx.shown(c) for t in scope for c in t.cands if c.quantity == q}
        if stated:
            if shown not in stated:
                return False
            continue
        base = next((b for b in ctx.numbers if b.quantity == q and not b.variant and b.evidence_id == n.evidence_id), None)
        if base is None or ctx.shown(base) != shown:
            return False
    return True


def _check_grid_values(clause_numbers: list[_Token], sentence_numbers: list[_Token], ctx: _Context, issue) -> None:
    """'If WACC rises to 13.92%, the value falls to X': X must be the cell for WACC 13.92% at the
    base terminal growth, not a cell where growth changed too. Checked per clause, then per sentence."""
    for t in clause_numbers:
        if not t.cands or not all(n.variant and n.conditions for n in t.cands):
            continue
        fits = [n for n in t.cands if _cell_fits(n, clause_numbers, ctx) or _cell_fits(n, sentence_numbers, ctx)]
        if fits:
            t.cands = fits
            continue
        where = "; ".join(n.label.replace("Value per share at ", "") for n in t.cands)
        issue("sensitivity_mismatch", "error", t.text, f"{t.text} is the grid value at {where}, which is not "
              f"what the sentence states (an unstated input stays at the scenario's own value)")
        t.cands = []


# ---------- comparison claims ----------

class _Clause(BaseModel):
    text: str                                # with tokens replaced by ⟨N0⟩ / ⟨P0⟩ / ⟨D0⟩
    numbers: list[_Token]
    periods: list[_Token]

    model_config = {"arbitrary_types_allowed": True}


def _clauses(plain: str, tokens: list[_Token]) -> list[_Clause]:
    parts, pos = [], 0
    for m in list(CLAUSE_SPLIT.finditer(plain)) + [None]:
        end = m.start() if m else len(plain)
        parts.append((pos, end))
        pos = m.end() if m else pos
    out = []
    for s, e in parts:
        inner = [t for t in tokens if s <= t.start and t.end <= e]
        text, cur, nums, pers = "", s, [], []
        for t in inner:
            text += plain[cur:t.start]
            if t.kind == "number":
                text += f"⟨N{len(nums)}⟩"
                nums.append(t)
            elif t.kind == "period":
                text += f"⟨P{len(pers)}⟩"
                pers.append(t)
            else:
                text += "⟨D⟩"
            cur = t.end
        text += plain[cur:e]
        out.append(_Clause(text=text, numbers=nums, periods=pers))
    return out


def _named_quantities(clause: _Clause, ctx: _Context, before: int, after: int = 0) -> set:
    """Quantities named in the clause, nearest before position `before` (but not before `after`);
    if none, the first one named after it. Empty if the clause names none."""
    if not ctx.aliases:
        return set()
    rx = re.compile(_alt(ctx.aliases), re.I)
    hits = [(m.start(), ctx.aliases[re.sub(r"\s+", " ", m.group(0).lower())]) for m in rx.finditer(clause.text)]
    earlier = [h for h in hits if after <= h[0] < before]
    if earlier:
        return earlier[-1][1]
    later = [h for h in hits if h[0] >= before]
    return later[0][1] if later and after == 0 else set()


def _check_comparisons(clause: _Clause, ctx: _Context, issue) -> None:
    consumed = []          # spans of direction words already checked
    text = clause.text

    def label(direction):
        return {"up": "an increase", "down": "a decrease", "same": "no change"}[direction]

    # "from X to Y" with two figures
    for m in FROM_TO_RE.finditer(text):
        a, b = clause.numbers[int(m.group("a"))], clause.numbers[int(m.group("b"))]
        verbs = [d for d in DIR_RE.finditer(text[:m.start()])]
        if not (a.cands and b.cands) or not verbs:
            continue
        v = verbs[-1]
        consumed.append(v.span())
        said = "up" if (v.group("up") or v.group("grew")) else "down" if v.group("down") else "same"
        actual = _direction(abs(a.value), abs(b.value))
        if said != actual:
            periods = {n.period for n in a.cands + b.cands if period_key(n.period or "")}
            check = "comparison_wrong_direction" if len(periods) > 1 else "change_contradicts"
            issue(check, "error", f"{v.group(0)} from {a.text} to {b.text}",
                  f"says {label(said)} from {a.text} to {b.text}, which is {label(actual)}")

    # "<verb> ... to Y"
    previous_end = 0       # "if growth falls to 3%, it falls to X": the second claim is not about growth
    for m in TO_CLAIM_RE.finditer(text):
        if any(s <= m.start() < e for s, e in consumed):
            continue
        consumed.append((m.start(), m.start() + len(m.group(0).split()[0])))
        after, previous_end = previous_end, m.end()
        said = "up" if m.group("up") else "down" if m.group("down") else "same"
        y = clause.numbers[int(m.group("n"))]
        if not y.cands:
            continue                              # already an error from grounding
        span = m.group(0).replace(f"⟨N{m.group('n')}⟩", y.text)
        qs = _named_quantities(clause, ctx, m.start(), after) or {n.quantity for n in y.cands}
        ys = [n for n in y.cands if n.quantity in qs]
        if not ys:
            issue("comparison_unsupported", "error", span,
                  f"no figure for {sorted(qs)} in the tool results equals {y.text}")
            continue
        has_variants = any(n.variant and n.quantity in qs for n in ctx.numbers)
        if has_variants and any(not n.variant for n in ys):
            if said != "same":
                issue("change_contradicts", "error", span, f"says {label(said)} to {y.text}, but {y.text} is the "
                      f"scenario's own {ys[0].quantity.replace('_', ' ')} (unchanged)")
            continue
        if all(n.variant for n in ys):
            base = next((n for n in ctx.numbers if n.quantity == ys[0].quantity and not n.variant
                         and n.evidence_id == ys[0].evidence_id), None)
            if base is None:
                issue("comparison_unsupported", "error", span, f"no base value to compare {y.text} with")
                continue
            actual = _direction(ctx.shown(base), ctx.shown(ys[0]))
            if said != actual:
                issue("change_contradicts", "error", span, f"says {label(said)} to {y.text}; the base case is "
                      f"{base.display}, so it is {label(actual)}")
            continue
        n = ys[0]
        earlier = ctx.values({n.quantity}).get(_prior_label(n.period))
        if earlier is None:
            issue("comparison_unsupported", "error", span, f"says {label(said)} to {y.text} ({n.period}), but no "
                  f"earlier {n.quantity.replace('_', ' ')} figure is in the tool results")
            continue
        actual = _direction(ctx.shown(earlier), ctx.shown(n))
        if said != actual:
            issue("comparison_wrong_direction", "error", span, f"says {label(said)} to {n.display} in {n.period}; "
                  f"{earlier.period} was {earlier.display}, so it is {label(actual)}")

    # "<figure> ... lower/higher than <figure>": an ordering of two written figures, not a change.
    # (A growth rate of 4.58% can be "lower than" a 10% figure without anything having fallen; read
    # as a change, the positive growth rate made "lower" look wrong: the EV-F01 false rejection.)
    for v in DIR_RE.finditer(text):
        if any(s <= v.start() < e for s, e in consumed):
            continue
        m = THAN_FIGURE_RE.match(text, v.end())
        before = re.findall(r"⟨N(\d+)⟩", text[:v.start()])
        if not m or not before:
            continue
        consumed.append(v.span())
        a, b = clause.numbers[int(before[-1])], clause.numbers[int(m.group("n"))]
        said = "up" if v.group("up") else "down" if v.group("down") else "same"
        span = f"{a.text} ... {v.group(0)} than {b.text}"
        if not _units_compatible(a.unit, b.unit):
            issue("comparison_unsupported", "error", span, f"compares {a.text} with {b.text}, which are not the "
                  f"same kind of figure")
            continue
        actual = _direction(b.value, a.value)
        if said != actual:
            issue("comparison_wrong_direction", "error", span, f"says {a.text} is {v.group(0)} than {b.text}, "
                  f"which is not so")

    # any other direction word: "net margin decreased from FY25 to FY26", "revenue grew 4.58%"
    for v in DIR_RE.finditer(text):
        if any(s <= v.start() < e for s, e in consumed):
            continue
        said = "up" if (v.group("up") or v.group("grew")) else "down" if v.group("down") else "same"
        changes = [t for t in clause.numbers if any(n.measures_change for n in t.cands)]
        if changes:
            t = changes[0]
            n = next(n for n in t.cands if n.measures_change)
            actual = "up" if n.value > 0 else "down" if n.value < 0 else "same"
            if said != actual:
                issue("comparison_wrong_direction", "error", f"{v.group(0)} {t.text}",
                      f"says {label(said)}, but {n.label} is {n.display}")
            continue
        qs = _named_quantities(clause, ctx, v.start()) or \
            {n.quantity for t in clause.numbers for n in t.cands if not n.variant}
        periods = list(dict.fromkeys(p.period for p in clause.periods if period_key(p.period)))
        span = re.sub(r"⟨[NPD]\d*⟩", "…", text.strip())[:120]
        if not qs:
            if len(periods) >= 2:
                issue("comparison_unsupported", "error", span,
                      f"compares {periods[0]} and {periods[1]} without a figure from the tools")
            continue
        if any(n.variant and n.quantity in qs for n in ctx.numbers) and not periods:
            continue      # a sensitivity grid is shown; the grid itself backs "value falls as WACC rises" (TO VERIFY)
        values = ctx.values(qs)
        than = text.lower().find(" than ", v.start())
        if than != -1 and periods:
            subj = [p.period for p in clause.periods if text.find(f"⟨P{clause.periods.index(p)}⟩") < than]
            comp = [p.period for p in clause.periods if text.find(f"⟨P{clause.periods.index(p)}⟩") > than]
            pair = (comp[0], subj[0]) if subj and comp else None
        elif len(periods) >= 2:
            ordered = sorted(periods, key=period_key)
            pair = (ordered[0], ordered[-1])
        elif len(periods) == 1:
            pair = (_prior_label(periods[0]), periods[0])
        else:
            ordered = sorted(values, key=lambda p: period_key(p) or (0, 0))
            pair = (ordered[-2], ordered[-1]) if len(ordered) >= 2 else None
        name = sorted(qs)[0].replace("_", " ")
        if pair is None or pair[0] not in values or pair[1] not in values:
            have = sorted(values) or "none"
            issue("comparison_unsupported", "error", span, f"'{v.group(0)}' compares {name} across periods "
                  f"{list(pair) if pair else '(unclear)'}, but the tool results have {name} for: {have}")
            continue
        old, new = values[pair[0]], values[pair[1]]
        actual = _direction(ctx.shown(old), ctx.shown(new))
        if said != actual:
            issue("comparison_wrong_direction", "error", span, f"says {label(said)} ('{v.group(0)}'), but {name} "
                  f"was {old.display} in {pair[0]} and {new.display} in {pair[1]}: {label(actual)}")
