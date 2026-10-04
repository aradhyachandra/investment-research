"""Claims in an answer, read from its text the same way for every system (full, verifier off,
naive RAG), so the systems are scored alike. Deterministic, no LLM.

Numeric claim: a number written in the answer text, with the unit written next to it
(INR_CRORE, INR_MILLION, INR_LAKH_CRORE, PERCENT, INR_PER_SHARE, INR_ANY = rupees with no scale, USD,
UNSUPPORTED = some other word, None = no unit) and the period labels of its sentence. Not
claims: page numbers ("page 167"), citation ids ("[fact:12]"), dates, period labels and bare
years (1900-2100). Number reading reuses the verifier's tokenizer (verifier.py), so a figure is
read the same way when it is checked and when it is scored.

Each numeric claim gets:
  supported  the figure is a tool number (value as displayed, unit fits) or appears in the text of
             a passage or a code-written note the system was given. Otherwise it has no evidence.
  cited      the (source_id, page) evidence behind it: the tool numbers it matches (a ratio's input
             facts count), plus ids cited in brackets in its sentence; if neither, the answer's
             cited passages. A DCF figure has no page (the run is the evidence).

Qualitative claim: a sentence of an LLM-written, non-refused answer with no numeric claim and at
least `min_words` words. Its cited passages are the chunk ids in its brackets, else the answer's
cited passages. Template answers (code-written quotes) have none. These are labelled by hand
(qualitative.py), never graded here.
"""
import re
from decimal import Decimal

from pydantic import BaseModel

from erp.agent.answer_schema import Answer
from erp.agent.llm import load_agent_config
from erp.agent.tools import Evidence, ToolResult
from erp.agent.verifier import (CITE_RE, ID_RE, PAGE_BEFORE, SENTENCE_SPLIT, _numbers_in, _same_number, _Token,
                                _tokens, _unit_fits, _value_matches)

MIN_WORDS = 4                       # shorter sentences are not treated as qualitative claims
LAKH_CRORE_AFTER = re.compile(r"\s+crores?\b", re.I)
USD_BEFORE = re.compile(r"(?:USD|US\$|\$)", re.I)


class CitedPage(BaseModel):
    evidence_id: str
    kind: str
    source_id: int
    page: int
    page_end: int


class NumericClaim(BaseModel):
    text: str                       # as written, e.g. "INR 267,021 crore"
    value: str                      # decimal string as written, e.g. "267021", "18.43"
    decimals: int
    unit: str | None
    sentence: str
    periods: list[str]              # period labels in the claim's sentence
    supported: bool = False
    tool_number_ids: list[str] = []
    cited: list[CitedPage] = []


class QualitativeClaim(BaseModel):
    text: str
    cited: list[CitedPage] = []
    cited_by: str = "none"          # "sentence" (brackets), "answer" (answer-level), or "none"


def _sentences(text: str) -> list[str]:
    return [s for s in SENTENCE_SPLIT.split(text or "") if s and s.strip()]


def _plain(sentence: str) -> str:
    """The sentence with bracketed citation ids blanked out (same length, so offsets hold)."""
    return CITE_RE.sub(lambda m: " " * len(m.group(0)) if ID_RE.search(m.group(1)) else m.group(0), sentence)


def _bracket_ids(sentence: str) -> list[str]:
    return list(dict.fromkeys(i.split("#")[0] for b in CITE_RE.findall(sentence) for i in ID_RE.findall(b)))


def _claims_with_tokens(text: str) -> list[tuple[NumericClaim, _Token]]:
    out = []
    for sentence in _sentences(text):
        plain = _plain(sentence)
        tokens = _tokens(plain)
        periods = [t.period for t in tokens if t.kind == "period"]
        for t in tokens:
            if t.kind != "number" or PAGE_BEFORE.search(plain[:t.start]):
                continue
            if t.plain and 1900 <= t.value <= 2100:          # a bare year
                continue
            unit, shown = t.unit, t.text
            if USD_BEFORE.match(t.text):        # the tokenizer reads "million" as INR whatever the currency
                unit = "USD"
            after = LAKH_CRORE_AFTER.match(plain[t.end:])
            if t.unit == "UNSUPPORTED" and re.search(r"lakhs?$", t.text, re.I) and after:
                unit, shown = "INR_LAKH_CRORE", f"{t.text}{after.group(0)}"
            out.append((NumericClaim(text=shown.strip(), value=str(t.value), decimals=t.decimals, unit=unit,
                                     sentence=sentence.strip(), periods=periods), t))
    return out


