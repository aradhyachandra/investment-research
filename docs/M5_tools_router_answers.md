# M5: From a question to a sourced answer (plain-language note)

Up to M4 the project had four separate tools: look up a stored figure, compute a ratio, run the
DCF, search the annual report. Each worked on its own, with no LLM. M5 connects them to a
question typed in plain English and returns a structured answer where every figure says where
it came from.

The LLM gets two narrow jobs: **choose** the tool, and **write** the sentence. It never does
the arithmetic in between, and it never chooses which numbers are true.

## 1. Choosing the model (P0.6)

The app's LLM runs locally through Ollama (no API, no key). On an 8 GB MacBook Air only small
models fit, so three 3-4 billion parameter models were compared: llama3.2, qwen2.5:3b and phi4-mini.

Two tests:
- A toy test (5 questions about a made-up company) to see whether each model can produce valid
  JSON and pick tools at all.
- The real router on 20 practice questions, scoring whether it picked the right tools with the
  right arguments.

**qwen2.5:3b won**: it routed all 20 correctly once DCF scenario names were known, never refused
a normal question, refused all three out-of-scope ones, and used the least memory. llama3.2
"answered" a question comparing TCS with Infosys by looking up TCS revenue, which is the kind of
mistake that matters most. Details and caveats are in NOTES.md. The biggest caveat: the practice
questions were written by Claude and the prompt was tuned on them, so these scores are a
plumbing check, not a result.

The model name lives in `config/agent.yaml`. Every LLM call goes through one function,
`call_llm` (`src/erp/agent/llm.py`), so swapping models is a one-line config change.

## 2. One shape for every tool (`src/erp/agent/tools.py`)

The four tools returned different things (a fact, a ratio, a DCF run, a list of chunks). The
tool layer wraps each so they all return the same `ToolResult`:
- **numbers**: each figure with its value, unit, period, basis, and a **display string** that
  code has already formatted ("INR 267,021 crore", "18.43%"). The LLM copies this string; it never
  rounds or converts. DCF rates are stored as decimals (0.12) and code turns them into "12.00%".
- **evidence**: where each figure comes from, with an **evidence ID** pointing back into a store:
  `fact:12` (a row in SQLite), `calc:3` (a computed ratio, which lists the facts it used),
  `dcf:1` (a stored DCF run), `chunk:...` (a passage in ChromaDB with its PDF page).
- **passages**: text from the annual report, for "what does the report say" questions.
- **error**: if the tool could not answer (no FY22 data, no DCF assumptions file), it says why.
  A missing figure is reported, never guessed.

Each tool also has a typed input (e.g. `metric_id`, `period`, `basis`), checked before it runs.

## 3. The two-step router (`router.py`, `loop.py`)

**Step 1: route.** The LLM sees the question and a fixed menu: the four tools, the metric names,
the ratio names, the periods that exist in the database, the DCF scenario names. Its reply must
be JSON matching a schema in which those menus are the only allowed values (Ollama enforces
this). So it can pick "revenue_from_operations, FY26", but it cannot invent "share_price" or
"FY30". It can also say "refuse", with a reason: personal investment advice, a share-price
forecast, another company, or data we don't have.

Two things made the small models work (both found by testing, see NOTES.md):
- a few **worked examples** in the prompt (different from the practice questions), and
- asking for the **list of calls first** and the question type second. When the model had to
  decide the type first, it labelled almost everything "out of scope" (5 of 20 right; after the
  change 16-20 of 20).

**Step 2: run the tools.** Plain Python runs every call the router asked for. No LLM here.

**Step 3: write the answer.** The LLM gets the question plus an "evidence sheet": the numbers
(with their display strings and IDs), the passages, notes (e.g. "this figure has not been checked
by a human yet"), and anything that failed. It must reply with the answer text plus the list of
number IDs and evidence IDs it used, again chosen from menus of the IDs it was given.

## 4. The Answer object (`answer_schema.py`)

Every answer has:
- `answer_text`: the sentence(s) for the reader.
- `numbers_used`: each figure copied from a tool result (never read back out of the LLM's text),
  each pointing at an evidence ID.
- `citations`: the evidence behind those numbers. For a ratio this includes the ratio's formula
  and the facts it used, so you can follow 18.43% back to PDF page 167.
- `refused` + `refusal_reason`.
- `limitations` (unverified figures, failed lookups, failed DCF checks), `warnings` (what code had
  to correct in the LLM's reply), the route, the model name, and a disclaimer.

## 5. Where code overrules the LLM

- **Refusals** use fixed texts written in code, not LLM text, and run no tools.
- If the LLM lists an ID that doesn't exist, it is dropped (and noted in `warnings`).
- If the answer text contains advice or verdict words ("buy", "undervalued", "target price"...),
  or the reply is not valid JSON, the LLM text is thrown away and a **template answer** built
  from the tool results is used instead.
- If every tool failed, the answer is a refusal ("could not answer from the available data")
  listing why, instead of letting the LLM improvise.

## 6. What M5 does NOT do yet (M6)

M5 does not check that every number *written in the text* is one of the tool numbers. The prompt,
the pre-formatted numbers and the ID menus make it likely, but not guaranteed. A live example:
asked how net margin changed from FY25 to FY26, the router only fetched FY26, and the model wrote
"net margin decreased", a comparison with no FY25 figure behind it. Catching that is the job of
the verifier in M6.

## 7. How "done" was tested

- `tests/test_m5_acceptance.py` runs 10 practice questions end to end with a scripted fake LLM
  (so it is repeatable without Ollama) and checks that every answer's numbers point at citations
  that carry source, page, period and basis. It also measures routing accuracy.
- `tests/run_provisional_dev.py` does the same with the real model, database and index. Last run:
  15 of 20 answered with evidence filled, 3 correct refusals, 2 DCF questions answered "the
  assumptions file does not exist yet" (it doesn't: that is the author's P0.3 work).
