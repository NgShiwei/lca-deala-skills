# Reading scientific articles (and their SI) for inventory data

## First: check that `Read` can open a PDF at all

`Read` renders PDF pages through poppler (`pdftoppm`). Where poppler is **not
installed, `Read` cannot open a PDF at all** — this was the case on the machine
this skill was built on. Test it on page 1 before planning a sweep.

When `Read` cannot render, extract the text yourself instead:

```
pdftotext -table <file.pdf> -        # xpdf 4.06; -table preserves column structure
```

`-table` matters: without it, table columns collapse into unreadable runs and
digits merge across cells. The windowing advice below still applies — work
through the document in sections and keep the same coverage log — you are just
reading extracted text rather than rendered pages.

## The Read tool's limits

The `Read` tool ingests PDFs directly where poppler is available. Two hard facts
shape everything below:

- Each `Read` call covers **at most 20 pages**.
- For any PDF **over 10 pages**, the `pages` argument is **required** (e.g.
  `Read(file_path=..., pages="1-20")`).

A research article plus its Supplementary Information routinely runs 30–80 pages, so
**one `Read` call never covers the whole document.** Reading long PDFs is a sweep of
successive ≤20-page windows with a coverage log — not a single call.

## 1. Get the span before reading

```
python scripts/lci_helpers.py --pageinfo <file.pdf>
```

Prints the page count and the exact windows to read, e.g. for 55 pages:

```
Read(pages="1-20")
Read(pages="21-40")
Read(pages="41-55")
```

`pdf_page_count()` prefers the `/Type /Pages … /Count N` object and falls back to
counting `/Type /Page` markers. If it returns `None` (encrypted, malformed, or
unusual producer), fall back to reading successive 20-page windows (`1-20`, `21-40`,
…) until `Read` reports a page beyond the end — then stop.

## 2. Keep a coverage log

Track which ranges you've read so nothing is skipped or double-transcribed. A simple
running note is enough:

```
main.pdf (18 pp):  1-18 read.  Inventory: Table 3 p.6, Table 4 p.8.
SI.pdf   (41 pp):  1-20 read, 21-40 read, 41-41 read.  Inventory: Tables S2-S5 pp.4-11.
```

Every window in the plan must appear in the log before you consider the document
covered.

## 3. Structural pass first, then deep read

Do **not** deep-read all 60+ pages linearly. Two passes are faster and safer:

- **Locate (skim):** read each window once looking for the functional unit, system
  boundary, allocation statement, and the *pages that hold inventory tables*. Signals:
  "Table N", "Life cycle inventory", "Inventory", "LCI", "Input data", "Foreground",
  "Unit process", "per functional unit", "Supplementary", "Table S…".
- **Transcribe (careful):** re-read only the windows containing inventory tables and
  copy values digit-by-digit into the template, one row per flow, each with its
  `source_location`.

## 4. Where the inventory actually hides

- **Main text** usually gives the FU, system boundary, allocation choice, and an
  *aggregated* or illustrative inventory. Often it only shows characterised results
  (kg CO₂-eq per category) — those are impacts, not inventory (see extraction-guide).
- **Supplementary Information** usually holds the *disaggregated* inventory: per-unit-
  process input/output tables with real quantities and units. **This is the primary
  source.** If the user didn't provide the SI, ask for it before finalising — an
  inventory built from the main text alone is usually incomplete.
- **Data repositories:** some papers put the inventory in an external dataset
  (Zenodo/Mendeley/ecoinvent submission). If the text references one and it's not in
  hand, tell the user what's missing rather than approximating.

## 5. Scanned / image-only PDFs

Where `Read` can render (see the poppler note at the top), scanned tables are still
transcribable — `pdftotext` returns nothing useful on an image-only page, so this is
the one case that genuinely needs rendering. But:

- Flag the transcription risk to the user; scanned digits are error-prone.
- Double-check decimal points, thousands separators, and easily-confused digits.
- Ask whether a machine-readable SI or source spreadsheet exists — always prefer it.

## 6. Practical tips

- Multi-column layouts and tables that break across a page boundary: read the window
  that spans the break so you don't lose the continuation rows.
- Note the table's stated basis (per batch / per ha / per t / per year) *at the table*,
  not later — it's the `per_fu_basis` you'll normalise against.
- If a total row and its component rows don't reconcile, record both and ask; don't
  silently trust one over the other.
