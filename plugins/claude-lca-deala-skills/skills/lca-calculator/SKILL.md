---
name: lca-calculator
description: >-
  Brightway LCA/LCIA over ecoinvent, Agri-footprint, or premise databases. Use
  for: running an impact calculation, inspecting or editing activities and
  exchanges, choosing an impact method, making a safe working copy before
  editing, defining a new foreground process from user-supplied data, and
  recovering from duplicate or broken activities.
---

# Life Cycle Assessment Calculator

Compute LCA results with Brightway and keep the underlying databases safe while
doing it. This skill assumes **Brightway 2.5** (`bw2data` 4.x, `bw2calc` 2.5 with
`MultiLCA`, `bw2io`), the API used across modern ecoinvent / Agri-footprint /
premise workflows. If a project is on legacy Brightway 2 (`bw2calc.LCA` only, no
`MultiLCA`), say so and adapt.

## Five principles that prevent expensive mistakes

These come first because ignoring them is what wrecks a day of work.

1. **Never edit an original/reference database in place. Work on a copy.**
   Copying activities into a "working" database (e.g. `<db>_working`,
   `DEALA <db>`) means an editing mistake never corrupts the source you imported.
   Duplicating a whole database is cheap relative to re-importing ecoinvent.
   See `references/working-databases-and-cleanup.md`.

2. **Make every mutating step idempotent.** Brightway's `activity.copy()` mints a
   new object each time — re-running a loop silently accumulates duplicates, and
   iterating `activity.exchanges()` *while adding* exchanges re-matches the ones
   you just added. Delete-then-copy on a stable name, and snapshot exchanges with
   `list(...)` before adding. These two habits eliminate the most common "the
   numbers doubled / tripled" bugs.

3. **Ask before you assume.** LCA is full of choices only the user can make:
   which impact method, which allocation, which proxy for missing data, what
   functional unit, whether a flow should be costed/characterized at all. When a
   selector returns 0 or >1 candidates, when data is missing, or when a mapping is
   a judgement call, stop and ask rather than silently picking `[0]`. A wrong
   default propagates into every downstream result.

