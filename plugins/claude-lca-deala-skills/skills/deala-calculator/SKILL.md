---
name: deala-calculator
description: >-
  Calculate life-cycle ECONOMIC impacts (cost) with DEALA on top of Brightway
  2.5, the economic counterpart to the lca-calculator skill. Use whenever the
  work involves DEALA, deala_io, marketsphere flows, cost per kg or per process,
  unit prices (electricity, gas, labour, solvent, water, freight), the
  ('DEALA-Cost (BEIC 1)', 'total cost', 'TC') method, injecting cost exchanges
  into modular/cut-off activities, transport cost per country pair, or building a
  cost edge-weight table for a supply-chain graph. Also use to verify a cost
  score by hand, Σ(input_amount × unit_price) / production, and show it matches
  the native bc.MultiLCA score.
---

# DEALA Cost Calculator

Score the **economic** cost of a process the native DEALA way, verify that score
by hand, and hand the result to a supply-chain graph. This is the economic half
of the same pipeline `lca-calculator` covers environmentally: identical
functional unit, identical name parsing, identical edge-weight formula — so cost
and emissions are directly comparable and mergeable into a combined objective.

Assumes **Brightway 2.5** (`bw2data` 4.x, `bw2calc` 2.5 `MultiLCA`) with the
`deala` package's activity databases and the `DEALA-Cost (BEIC 1)` method
installed.

## The one thing that makes this work: link cost inputs as `technosphere`

Every DEALA input activity (electricity, gas, labour, transport, solvent, water)
carries `production: 1` **plus** a `type='biosphere'` exchange to a
`marketsphere` flow equal to its unit price. The `DEALA-Cost` method
characterises those marketsphere flows. So a process gets its cost by linking to
the input activity as a **`type='technosphere'`** exchange — `bc.MultiLCA` then
traverses that link and sums the input's price flow.

> **`type='marketsphere'` on your own exchange scores 0, silently.** bw2calc 2.5
> puts such an exchange in *neither* the technosphere nor the biosphere matrix,
> so it is dropped without warning and every cost comes back 0. This is the
> single most expensive mistake on the economic side. Details and the other dead
> ends (legacy `bw.LCA`, `deala_io().calculate_total_cost_processes`) are in
> `references/deala-cost-method.md` — read it before hand-rolling anything.

## Four rules before you compute

