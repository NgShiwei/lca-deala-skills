---
name: lci-extractor
description: >-
  Extract a life-cycle inventory (LCI) from a scientific article supplied as a PDF
  (plus its Supplementary Information) and hand it off to the lca-calculator skill
  for linking and LCIA. Use whenever the user provides a paper (a PDF path) and
  wants its inventory, foreground data, input-output table, or material, energy
  and emission flows pulled out and normalised to the functional unit, including
  digitising an SI inventory table. Handles articles longer than the Read tool's
  20-page limit by reading in successive page windows. It transcribes and
  normalises only what the paper states (with provenance); it does NOT link flows
  to ecoinvent/Agri-footprint or compute scores, which is the lca-calculator's
  job, fed via this skill's [HEADER]/[EXCHANGES] template.
---

# Life Cycle Inventory Extractor

Turn a scientific article (PDF + Supplementary Information) into a structured,
fully-cited life-cycle inventory, normalised to the study's functional unit, in the
exact CSV template the **lca-calculator** skill consumes. Extraction ends at a clean
handoff: linking every flow to a background database and running LCIA is the
lca-calculator's job, reached via `to_new_process_template()`.

**Licensed data.** The rules in the `lca-calculator` skill's "Licensed data"
section apply here too: never ask for the ecoinvent password in chat, the user
stores credentials in their own terminal, never read a licensed export whole,
and never commit licensed data or anything derived from it row for row.

## Five integrity principles (read before extracting)

Ignoring these produces an inventory that looks complete and is quietly wrong.

1. **Extract only what the paper states; cite every value.** Every number goes in a
   row with a `source_location` (e.g. "Table 3", "SI Table S2 row 4", "p.7 §2.1").
   If a value isn't in the paper or its SI, leave it blank and flag the gap — **never
   fabricate, infer, or fill from memory.** A plausible-looking invented quantity is
   the worst possible outcome.

2. **Fix the functional unit first, then normalise with arithmetic you show.** Read
   the FU and reference flow before touching the inventory. Papers report inventories
   per batch, per hectare, per tonne, per year — not per FU. Record the raw number in
   `original_quantity`/`original_unit`, the basis in `per_fu_basis`, and the
   normalised value in `quantity`, and **show the division** in your message so the
   user can check it.

   **The output basis is where the silent 1000× lives.** Brightway does not convert
   units across an exchange: it scales a child by the raw ratio
   `parent_amount / child_output_amount`. A tier whose `reference_flow` reads "0.64 g",
   consumed by a parent as "0.11 kg", is scaled by `0.11/0.64` instead of `110/0.64`.
   `_resolve_output_basis` now converts the output to kg exactly (0.64 g →
   0.00064 kg) and leaves the exchange rows untouched — they are already per that same
   physical output. If no `<number> <unit>` basis can be read at all it **refuses**
   rather than defaulting to "1 unit". Never paper over a basis by hand.

3. **Foreground inventory ≠ characterised results.** A cradle-to-gate table of
   kg CO₂-eq, MJ-eq, or "GWP contribution" is an *impact assessment result*, not an
   inventory. Do not file "2.1 kg CO₂-eq" as an emission flow — that double-counts
   and can't be re-linked. Capture such headline results only as `data_type=characterized`
   rows (for the later cross-check); they are dropped before handoff. Elemental flows
   (kg CO₂ *fossil*, m³ water) are real emissions and belong in the inventory.

4. **The real inventory usually lives in the Supplementary Information.** Main-text
   tables are often aggregated or illustrative; the disaggregated, per-unit-process
   inventory is typically in the SI (a separate PDF/spreadsheet). **Always ask for the
   SI** if it wasn't provided, and treat it as the primary source when it exists.

5. **Ambiguity → ask, don't guess.** Unclear unit, unstated allocation, a total that
   doesn't reconcile with its parts, a flow you can't classify — stop and ask the
   user rather than picking a default. This mirrors the lca-calculator's "ask before
   you assume" principle, because your output flows straight into it.

## Reading the PDF — the workflow

**The Read tool caps each call at 20 pages and requires an explicit `pages` range for
any PDF over 10 pages.** Articles + SI routinely exceed 20 pages, so *never assume one
Read covers the document.* See `references/reading-articles.md` for the full strategy.

1. **Get the span, then plan windows.** Run
   `python scripts/lci_helpers.py --pageinfo <file.pdf>` to get the page count and the
   exact `Read(pages="a-b")` windows (1–20, 21–40, …). If the count can't be parsed,
   fall back to reading successive 20-page windows until Read reports an out-of-range
   page. Keep a **coverage log** of ranges read so no page or table is skipped.

2. **Structural pass, then deep read.** First skim to locate the FU, system boundary,
   and — crucially — which pages hold inventory tables (look for "Table N",
   "Inventory", "LCI", "Life cycle inventory", "Input", "Supplementary"). Then read
   *those* windows carefully rather than deep-reading every page linearly. Read the
   **SI as its own document** with the same windowed sweep; ask for it if missing.

3. **Scanned / image-only PDFs.** Read renders these visually, so you can still
   transcribe tables — but flag the transcription risk, double-check digits, and
   request a machine-readable SI/spreadsheet if one exists.

## Extraction & handoff — the workflow

4. **Capture metadata first.** Fill the `[METADATA]` block:
   functional_unit, reference_flow, system_boundary, geography, reference_year,
   allocation (as the paper states it), background_database, and `reported_result`
   (the paper's own headline LCIA number, verbatim with method — this is what the
   later cross-check compares against). Template: `assets/lci_extraction_template.csv`.