4. **No single activity matches the request? Ask — never quietly assemble your
   own inventory.** When no existing activity in the loaded databases has a
   reference product that matches what the user asked for (e.g. they ask for a
   "PET water bottle" and the database only has PET granulate and a separate
   moulding step), do **not** silently stitch background activities together into
   an ad-hoc inventory and report a number as if it were the thing they asked for.
   Stop and ask whether they want to **create a new process**, offering both
   routes: (a) the **guided-interactive template** — you elicit the inventory
   row by row, or (b) **uploading a filled CSV** (`assets/new_process_template.csv`).
   You *may* additionally offer to **assume/approximate a life-cycle inventory**
   yourself (a stand-in built from related background activities), but this is
   **never the default** — present it only as an explicit third option the user
   opts into, and label any resulting number as an assumed inventory. See
   [Creating an entirely new process](#creating-an-entirely-new-process).

5. **Verification is a gate.** A score is not delivered until it has been
   checked against an anchor outside the model. Ask the user for that absolute
   anchor; if you believe one is in their files, name the specific file and ask
   permission before opening it. Expect a gap and explain it — a model that
   lands exactly on a published number is more often a sign you tuned toward it
   than a sign it is right. Where no anchor exists (many papers report only
   normalised results), deliver the model explicitly labelled **unvalidated**.

## The workflow

Detailed, copy-adaptable code for every step is in
`references/brightway-patterns.md` — read it when you implement. The steps:

0. **Check the environment** — run `python scripts/check_environment.py` in the
   interpreter that will do the work (the notebook kernel, not just any
   terminal). Add `--no-deala` for purely environmental work. It prints
   `sys.executable` and fails with the fix for each problem: the Brightway 2.5
   pins, `ecoinvent_interface >= 3.1`, `matrix_utils >= 0.6.3`, deala. Don't
   start until it prints `OK`. Installing is in the repository's `SETUP.md`.
1. **Set up** — import `bw2data as bd`, `bw2calc as bc`, `bw2io as bi`,
   `pandas`, `numpy`; select the project with `bd.projects.set_current(<name>)`;
   list databases with `list(bd.databases)`.
2. **Manage databases** — copy a source DB to a working DB before editing;
   delete a stale working DB with `del bd.databases[<name>]`. Confirm the target
   name with the user before deleting anything — deletion is irreversible.
3. **Inspect activities & exchanges** — find activities by name/location, list
   their exchanges (`production` / `technosphere` / `biosphere`), read amounts.
   Use `bwa.print_recursive_supply_chain(act)` for structure.
4. **Edit exchanges** — add a new exchange with `act.new_exchange(...).save()`,
   zero or change amounts, delete activities/exchanges. Always snapshot with
   `list(act.exchanges())` before adding inside a loop. **After creating or
   editing activities in a database, call `db.process()` before you calculate** —
   an unprocessed (stale) datapackage yields a `NonsquareTechnosphere` error even
   when every exchange link is correct.
5. **Define the impact method** — resolve a method key (a 3- or 4-tuple) from
   `bd.methods`. The namespace `m[0]` must match the biosphere version the
   inventory is linked to. Default: IPCC 2021 GWP100. See
   `references/method-selection.md` and `scripts/query_methods.py`.
6. **Define the functional unit(s)** — build
   `{activity_name: {activity.id: amount}}`. One entry per activity for a
   multi-activity `MultiLCA`.
7. **Construct the matrices** — `data_objs = bd.get_multilca_data_objs(
   functional_units=..., method_config={"impact_categories": [key]})`.
8. **Run** — `MultiLCA(demands=..., method_config=..., data_objs=..., use_distributions=False)`,
   then `.lci()` then `.lcia()`.
9. **Save as DataFrame** — `pd.DataFrame.from_dict(mlca.scores, orient="index")`;
   write to CSV. `mlca.scores` is keyed by `(method_tuple, fu_name)`.
10. **Show / plot results** — display the DataFrame; plot only what the user
    asks for (per-activity bars, contribution, or the downstream network). Ask
    what they want to see rather than guessing a chart.

Steps 5–9 are wrapped in `scripts/lca_helpers.py::run_multilca(...)` so you don't
re-derive them each time; use it unless the user needs the intermediate objects.

## Creating an entirely new process

This is where principle 4 routes to: reach it either when the user explicitly
asks to define a *new* process, or when no existing activity matched their
request and they chose to build one. Offer the two data-entry routes up front —
the **guided-interactive template** (you elicit the inventory row by row) or an
**uploaded CSV** (`assets/new_process_template.csv`) — and confirm which they
want before proceeding. Then collect a full inventory, link every input/output
to a real background activity, and build it into a working database. The required fields, the elicitation flow
(offer the fill-in table first but confirm the mode; fall back to interactive
prompting or gap-detection when data is incomplete; there may be many rows per
role), and the strict link/unit confirmation are in
`references/new-process-template.md`. Use `load_inventory_csv()` (if the user filled
the table) → `resolve_links()` → `build_process()` from `lca_helpers.py`; the blank
table is `assets/new_process_template.csv`.
Because the user is supplying data you cannot verify, lean hard on principle 3 —
confirm every ambiguous link, every unit, and every geography proxy before building.

### When the inventory is a chain, not one process

Real inventories are often multi-tier: the product is made from an intermediate
that is itself a foreground process, which in turn consumes a feedstock. Ask
early — *"is any input of this process something you also have data for, rather
than an ecoinvent activity?"* — because discovering it after building the parent
means rebuilding.

Use `assets/new_process_template_nested.csv`: the same `[HEADER]`/`[EXCHANGES]`
pair, repeated once per process in one file. A row links to a sibling process by
setting `source_db` to the working database and `link_name` to that process's
exact `name`. Then:

```python
procs = load_inventory_multi(path)
plan  = resolve_chain(procs, "LCA_working")   # dry run: buckets per process + build order
# ... settle every ambiguity/missing/unit/geography row with the user ...
built = build_chain(procs, "LCA_working", background_resolved)
```

`resolve_chain` sorts children before parents itself, so the file can be written
in whatever order reads most clearly. It refuses to build on a circular
dependency, a duplicate process name, or an internal link pointing at nothing.
Burden-free feedstocks are their own process with an empty `[EXCHANGES]` block —
a production exchange and no inputs, scoring zero — never a row deleted from the
parent.

The five buckets come back **per process**. Gather them across the whole chain
and put them to the user in one batch: a chain multiplies the judgement calls, it
does not excuse them.

**Blank `link_name` cells are not yours to fill silently.** When the uploaded CSV
leaves the `link_name` column empty (in whole or in part), the user has not chosen
a background activity — you are only *guessing* one. Do not resolve, build, and
report a number off your own guesses. Instead, propose the ecoinvent activity you
would use for each blank row (name, reference product, location, and why it is a
reasonable proxy) and **confirm the suggested links with the user before building**.
Only proceed once they have accepted or corrected them. This holds even when your
guess resolves cleanly — a clean match to the wrong activity (e.g. an incinerator's
electricity co-product instead of its `waste ...` reference product) still produces
a wrong answer.

## Documentation fields, and the pedigree block that is NOT there yet

`assets/new_process_template.csv` carries ISO 14040/14044 + ILCD documentation
fields in the header (`allocation_justification`, `system_boundary`,
`cutoff_rules`, `technology_coverage`, `reference_year`, `data_source`) and
`link_rationale` in the exchanges. They do not affect any number — they make the
record auditable. `load_inventory_csv` passes them through untouched, so they are
safe to fill and safe to leave blank. Ask the user for them; do not invent them.

**Deliberately absent: the ecoinvent pedigree matrix.** Uncertainty/sensitivity
is not wired up. `run_multilca(..., use_distributions=True)` exists, but
`build_process` writes each exchange with a plain `amount` and no uncertainty
dict, so Brightway samples a point value and a "stochastic" run returns the
deterministic answer.

**When a user asks for sensitivity, uncertainty or Monte Carlo analysis, tell
them the uncertainty data is not captured yet.** Running a distribution-free
"Monte Carlo" and reporting the spread would dress a deterministic answer up as
a stochastic one. What it would take to wire this up is recorded under "Not
wired up yet" in `references/new-process-template.md`.

## Bundled resources

- `scripts/lca_helpers.py` — reusable, import-or-copy helpers for working
  copies, activity and exchange inspection, cleanup, method lookup, and running
  a MultiLCA. Read the file for the full set; prefer these over hand-writing the
  same logic. Two things the signatures do not tell you: the new-process
  pipelines are order-dependent — `load_inventory_csv` → `resolve_links` →
  `build_process` for one process, `load_inventory_multi` → `resolve_chain` →
  `build_chain` for a multi-tier chain — and `resolve_links` returns five
  buckets, where the fifth, `geography_fallback`, flags country→GLO/RoW proxies
  that need confirming rather than silently resolving them.
- `references/new-process-template.md` + `assets/new_process_template.csv` —
  fields, elicitation flow, and blank table for defining a brand-new process.
  Includes the ISO/ILCD documentation fields; pedigree/uncertainty columns are
  deliberately not present yet (see above).
- `assets/new_process_template_nested.csv` — the same format with the block pair
  repeated per process, for a child→parent chain built in one pass.
- `scripts/check_environment.py` — the shared environment check every
  Brightway skill runs first. Importable: `check(require_deala=...)` returns a
  list of `(problem, fix)` pairs.
- `scripts/query_methods.py` — CLI to list/search available LCIA methods in a
  project (`python query_methods.py --project <p> --version ecoinvent-3.10
  --contains "global warming"`). On Windows, `python` is often not on PATH — use
  the `py` launcher instead (`py query_methods.py ...`).
- `references/brightway-patterns.md` — the 10 steps as concrete code.
- `references/working-databases-and-cleanup.md` — safe working copies, and how
  to recover when a run goes wrong (duplicate accumulation, broken activities
  missing a production exchange, re-match cascades).
- `references/method-selection.md` — method-key structure, querying `bd.methods`,
  matching the method namespace to the biosphere version.

## When something looks off

If results are implausible (one activity orders of magnitude off the others),
suspect the inventory, not the maths: a duplicate activity missing its
`production` exchange scores as if output were 1 unit. Inspect the activity's
exchanges before trusting any score.

On a `NonsquareTechnosphere` error, don't guess the cause — run
`diagnose_nonsquare(demand)` (in `lca_helpers.py`). It has two common causes that
look identical: a stale datapackage on a just-edited database (fix: `db.process()`
then retry) versus a genuine orphan/duplicate activity (fix: inspect and remove).
Both are covered in `references/working-databases-and-cleanup.md`.
