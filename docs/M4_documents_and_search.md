# M4: Turning the annual report into searchable chunks (plain-language note)

SQLite holds the **numbers**. This milestone handles the **words**: what the annual report
*says* about risks, clients, strategy, people and capital allocation. The goal is that a
question like "how does TCS manage cyber risk?" finds the right passage, and that every passage
found tells you exactly which page it came from.

No LLM writes anything in this milestone. The only model is an *embedding* model, which turns
text into numbers so that passages with similar meaning can be found.

## 1. What a chunk is

The annual report is 360 PDF pages. You can't hand a search system a whole page, let alone a
whole report: a page mixes several topics, and the embedding model only reads a limited amount
of text at once. So the text is cut into **chunks** of about 1,500 characters (a few paragraphs).

How the cutting works (`src/erp/ingest/pdf_to_chunks.py`):
- Read each page's lines with PyMuPDF. Drop the running header ("Statutory Reports ...") and the
  footer (page number, report name). They are on every page and would only add noise.
- Find **headings** by their font: bold and clearly bigger than the body text (body is 9 pt,
  headings 11 pt). A heading starts a new section, and its name is stored with every chunk below
  it, even on later pages.
- Cut each section into chunks on line boundaries. Consecutive chunks **overlap** by about 200
  characters, so a sentence cut in two still appears whole in one of them.
- A chunk stays on **one page**. Exception: a tiny leftover at the bottom of a page (under 200
  characters) is joined to the top of the next page if the same section continues there. That
  chunk records both pages.

## 2. Why every chunk carries a page

The core rule of the project is *sources prove*. An answer that says "the annual report says X"
is only checkable if it says **where**. So the page is attached to the chunk when it is made,
from the PDF itself, and travels with it into the database and out of every search.
The citation is then a fact about the data, not something an LLM types (LLMs invent page numbers
easily). A chunk without a source and a page is refused before anything is stored, and a search
never returns one.

There are two page numbers:
- **`page`**: the PDF page index (1 = the first page of the file). Always present.
- **`page_label`**: the number printed on the page. PDF page 167 is printed page 197. Readers
  of the printed report use this one.

This PDF has no built-in page labels, and some printed page numbers are only partly readable by
software (page "90" reads as "9"). So the printed numbers are written in the company config as
ranges (`page_labels` in `config/companies/tcs.yaml`), and the code re-reads every footer to check
the config: 0 contradictions, 57 footers partly unreadable. The first 30 pages are two-page
spreads (one PDF page = two printed pages side by side). They are read as two halves, so each
half gets its own printed number.

Other metadata on every chunk: `source_id` (the document's row in SQLite `source_document`, so
numbers and text point to the same document list), `doc_type`, `doc_title`, `section`,
`fiscal_year`, `chunk_id` and `is_table_heavy`.

## 3. What an embedding is

An **embedding** is a list of numbers (768 of them for `nomic-embed-text`) that stands for the
meaning of a piece of text. Texts about similar things get similar lists, even if they use
different words: "returning cash to shareholders" lands near "dividends and buybacks".

To search:
1. When indexing, every chunk is embedded once and stored in **ChromaDB** (a database built for
   this) together with its text and metadata.
2. When searching, the question is embedded the same way, and ChromaDB returns the chunks whose
   lists are closest. The **score** is the cosine similarity (1 = same direction, near 0 =
   unrelated).

The embedding model runs locally in Ollama and is called through one function
(`embed_texts` in `src/erp/ingest/embed.py`), with the model name in `config/ingest.yaml`. The
model expects a hint on each input ("search_document: " for chunks, "search_query: " for
questions), so the code adds those.

ChromaDB can embed text by itself, but it does that by downloading a different model from the
internet. That is switched off: if anything ever asks ChromaDB to embed, it raises an error.

## 4. Tables and numbers

Financial statement pages come out of the PDF as one cell per line, and numbers often get stray
spaces ("2, 7 1, 423"). So:
- **Chunk text is never used as the source of a number.** Numbers come from SQLite, where every
  one was typed and checked against its page.
- Chunks that are mostly numbers are marked `is_table_heavy` (229 of 1,118). Search lowers their
  score a little (x 0.85), so for a qualitative question a prose passage wins over a table with
  the same words.

## 5. Running it twice changes nothing

Each stored chunk records the file's **sha256** (a fingerprint of the file's bytes). On a re-run,
if the fingerprint matches, the file is skipped (about 1 second for both documents). If the file
changed (and its new fingerprint was registered), its old chunks are deleted and it is indexed
again. The same happens if the embedding model changes. A file that isn't registered in SQLite,
or whose fingerprint doesn't match the registered one, or that is an LLM-generated note
(`generated_sample`, or anything in `data/sample/generated/`), is refused.

## 6. search_documents

`search_documents(query, top_k=5, doc_type=None, fiscal_year=None, source_id=None)` in
`src/erp/tools/search.py` is a plain Python function (no LLM). It returns a list of results, best
first, each with the chunk text, source_id, document title, page, printed page label, section and
score. The filters narrow the search, e.g. only the FY2026 annual report.

## 7. How well does it find things? (provisional)

Claude wrote 12 test questions in the style of the eval's qualitative category (risks, client
concentration, capital allocation, strategy, people) and noted the right pages after reading the
report. Result on the real report: the right page is in the **top 5 for 9 of the 12** questions
and in the top 10 for 11 of 12.

This is only a first baseline. The questions and expected pages are Claude's, not the author's;
some misses look like the expected pages were too narrow, and one depends on wording. The real
measure comes from the author's own eval questions (P0.4), and only then is a target set.

## Words to know
- **Chunk**: a few paragraphs of report text, with its page and section.
- **Embedding**: a list of numbers standing for a text's meaning; close lists = similar meaning.
- **Vector store** (ChromaDB): a database that finds the stored embeddings closest to a question's.
- **recall@5**: share of questions where a correct page appears in the top 5 results.
- **sha256**: a fingerprint of a file; any change to the file changes it.
