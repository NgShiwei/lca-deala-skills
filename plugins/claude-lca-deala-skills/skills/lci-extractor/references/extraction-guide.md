# Extraction guide — turning a paper's numbers into a clean inventory

How to fill `assets/lci_extraction_template.csv` correctly. The template has two
blocks: `[METADATA]` (one row about the study) and `[EXCHANGES]` (one row per flow).
Load it with `lci_helpers.load_extraction(path)`.

## Metadata block — set the frame first

| Field | What to record | Where it comes from |
|---|---|---|
| `functional_unit` | The FU **verbatim** (e.g. "1 kg protein isolate, 90% protein"). | Goal & scope / methods. |
| `reference_flow` | The physical flow delivering the FU + amount/unit (often "1 kg <product>"). Drives the handoff's `output_quantity`/`output_unit` — see **Output basis** below. | Methods. |
| `process_name` | *Optional; required for multi-tier.* What to call **this** unit process. Children are linked by name, so each tier needs its own. | You, from the paper's process names. |
| `system_boundary` | cradle-to-gate / -grave / gate-to-gate, and what's included/excluded. | Methods / a system diagram. |
| `geography` | Country/region modelled (ISO2 / GLO / RoW / name). | Methods. |
| `reference_year` | Year the inventory represents. | Methods / data sources. |
| `allocation` | none / economic / mass / substitution — **as the paper states it**. | Methods (allocation section). |
| `background_database` | The LCI database + version the paper used (e.g. "ecoinvent 3.8 cutoff"). Lets the cross-check match. | Methods / data sources. |
| `reported_result` | The paper's headline LCIA result verbatim **with method** (e.g. "3.2 kg CO₂-eq/kg, IPCC GWP100"). The cross-check target. | Results / abstract. |
| `allocation_justification`, `cutoff_rules`, `technology_coverage`, `data_source` | *Optional* ISO 14040/44 + ILCD documentation, carried **per process** to the calculator's header. Tiers legitimately differ. | Methods; leave blank rather than inventing. |
| `notes` | Anything needed to interpret the inventory. | — |

Do the FU **before** the flows: every exchange quantity is normalised against it.

### Output basis — where a silent 1000× hides

`reference_flow` sets the process's production amount. Brightway does **not** convert
units across an exchange: it scales a child by `parent_amount / child_output_amount`.
So a lab tier reported per "0.64 g", consumed by its parent as "0.11 kg", gets scaled
by `0.11/0.64` instead of `110/0.64` — a 1000× underestimate that looks like nothing.

`_resolve_output_basis` handles this by **exact conversion**: "0.64 g" becomes
`0.00064 kg`. The exchange rows are deliberately **not** rescaled — they are already
expressed per that same physical output, so only the output's unit label changes. If
the reference flow carries no readable `<number> <unit>`, the emitter **refuses**
rather than defaulting to "1 unit". Record the paper's native basis verbatim and let
the tool convert; do not pre-scale it by hand.

## Exchange rows — one per flow

### `role`
Same vocabulary the lca-calculator uses, so the handoff maps straight through:

| role | use for | maps to (in lca-calculator) |
|---|---|---|
| `material` | material/feedstock/chemical/water inputs | technosphere |
| `energy` | electricity, heat, fuel | technosphere |
| `transport` | transport legs (usually tkm) | technosphere |
| `emission` | **elemental** emissions to air/water/soil (kg CO₂ fossil, kg CH₄, m³ water) | biosphere |
| `coproduct` | any output besides the reference product | negative technosphere / allocation |
| `waste` | waste sent to treatment (amount often **negative** in ecoinvent) | technosphere |

### Quantities and normalisation (principle 2)
Papers rarely report per-FU. For each flow:

1. Copy the printed number → `original_quantity` + `original_unit`.
2. Record the table's basis → `per_fu_basis` (e.g. "per batch 500 kg", "per ha",
   "per 1 t product").
3. Compute the per-FU value → `quantity` (+ `unit`), and **show the arithmetic** in
   your message. Example: 950 kWh per 500 kg product, FU = 1 kg → 950 / 500 = **1.9
   kWh/kg**.

If a flow is already per-FU, set `original_*` equal to `quantity`/`unit` and
`per_fu_basis` = "per 1 <FU>".

### Units
Keep the paper's native unit in `unit`; do conversions explicitly and note them.
Common ones:

- mass: 1 t = 1000 kg; 1 g = 0.001 kg. **`mt` is deliberately absent from
  `_MASS_TO_KG`** — it reads as both "metric ton" and "megatonne", a factor of 10⁶
  apart. An output basis in `mt` therefore raises `UnitBasisError` instead of
  resolving; ask the user which the paper means.
- energy: 1 kWh = 3.6 MJ; 1 MJ = 0.2778 kWh; watch LHV vs HHV for fuels.
- transport: tkm = tonne × km — if the paper gives mass and distance separately,
  compute tkm and show it.