def numeric_claims_in_text(text: str) -> list[NumericClaim]:
    return [c for c, _ in _claims_with_tokens(text)]


def _evidence_chain(eid: str, by_id: dict[str, Evidence], seen: set | None = None) -> list[Evidence]:
    seen = set() if seen is None else seen
    if eid in seen or eid not in by_id:
        return []
    seen.add(eid)
    out = [by_id[eid]]
    for i in by_id[eid].input_evidence_ids:
        out += _evidence_chain(i, by_id, seen)
    return out


def _pages(evidence: list[Evidence]) -> list[CitedPage]:
    out = {}
    for e in evidence:
        if e.source_id is not None and e.page is not None:
            out.setdefault(e.evidence_id, CitedPage(evidence_id=e.evidence_id, kind=e.kind, source_id=e.source_id,
                                                    page=e.page, page_end=e.page_end or e.page))
    return list(out.values())


def extract_claims(answer: Answer, cfg: dict | None = None) -> tuple[list[NumericClaim], list[QualitativeClaim]]:
    cfg = cfg or load_agent_config()
    decimals = cfg["display"]["decimals"]
    footer = " ".join(cfg["dcf_footer"].split())
    ok: list[ToolResult] = [r for r in answer.tool_results if r.ok]
    by_id = {e.evidence_id: e for r in ok for e in r.evidence}
    by_id.update({e.evidence_id: e for e in answer.citations})
    tool_numbers = list({n.number_id: n for r in ok for n in r.numbers}.values())
    passage_numbers = _numbers_in([p.text for r in ok for p in r.passages])
    note_numbers = _numbers_in([x for r in ok for x in r.notes] + [n.label for n in tool_numbers]
                               + [s for e in by_id.values() for s in (e.formula, e.source_title) if s])
    answer_chunks = [e for e in answer.citations if e.kind == "doc_chunk"]

    numeric = []
    for claim, tok in _claims_with_tokens(answer.answer_text):
        matches = [n for n in tool_numbers if _unit_fits(tok.unit, n.unit)
                   and _value_matches(tok, n, decimals.get(n.unit, 2))]
        if len(matches) > 1 and claim.periods:
            matches = [n for n in matches if n.period in claim.periods] or matches
        evidence = [e for n in matches for e in _evidence_chain(n.evidence_id, by_id)]
        evidence += [e for i in _bracket_ids(claim.sentence) for e in _evidence_chain(i, by_id)]
        if not evidence:
            evidence = answer_chunks
        claim.tool_number_ids = [n.number_id for n in matches]
        claim.supported = bool(matches) or any(_same_number(tok, o) for o in passage_numbers + note_numbers)
        claim.cited = _pages(evidence)
        numeric.append(claim)

    qualitative = []
    if not answer.refused and answer.composed_by == "llm":
        numeric_sentences = {c.sentence for c in numeric}
        for sentence in _sentences(answer.answer_text):
            s = sentence.strip()
            words = re.findall(r"[A-Za-z]+", _plain(s))
            if s in numeric_sentences or len(words) < MIN_WORDS or s in footer:
                continue
            ids = [i for i in _bracket_ids(s) if i in by_id]
            if ids:
                cited, how = _pages([e for i in ids for e in _evidence_chain(i, by_id)]), "sentence"
            else:
                cited, how = _pages(answer_chunks), ("answer" if answer_chunks else "none")
            qualitative.append(QualitativeClaim(text=s, cited=cited, cited_by=how if cited else "none"))
    return numeric, qualitative


def numeric_value(claim: NumericClaim) -> Decimal:
    return Decimal(claim.value)