1. **Check the environment first, and never downgrade scipy.** Run
   `python ../lca-calculator/scripts/check_environment.py` (paths are relative
   to this skill's folder) in the interpreter that will do the work, or call
   `dh.check_environment()`, which runs the same check and refuses to continue.
   It prints the interpreter and checks the Brightway 2.5 pins, deala 1.2.1
   (unmodified), `ecoinvent_interface >= 3.1` and `matrix_utils >= 0.6.3`, and
   every failure comes with its fix. The `matrix_utils` floor is the one that
   bites here: below 0.6.3, DEALA-Cost `.lci()` crashes with
   `'csc_matrix' object has no attribute 'A1'` at `array_mapper.py:78`. Fix by
   upgrading the package, not by patching source or monkeypatching at runtime,
   and not by downgrading scipy — GWP scoring is fine under scipy 1.13.1 and
   downgrading breaks the environmental half. The install itself is in the
   repository's `SETUP.md`.

2. **`bd.databases.clean()` after any injection or edit — not a named
   `db.process()`.** Every `.save()` flags its database dirty; a dirty DB has a
   stale datapackage and a `depends` list missing newly-referenced input
   databases, which surfaces as `NonsquareTechnosphere` on a perfectly valid
   graph. `clean()` processes *every* dirty database, so it also catches edits to
   the DEALA input DB (e.g. a GLO price proxy) that a single named `process()`
   would miss. It writes to `processed/`, not the multi-GB SQLite — fast and safe.

3. **One Python process per project**, and set `PYTHONIOENCODING=utf-8` on
   Windows. bw2data holds a SQLite lock; closing a Jupyter *tab* does not free it
   (the kernel does). Project load is ~10 s, so batch a session's work into one
   script rather than iterating cell-by-cell. Read-only scoring generally
   tolerates a live kernel; writes do not. **Ask before killing a user's kernel.**

4. **Never silently pick `[0]`.** A cost mapping is a methodological choice —
   which electricity tier, which gas tier, which labour category, what proxy for
   a country with no price data. When a selector returns 0 or >1 matches, ask.
   `verify_cost.py` refuses to guess and prints the candidates instead.

## The workflow

1. **Check the environment** — `dh.check_environment()` (rule 1).
2. **Select the project** — `bd.projects.set_current(<name>)`.
3. **Inject cost exchanges** into the modular/cut-off activities:
   `type='technosphere'`, `input=<DEALA input activity>`,
   `amount = <physical amount> × <unit conversion>`. Resolve the input activity
   country-first with a GLO fallback. Snapshot exchanges with `list(...)` before
   adding inside the loop, or the newly-added exchanges re-match your patterns.
   Full mapping pattern in `references/deala-cost-method.md`.
4. **`dh.clean()`** — once, after the whole injection loop.
5. **Score natively** — `dh.score_native(activities)`; FU = `{act.id: 1}` → cost
   per reference unit (per kg). Scaling factors and transport come later.
6. **VERIFY BY HAND** — `dh.verify(activity)` or `verify_cost.py`. Do not skip
   this; see below.
7. **Transport** — `dh.transport_rates()` → `dh.build_transport_table(...)`.
8. **Edge table** — `dh.build_edge_table(...)` → a `calculated_cost` column.
9. **Graph** — hand off to the `supply-chain-optimizer` skill with
   `score_col="calculated_cost"`.

Steps 5–8 are wrapped in `scripts/deala_helpers.py`; steps 7–9 are detailed in
`references/transport-and-edges.md`.

## Verify the cost by hand — do this every time

A cost number that nobody has checked arithmetically is not evidence. Before
reporting any DEALA result, hand-compute one activity and show it matches:

```
cost = Σ(input_amount × unit_price) / production_amount
```

where each `unit_price` is that DEALA input activity's *own* DEALA-Cost score
(it has `production: 1` and a price flow, so scoring it alone returns its price).

```bash
set PYTHONIOENCODING=utf-8
py verify_cost.py --project <project> \
   --db "<costed modular db>" \
   --activity "<activity name substring>" --country <XX>
```

The shape of the worked example this produces — every cost input, its unit
price, its contribution, the sum, the division by production, and the ratio
native/manual **1.000000** — is written out line by line in
**`references/manual-verification.md`**. Show the user's own run in that form
when they ask "where does this number come from"; it is the whole argument in
one screen.

`--all` runs the same check over every cut-off activity as a regression gate.
Expect every ratio to read 1.000000 and the max abs diff to be float noise.
Run it after any injection change, before trusting a path.

## Bundled resources

- `scripts/deala_helpers.py` — `check_environment`, `clean`, `parse_names`,
  `find_cutoff_activities`, `score_native`, `price_inputs`, `read_cost_links`,
  `manual_cost`, `verify`, `format_verification`, `cross_check_all`,
  `transport_rates`, `build_transport_table`, `parse_scale_list`,
  `build_edge_table`. Prefer these over rewriting the same logic.
- `scripts/verify_cost.py` — CLI for the worked example (`--activity`) and the
  regression gate (`--all`).
- `references/deala-cost-method.md` — the native method, why marketsphere scores
  0, the injection/mapping pattern, `clean()` vs `process()`, the `.A1` history,
  and the dead ends not to retry.
- `references/manual-verification.md` — the step-by-step hand calculation, with
  real output.
- `references/transport-and-edges.md` — multi-leg transport model, land-mode
  tiering, edge-weight formula, and the graph handoff.

## When something looks off

- **Every cost is 0** → the exchanges are typed `marketsphere`. Retype to
  `technosphere` and `clean()`.
- **`NonsquareTechnosphere`** → you edited and did not `clean()`. That is the
  first thing to try, before hunting for orphan activities.
- **`AttributeError: ... 'A1'`** → `matrix_utils` < 0.6.3. Upgrade the package.
- **A cost is wildly out of range** → suspect the inventory, not the maths: an
  activity missing its `production` exchange is scored as if output were 1 unit.
  Run `dh.manual_cost(act)` and read the breakdown — it shows every term.
- **Native and manual disagree** → the activity has upstream technosphere inputs
  that are *not* zeroed. Native DEALA cost is
  `LCA(process) − Σ LCA(tech_input) × amount`; the two forms coincide only
  because cut-off activities have upstream zeroed. On a non-cut-off process,
  native is right and the naive sum is not.
