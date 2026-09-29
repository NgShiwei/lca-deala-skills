# Creating a brand-new process from a user-supplied inventory

Use this when the user wants to define an entirely new process (not calculate an
existing one). The job is to collect a complete inventory, link every input/output
to a real background activity, and build it into a working database that is ready
to calculate.

## Fields a process inventory needs

**Header (the activity itself)** — these are the `[HEADER]` columns in the CSV;
`load_inventory_csv()` normalises them to the keys `build_process` reads (`name`,
`output_amount`, …):

| Field | Notes |
|---|---|
| `name` | Identity of the activity. (`process_name` is also accepted.) |
| `reference_product` | What it produces; written onto the activity's `reference product` field. |
| `output_quantity` + `output_unit` | Becomes the **production exchange** (loaded as `output_amount`). Mandatory and explicit — without it Brightway treats output as 1 unit and the score is meaningless. |
| `location` | Geography (ISO2 / `GLO` / `RoW`); drives which background activities can link. |
| `working_database` | Where to create it. **Never a reference database** — a working copy only. |
| `allocation` | `none` / `economic` / `mass`, only if there are co-products. |
| `comment` | Optional provenance. |

**Exchange rows — one per input/output, and any number per role:**

| Field | Notes |
|---|---|
| `role` | `material` / `energy` / `transport` / `emission` / `coproduct` / `waste`. Roles map to Brightway exchange types: material/energy/transport/waste → `technosphere`, emission → `biosphere`. A `coproduct` is **not** a second `production` exchange — it is handled as a *negative technosphere* input of the displaced market (substitution) or by explicit allocation (see below). `waste` links a treatment activity whose amount is usually **negative** in ecoinvent (the treatment "produces" a negative amount of waste); confirm the sign before building. |
| `description` | Plain-language label. |
| `quantity` + `unit` | The amount and its native unit. |
| `link_name` | The background activity (technosphere) or elementary flow (emission) to link to. |
| `source_db` | Database to find the link in — must be consistent with the biosphere version the chosen method characterizes. |
| `location` | Preferred link geography (technosphere) or compartment air/water/soil (emission). |
| `factor` | Optional; multiplies quantity to match the link's unit (e.g. 1000 for m³→kg). |

There can be **as many rows per role as needed** — several materials, several
energy carriers, several transport legs, several emissions, and several outputs.
The blank template is `assets/new_process_template.csv`.

### Multiple outputs (multifunctional processes)

A process may produce more than one output, but **exactly one is the reference
product** (it goes in the header and defines the functional unit). Any additional
outputs are `coproduct` rows in the table.

Co-products make the process multifunctional, and how to handle them is a
**methodological choice — do not decide it silently**. When co-products are present,
pause and ask the user which approach to use:

- **Substitution (system expansion):** each co-product becomes a *negative*
  technosphere input of the market activity it displaces (avoided burden). Keeps the
  technosphere square automatically. The co-product row's `link_name` should point at
  that displaced market activity. `build_process(..., coproduct_handling="substitution")`.
- **Allocation (economic / mass):** split burdens across outputs by value or mass —
  this matches the Agri-footprint economic/mass approach but needs a value or mass
  per output and a separate modelling step; handle it explicitly rather than through
  `build_process`.

`build_process` will **raise** if co-products are present and no
`coproduct_handling` is given — that is deliberate, so the choice always reaches the
user.

## How to collect it (elicitation)

1. **Confirm the mode first.** Offer the fill-in table by default, but ask whether
   the user would rather do interactive Q&A or fill the CSV offline — some users
   won't have all the data to hand.
2. **Table path:** load the returned CSV with `load_inventory_csv(path)` →
   `(header, exchanges)`, then run the **gap check** (below) and list anything
   missing before proceeding.
3. **Interactive path:** walk the basic categories in order, looping "any more?"
   within each so the user can add multiple rows per role:
   - reference output (product, quantity, unit) →
   - materials (repeat) → energy carriers (repeat) → transport legs (repeat) →
   - then optionally emissions / waste / co-products.
4. **Strict validation** (always): call `resolve_links(exchanges)`. For every
   entry in `ambiguous` (>1 match) or `missing` (0 matches), **show the candidates
   and ask** — never silently pick `[0]`. For every `unit_mismatch`, confirm a
   conversion `factor` with the user. For every `geography_fallback` (the requested
   country had no match, so a `GLO`/`RoW` proxy was found), **show the proxy and
   confirm** — a country→global swap can move the score materially. Move each
   confirmed pair into `resolved`. Repeat until everything the user has approved is
   in `resolved`.
5. **Build:** `build_process(header, resolved, working_database)` creates the
   activity, adds the production exchange, links every input/output, and calls
   `db.process()` so the datapackage is current (otherwise the first calc throws
   `NonsquareTechnosphere`). It refuses to write into a reference database.
6. **Calculate** as usual (`run_multilca`) and report.

## Gap check — the basic fields a process is expected to have

Flag any of these that are absent, and ask the user to supply or explicitly skip:

1. **Output** — reference product + quantity + unit *(required; cannot skip)*
2. **Materials** — at least the main material input(s)
3. **Energy** — electricity and/or heat/fuel
4. **Transportation** — inbound/outbound legs (tkm), if relevant
5. *(advanced, optional)* direct **emissions**, **waste** outputs, **co-products**