5. **Transcribe each flow into an `[EXCHANGES]` row** with `role`
   (material/energy/transport/emission/coproduct/waste), normalised `quantity`+`unit`,
   the `original_*`/`per_fu_basis` provenance, `source_location`, and `data_type`
   (foreground/background/characterized). See `references/extraction-guide.md` for
   roles, unit conversions, normalisation, co-products/allocation, sign conventions,
   and characterised-vs-elemental calls.

6. **Check before handoff.** Load with `load_extraction()`, then run `gap_check()`
   (missing categories/metadata → go back to the paper/SI) and `validate()`
   (bad role, non-numeric/unnormalised quantity, missing provenance, a characterised
   result mis-filed as a flow). Resolve every issue or surface it to the user.

7. **Emit the calculator template.** `to_new_process_template(src, dst)` writes the
   lca-calculator `[HEADER]`/`[EXCHANGES]` CSV — dropping all provenance columns and
   every `characterized` row. `link_name`/`source_db` pass through as *suggestions*
   only; never invent a link — the lca-calculator confirms them.

   **Multi-tier studies go out as ONE nested file, not N stitched by hand.** When the
   paper's chain has more than one unit process (a parent plus the sub-processes it
   consumes), use `to_nested_template(srcs, dst)` instead. It takes several
   single-process extractions *or* one multi-process extraction
   (`load_extraction_multi`) and writes the calculator's
   `new_process_template_nested.csv` format — the `[HEADER]`/`[EXCHANGES]` pair
   repeated per process — doing three things the single-process handoff cannot:

   - **Foreground-to-foreground rows are linked, not left blank.** A row pointing at a
     sibling tier gets `source_db` = the working database and `link_name` = that
     child's *exact* name.
   - **Burden-free feedstocks become their own process** with an empty `[EXCHANGES]`
     block (column row, no data rows) — a zero-input child that scores zero. Never a
     blank-link row, and never a deleted one: dropping it hides the cut-off assumption
     and breaks the mass balance.
   - **The ISO/ILCD documentation fields are carried per process**, because tiers
     legitimately differ in `reference_year`, `technology_coverage` and `data_source`.

   It **refuses to write** while any of these is outstanding, because each is the
   user's call, not yours: an ambiguous internal link (two sibling tiers match the same
   row — e.g. commercial *and* lab chitosan), an unconfirmed burden-free row, an
   internal-link unit mismatch, or a duplicate process name. Run it, take the
   `format_nested_report()` output, **ask the batched questions**, then re-run with
   `link_map=` / `burden_free=`. Every auto-made link is listed in the report too —
   read them, they are not confirmations.

8. **Verify the chain before building.** Round-trip the emitted file through the
   calculator: `load_inventory_multi` → `resolve_chain`. The build order must come out
   **children-first**, with no cycles, no duplicate names and no dangling internal
   links. Those are structural errors, not judgement calls — fix them here rather than
   letting `build_chain` raise.

9. **Hand off to lca-calculator.** Invoke the **lca-calculator** skill on the emitted
   CSV: `load_inventory_csv` → `resolve_links` (interactive linking, matching the
   paper's background database/year as closely as available) → `build_process` →
   `run_multilca`. For a nested file the path is `load_inventory_multi` →
   `resolve_chain` → `build_chain`, which builds every tier in one pass. If the paper
   reported a result, **cross-check** the computed score against it (see verification
   note below).

## Cross-checking against the paper's own result

When the paper reports its own LCIA number, the extraction is only trustworthy if the
full pipeline reproduces it. After handoff, run LCIA with the **same method the paper
used** and compare. Same order of magnitude and (where background data aligns)
within ≈±10–20% is a pass; a larger gap must be *explainable* (different ecoinvent
version, allocation choice, a geography proxy substituted during `resolve_links`) —
not traceable to a mis-read quantity/unit or a characterised value filed as a flow.
If it traces to extraction, that's a bug to fix, not an acceptable discrepancy.
Document any unavoidable background-data proxy rather than forcing the number to match.

## Bundled resources

- `assets/lci_extraction_template.csv` — the `[METADATA]` + `[EXCHANGES]` template
  with provenance columns; ships with a filled, invented example used by `--selftest`.
- `assets/lci_extraction_nested_example.csv` — a **multi-process** extraction fixture
  (parent + lab-basis child + burden-free feedstock), used by `--selftest-nested`.
- `scripts/lci_helpers.py` — pure-stdlib helpers: `load_extraction`,
  `load_extraction_multi`, `gap_check`, `validate`, `to_new_process_template`,
  `to_nested_template`/`build_nested`/`format_nested_report`,
  `pdf_page_count`/`page_windows`. CLI: `--pageinfo <pdf>` (page count + read
  windows), `--selftest`, `--selftest-nested`, `--to-template <src> [dst]`, and
  `--to-nested-template <dst> <src>... [--working-db N] [--burden-free DESC]
  [--link 'Proc::desc=Child']`. On Windows, if `python` is not on your PATH, use the `py` launcher outside a virtual environment; inside an activated one, always `python`.
- `references/reading-articles.md` — long-PDF windowed reads, coverage logging,
  scanned tables, where in a paper/SI the inventory hides.
- `references/extraction-guide.md` — field-by-field rules, roles, unit conversions,
  per-FU normalisation, allocation/co-products, characterised-vs-elemental, tricky cases.

## Relationship to the other skills

- **lca-calculator** (sibling skill) — the downstream consumer. This skill's output
  is its `new_process_template` input; do not duplicate its linking/LCIA logic here.
- Extraction stops at the inventory. Deciding allocation method, choosing the impact
  method, and resolving ambiguous background links all happen in the lca-calculator,
  interactively with the user.