- volume→mass: needs a density (`factor`, e.g. water 1000 kg/m³); don't assume one
  silently.

The `factor` column is a *link-side* unit conversion for the lca-calculator (e.g.
1000 to turn m³ into kg against a per-kg activity). It does **not** rescale
`quantity`; per-FU normalisation is already baked into `quantity`.

### `data_type` — the critical classification (principle 3)
- `foreground` — a primary inventory flow the study measured or modelled. The default
  for real inputs/outputs.
- `background` — an inventory flow the study took from an LCI database. Still a real
  flow; keep it (mark the source in `notes`).
- `characterized` — an **impact-assessment result** (kg CO₂-eq, MJ-eq, mol H⁺-eq,
  "GWP contribution"). **Not an inventory flow.** Keep it only to cross-check against
  `reported_result`; `to_new_process_template()` drops these rows on handoff.

The tell: characterised results carry impact units (…-eq) or sit under headings like
"Impact assessment", "Characterised results", "GWP contribution". Elemental flows
(kg CO₂ *fossil*, kg CH₄, m³ water, kg P) carry physical units and belong in the
inventory as `emission`/`material`.

`validate()` flags a row whose `unit` looks like an impact score (contains "co2" or
"eq") but isn't marked `characterized` — resolve those deliberately.

### `source_location` — mandatory provenance (principle 1)
Every row cites exactly where the value came from: "Table 3", "SI Table S2 row 4",
"Fig 2 caption", "p.7 §2.1". A row without provenance fails `validate()`.

### Optional link hints
`link_name` / `source_db` / `location` may hold a *suggested* background activity —
but leave them blank unless the paper effectively names it. The lca-calculator's
`resolve_links` does the real, interactive linking; never invent a link here.

## Co-products and allocation

If the process has more than one output, exactly one is the reference product; the
others are `coproduct` rows. **How to split burdens is the paper's methodological
choice — record it in metadata `allocation`, don't invent one.**

- Paper used **economic/mass allocation:** set `allocation` accordingly; capture the
  co-product as a `coproduct` row and note the allocation factor/basis in `notes`.
- Paper used **substitution/system expansion:** note it; the co-product displaces a
  market activity (handled at build time in the lca-calculator as a negative
  technosphere input). `to_new_process_template` maps unknown allocations to `none`
  and leaves the methodological handling to the calculator — flag this to the user.

## Multi-tier studies — a parent plus the sub-processes it consumes

Many papers model a chain: a final product made from an intermediate the same study
also inventories (FLAM ← chitosan ← chitin). Each tier is its **own unit process**,
with its own reference flow, its own basis and often its own reference year and
technology scale. Extract them separately — either one file per tier, or one file
with the `[METADATA]`/`[EXCHANGES]` pair repeated (`load_extraction_multi`, see
`assets/lci_extraction_nested_example.csv`). Then emit **one** nested file with
`to_nested_template()`.

**Give every tier a distinct `process_name`.** `title` is the article and would
collide across tiers; the nested format links a child to its parent *by name*.

### The parent's row for its child
Leave `link_name`/`source_db` **blank** in the extraction — it is not a background
activity. `to_nested_template` rewrites the row to `source_db` = the working database
and `link_name` = the child's exact name. Where two tiers could match the same row
(commercial *and* lab chitosan both answer to "chitosan"), the emitter refuses and
asks rather than picking. Answer with the scenario the FU actually refers to.

### Burden-free feedstocks
A waste or by-product entering free under cut-off is **its own process** with no
inputs — an empty `[EXCHANGES]` block that scores zero. It is **not** a blank-link
row, and it is **never** a deleted row: dropping it hides the cut-off assumption and
breaks the mass balance. Keep the row in the parent's extraction with the reasoning in
`notes` (say "burden-free" / "cut-off"); the emitter will spot it as a candidate,
**ask**, and on confirmation promote it to a zero-input child whose output unit
matches the parent's row exactly.

### Before building
Round-trip the emitted file through `load_inventory_multi` → `resolve_chain`. Build
order must be **children-first**, with no cycles, no duplicate names, no dangling
internal links. Those are structural errors — fix them here.

## Waste sign convention

In ecoinvent a waste-treatment activity "produces" a **negative** amount of waste, so
`waste` rows often carry a negative `quantity`. Record the sign as the paper implies
and note it; confirm at build time.

## Tricky cases

- **Aggregated vs disaggregated:** prefer the SI's disaggregated per-unit-process
  rows over a single main-text total. If you must use a total, say so in `notes`.
- **Ranges / scenarios:** if a flow is given as a range or per scenario, extract the
  baseline the FU/result refers to, and note the range — don't average silently.
- **"Negligible"/"—"/blank cells:** record as absent, not as zero, unless the paper
  says zero. Note the ambiguity.
- **Totals that don't reconcile:** record components and total, and ask the user which
  governs — never quietly reconcile them yourself.
- **Percentages / shares:** convert to absolute per-FU amounts using a stated
  reference amount; if none is stated, ask.