The check is about the presence of each *category*, not a row count — a process may
legitimately have many rows in one category and none in another (e.g. an assembly
step with several materials but no direct emissions).

## Helper reference (`lca_helpers.py`)

- `load_inventory_csv(path)` → `(header, exchanges)`. Parses a filled
  `assets/new_process_template.csv` (the `[HEADER]` / `[EXCHANGES]` blocks) into the
  dicts `build_process` and `resolve_links` consume; normalises field names and
  coerces numerics. Pure Python — the "fill it offline" path.
- `resolve_links(exchanges)` →
  `{resolved, ambiguous, missing, unit_mismatch, geography_fallback}`. Read-only.
  A country→GLO/RoW substitution is surfaced in `geography_fallback` (to confirm),
  **not** silently placed in `resolved`. Drives step 4.
- `build_process(header, resolved, working_db_name)` → creates and processes the
  activity. Writes the `reference product`, adds the production exchange, uses a
  collision-safe activity code. Idempotent (replaces a same-named activity); guards
  against writing into a reference database.

### Reading the `missing` and `ambiguous` buckets

**A `missing` link is usually a rename, not an absence.** Cross-version renames
(`water, deionised` replacing `water, deionized, from tap water, at user`) and
retired geographies (a `GLO` NaOH that now exists only as `RoW` / `RER`) both land
in `missing`. Look the name up in the target database before telling the user a
flow is unavailable.

**`resolve_links` matches on name + location only, so it cannot separate the
outputs of a multi-output activity.** A process like `sulfate pulp production,
from softwood, bleached` returns several nodes differing only by reference
product, and they all arrive in `ambiguous` together. Select by reference product
explicitly and confirm the pick with the user.

### Multi-tier chains

- `load_inventory_multi(path)` → `[(header, exchanges), ...]`. Same file format,
  with the `[HEADER]`/`[EXCHANGES]` pair repeated once per process.
  `load_inventory_csv` now delegates to it and raises if the file holds more than
  one process, so a nested file can never be silently truncated to its first tier.
- `resolve_chain(processes, working_db_name)` → `{order, cycles, duplicates,
  per_process}`. The dry run. Splits each row into an **internal** link (to a
  sibling process) or a **background** link, runs `resolve_links` on the
  background ones, and topologically sorts children before parents.
- `build_chain(processes, working_db_name, background_resolved)` →
  `{name: Activity}`. Builds in dependency order, wiring internal links to the
  child activity built moments earlier. `background_resolved` is
  `{process_name: [(exchange, node), ...]}` covering only background links —
  i.e. what you settled with the user after the dry run.

## Nested / multi-tier inventories

Use `assets/new_process_template_nested.csv` when the thing being modelled is a
tree rather than a single process — a product whose intermediate is itself
modelled from a feedstock, lab and commercial variants of the same chain, or any
case where the user must key in data for several processes that feed one another.

**Linking a child to its parent.** In the parent's row, set `source_db` to the
working database name and put the child's exact `name` in `link_name`. That marks
the row as a foreground link instead of a background lookup. (For backward
compatibility with extractor output, a blank `link_name` whose `description`
exactly matches a process name also resolves — but prefer the explicit form.)

**Order in the file is irrelevant.** `resolve_chain` derives the build order from
the links. It refuses to build on a circular dependency, a duplicated process
name, or an internal link matching no process — those are structural errors, not
judgement calls, so they raise rather than prompting.

**Burden-free feedstocks** get their own `[HEADER]` with an `[EXCHANGES]` block
containing the column row and no data rows. That yields an activity with a
production exchange and no inputs, scoring zero. Never delete the row from the
parent instead: dropping it hides the cut-off assumption and breaks the mass
balance.

**Principle 3 still governs.** `resolve_chain` returns the five buckets *per
process*. Collect every ambiguity, unit mismatch, geography fallback and missing
link across the whole chain and put them to the user in one batch before calling
`build_chain` — a chain multiplies the number of judgement calls, it does not
excuse them.

**Watch the reference amounts.** A child whose production exchange is not 1 (a
lab process producing 0.00929 kg) is scaled correctly by Brightway, but only if
the amount is in the same unit as the parent's link row. Grams in the header
against kilograms in the exchanges is a silent 1000× error.

## Not wired up yet: pedigree and uncertainty

The template carries no pedigree columns, deliberately. `build_process` writes
each exchange with a plain `amount` and no uncertainty dict, so adding the
columns on their own would change nothing: users would fill in five indicators
per row for no effect. The agent-facing consequence is in `SKILL.md` — say the
uncertainty data is not captured rather than running a distribution-free
"Monte Carlo".

Wiring it up means landing all three of these together:

1. Teach `build_process` to translate the five pedigree indicators
   (`reliability`, `completeness`, `temporal_correlation`,
   `geographical_correlation`, `technological_correlation`, each 1-5) plus
   `basic_uncertainty` into a lognormal uncertainty dict.
2. Add those six columns to `assets/new_process_template.csv`.
3. Start asking for pedigree scores whenever the user wants a sensitivity or
   uncertainty analysis, the same way link, unit and geography are confirmed
   today under principle 3.
