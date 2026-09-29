# The native DEALA-Cost method under Brightway 2.5

## How DEALA represents a price

Verified against `deala` 1.2.1 source (`deala_io.py`). Each activity in a DEALA
input database (`DEALA_activities_remind_SSP2-NPi` and siblings) — electricity,
gas, labour, transport, solvent, water — has:

- `production: 1` (one kWh, MJ, kg, tkm, h …), and
- a `type='biosphere'` exchange to a **`marketsphere`** flow whose amount is its
  **unit price**.

The method `('DEALA-Cost (BEIC 1)', 'total cost', 'TC')` carries the
characterisation factors for those marketsphere flows. So scoring an input
activity alone returns its price, and scoring a process that links *to* that
activity returns the process's cost.

DEALA's own formula (`calculate_total_cost_processes`, `deala_io.py:1116`):

```
total = LCA(process) − Σ LCA(technosphere_input) × amount
```

The subtraction avoids double-counting cost already embodied upstream. For
**cut-off** activities (all upstream inputs zeroed) the subtraction term is zero,
so the native score equals a plain `Σ(amount × price) / production` — which is
what makes the hand verification in `manual-verification.md` exact.

## Link cost inputs as `technosphere`

```python
new_activity.new_exchange(
    name=deala_act["name"],
    input=deala_act,
    amount=physical_amount * unit_conversion,
    unit=DEALA_UNIT[deala_act["unit"]],
    type="technosphere",      # <-- NOT 'marketsphere'
).save()
```

**`type='marketsphere'` on your own exchange scores 0, silently.** bw2calc 2.5
places such an exchange in neither the technosphere nor the biosphere matrix, so
it is dropped without any warning and every process comes back 0. The
marketsphere flow belongs *inside* the DEALA input activity (where DEALA put it);
your link to that activity is an ordinary technosphere edge.

Probed and confirmed: DEALA input activities have `production: 1` **plus** the
biosphere price flow, so linking them keeps the technosphere square — no
`NonsquareTechnosphere` from this.

## Dead ends — do not retry these

Each was tried and failed on this stack (bw2data 4.7 / bw2calc 2.5.0 / deala 1.2.1):

| Attempt | Result |
|---|---|
| Score cut-off activities with `type='marketsphere'` cost links | **all 0** — dropped from both matrices |
| `bw.LCA({act: 1}, cost_key).lcia()` (legacy style) | **0**, and crashes on `.A1` below matrix_utils 0.6.3 |
| `deala_io().calculate_total_cost_processes(db)` | `TypeError` — calls the removed legacy `MultiLCA('setup')` API; `deala.io` is a Brightway wrapper, not a separate engine |
| Downgrading scipy to dodge the `.A1` crash | breaks nothing visibly but is the wrong fix, and GWP scoring is fine on scipy 1.13.1 — **don't** |

Conclusion: do not try to make the solver score `marketsphere` exchanges. Link
`technosphere` and the native method works.

## `bd.databases.clean()`, not `db.process()`

Every `.save()` on an activity or exchange flags its database *dirty*
(`bw2data` `databases.set_dirty(...)`, via `backends/proxies.py`). A dirty
database has a stale processed datapackage **and** a `depends` list that omits
newly-referenced input databases — here `DEALA_activities_remind_SSP2-NPi`, which
the injection has just started referencing. The modern API path
(`bd.get_multilca_data_objs()` + `bc.MultiLCA(demands=…, data_objs=…)`) reads
each database's datapackage directly (`bw2data/compat.py:172`) and walks
`depends` (`find_graph_dependents`), so it assembles a matrix with orphan product
rows → **`NonsquareTechnosphere`** on a perfectly valid graph.

`bd.databases.clean()` (`bw2data/meta.py`) runs `.process()` on **every** dirty
database and clears the flag. Prefer it over a named `deala_modular_db.process()`
for two reasons: it refreshes the modular DB's datapackage and `depends` just the
same, **and** it also reprocesses any other edited database — e.g. a GLO gas-price
proxy written into the DEALA input DB — that a single named `process()` would
miss. Call it **once**, after the whole injection loop, never per activity.

It writes datapackages (hundreds of MB for a large project) to `processed/`, **not** to the multi-GB
`databases.db` SQLite file, so it is fast and safe even on a bloated project.

**Why deala's own examples don't need it:** the legacy demand path
(`bw.LCA(demand)`, `bw.MultiLCA` via `calculation_setups`) goes through
`prepare_lca_inputs`, which calls `databases.clean()` for you
(`compat.py:84`). The explicit clean is a consequence of using the modern
explicit-`data_objs` API, not of anything being out of date.

## The `matrix_utils` `.A1` crash

Under scipy ≥ 1.13, `bc.MultiLCA(...).lci()` for **any method characterised
against the biosphere** — which DEALA-Cost is — crashed with

```
AttributeError: 'csc_matrix' object has no attribute 'A1'
  at matrix_utils/array_mapper.py:78
```

because that line was written for the old `np.matrix.A1` and scipy 1.13 sparse
indexing now returns a `csc_matrix`. GWP scoring is **unaffected** (it does not
hit that path), so **scipy must not be downgraded** — that would break the
environmental half to fix the economic one.

**The fix is a package upgrade, not a patch.** The correction
(`np.asarray(...).ravel()`, upstream commit `6445e5d`, "Fix #32") first shipped in
`matrix_utils` **0.6.3**; the environment had 0.6.2.

0.6.3 is a **floor**, not a preference: anything at or above it carries the
fix. `requirements.txt` pins exactly 0.6.3 because that is the verified
environment; `check_environment.py` enforces only the floor. Install from the
requirements files rather than upgrading this one package on its own, because
`bw2calc` 2.5.0 requires only `matrix_utils>=0.6` with no upper bound, and an
unbounded upgrade could jump to a major version the pinned stack was never run
with. Earlier interim workarounds — a runtime monkeypatch of
`ArrayMapper.map_array`, and a hand-edit of the library source — are both
**superseded and removed**; if you find either in old code, delete it.

Note `matrix_utils` is a **bw25** dependency (pulled by `bw2calc`), not a
`deala`/`brightway2` one. Deala's constraint that actually pins an old library is
`numpy<1.24` (→ numpy 1.23.5), unrelated to this crash.

Validated environment: scipy 1.13.1, numpy 1.23.5, matrix_utils 0.6.3,
bw2calc 2.5.0, bw2data 4.7, brightway2 2.4.7, brightway25 1.1.1, deala 1.2.1.

## The injection pattern

Two habits prevent the classic bugs:

**Idempotent copy.** `activity.copy()` mints a new object every call, so
re-running a loop accumulates duplicates. Delete-then-copy on a stable name:

```python
def fresh_deala_copy(source_activity, new_name):
    for old in [a for a in deala_modular_db if a["name"] == new_name]:
        old.delete()
    na = source_activity.copy()
    na["name"] = new_name
    na.save()
    return na
```

**Snapshot before adding.** Iterating `activity.exchanges()` *while* adding
exchanges re-matches the ones you just added — an added
`transport, freight train` link matches the `transport, freight train` pattern on
the next pass. Always `for exc in list(new_activity.exchanges()):`.

Country resolution is **country-first with a GLO fallback**, matched **exactly**
on both name and location, and a selector that finds nothing or more than one
raises rather than guessing. `dh.pick_deala(db, label, country)` is this:

```python
def pick_deala(db, label, country):
    for loc in (country, "GLO"):
        hits = [a for a in db if a["name"] == label and a["location"] == loc]
        if len(hits) > 1:
            raise ValueError(f'{len(hits)} DEALA activities named "{label}" at {loc}; '
                             "expected exactly one")
        if hits:
            return hits[0]
    raise ValueError(f'No DEALA activity found for "{label}" ({country} or GLO)')
```

Why exact, and why raise on two hits even when today's data gives one:

- **Substring matches collide.** DEALA's electricity labels share long
  prefixes (`Non-household, 20-499 MWh` against `Non-household, 2000-19999
  MWh`), and a location test like `country in a["location"]` matches any
  location containing those letters.
- **`[0]` hides a second hit.** The GLO proxy pattern below *writes* into the
  same database this selector searches. Once you create activities in the
  database your own selector reads, a substring-plus-`[0]` selector can start
  returning your own copy, or the older of two, with no error. A substring +
  `[0]` transport selector has silently changed a result this way before.

Match the process's country on `'{XX}'` (with braces), not the bare code —
`'AT'` is a substring of `"at farm"` and will collide.

### Cost mappings are methodological choices — ask, don't default

Every row below is a decision the user makes for their own inventory. The
middle column names the DEALA activity *family* to search, not a pick. Tier,
category and proxy choice all change the answer, so put each one to the user
and record what they chose.

| Flow | DEALA activity family | What to ask |
|---|---|---|
| Electricity | `electricity - Non-household, <band> MWh` | which consumption band: compute it per step from the plant's annual use ("Electricity: the consumption band" below), not one band for every step |
| Gas heat | `gas - non-household, <band> GJ` | which band; what proxy for a country DEALA has no gas price for; whether a country's data is sector-based rather than banded |
| Solvents | `consumables and supplies - solvent, organic` (GLO) | whether one proxy may stand for several solvents |
| Wastewater | `waste treatment - waste water, industrial` (GLO) | the unit conversion (m³ → kg is a factor of 1000) |
| Tap water | `consumables and supplies - Tap water production` (GLO) | |
| Freight | DEALA foreground transport (GLO, or country where it exists) | mode per leg |
| Labour | `personnel - <category>` (h) | which category; the rate in h/tonne and its source; hours = rate × production_kg / 1000 |

Some flows have no suitable DEALA activity, or are negligible, and are left
unpriced: agree that list with the user and state it. Land and overheads are
not priced by these helpers at all, and capital only if you add it (see
"Capital" below). If a user asks for "full cost", list what is absent rather
than implying the number is complete.

**The GLO proxy pattern.** When a country has no price, build an explicit proxy
activity rather than letting the fallback pick something arbitrary: copy a
covered country's activity, set `location='GLO'`, overwrite the biosphere price
amount with the computed average, and write the derivation into `comment` so the
choice is auditable. Compute the average from the **imported DB exchange
amounts** (already currency-adjusted), not from raw source JSON, so it is
consistent with every other DEALA activity. Make it idempotent by deleting any
existing GLO entry first.

## Prices deala doesn't ship: patch a private copy

deala prices from JSON tables inside its installed package (`files/`). When a
study needs a price deala lacks, **never edit those files in
`site-packages`**: the results would then depend on a hand-edited install that
no other machine has, and `check_environment.py` reports it as modified.
Copy the tree into the project and patch the copy (`scripts/deala_prices.py`):

```python
import deala_prices as dp

mirror = dp.mirror_deala_files("deala_mirror")      # rebuilt from scratch each run
dp.add_price_rows(mirror, rows, elasticity_rows=elast_rows)
# later: repository_main_path=mirror  (the PARENT of files/, not files/ itself)
```

- **Rows copy the table's own shape.** Each new row needs the fields in
  `dp.MATERIAL_FIELDS`; build it from an existing row of the same kind so
  every field deala reads (`REMIND Region` above all, which drives the GDP
  projection) is filled the way deala's own rows are. Give new rows a
  distinctive `Code`: `add_price_rows` removes any earlier row with the same
  code first, so a re-run replaces instead of duplicating.
- **Give every new material an elasticity row.** deala matches elasticity on
  `(Sector, Type, ISO)` and does not reset the value between datasets, so a
  row matching nothing silently inherits the exponent of whichever dataset
  matched last. Ask the user what the exponent should be (for a globally traded
  commodity, 0 is a defensible choice; say why).
- **The JSON is written as escaped ASCII**, because deala reads it with the
  machine's locale encoding. UTF-8 names turn into mojibake on some machines.
- **GDP workbooks.** deala needs one per scenario, matched by file stem, and a
  pip install does not ship all of them. A missing one fails much later as a
  bare `KeyError` on the scenario name. `dp.missing_gdp_scenarios(mirror,
  scenarios)` checks up front; add missing workbooks to the mirror's
  `files/GDP`.

## The cost year: the user's choice, and not a no-op

`dp.import_price_databases(deala_io_instance, cost_year=..., base_year=...,
repository_main_path=mirror)` builds deala's priced activity databases from
the mirror. **`cost_year` and `base_year` have no default: ask the user for
both.**

- `base_year` is the **currency year**: prices come out in USD of that year.
- `cost_year` is the **cost horizon**: the year every price is projected to.
  It is easy to leave at a far-future value by accident, which pairs a future
  cost against a present-day footprint.

deala projects each dataset from **its own Base Year**, by
`GDP[region][cost_year] / GDP[region][dataset Base Year]` raised to an
elasticity. So a cost year equal to the currency year is a no-op only for
datasets whose own Base Year is that year. Datasets with an earlier Base Year
(often gas, freight, water) are still projected forward across the gap. Report
it as a short projection, not a pass-through.

`import_price_databases` also refuses to run while the project holds any other
database whose name contains "DEALA" (deala would delete it), and rebuilds the
price databases only when a fingerprint of the mirror and the years changes.
Don't guard the rebuild with "if the database exists, skip": a corrected price
in the mirror would then have no effect on anything.

## Electricity: the consumption band

Eurostat prices non-household electricity in seven bands of annual
consumption (`dp.EUROSTAT_BANDS`, IA to IG), and a large consumer pays less per
kWh than a small one. One band for every step is wrong whenever the plants
differ in size, and the band can decide which country wins.

Compute the band per step from that plant's own annual use:

```python
kwh_per_kg = dp.electricity_per_kg(activity)           # all electricity inputs
mwh = dp.annual_mwh(kwh_per_kg, capacity_t_per_h, hours_per_year)
elec_act, record = dp.pick_electricity(deala_db, country, mwh)
provenance.append(record)
```

- **Capacity and operating hours are the user's inputs**, per plant. Ask; don't
  assume. If a step has no capacity of its own (it shares a plant, say), agree
  the assumption with the user and write it down.
- `pick_electricity` tries the country's own row in the computed band, then
  its nearest band that exists (one down, one up, two down, ...), then GLO in
  the computed band, and raises if none exists. The returned `record` says
  which one fired. Keep the records as a provenance table and show the user
  where a fallback fired: a fallback is a fact about the price table, not an
  error.

## Capital: feed the upfront cost, never an annualised one

deala prices equipment capital through a depreciation flow that spreads the
capital cost over its lifetime: in deala 1.2.1 that flow scores 1/25 USD per
USD of capital, i.e. straight-line over 25 years. So:

- **Feed deala the upfront (undepreciated) equipment cost per kg of annual
  capacity**, multiplied by the activity's production amount:
  `amount [USD] = upfront_cost / (capacity_t_per_h × 1000 × hours_per_year) × production_kg`.
- **Never feed a figure that is already spread over the years** (a "USD/kg,
  depreciated" column from an equipment workbook, say). deala annualises it
  again, and capital comes out 25 times too small.
- The depreciation flow is GLO-only and does not vary by country. If capital
  cost should vary by country, that variation has to come from the amount (a
  location factor the user supplies and cites); say so in the methods.

Every number here — the equipment cost, the capacity, the hours, any location
factor — comes from the user. Ask for each, and for its source.

## Allocation is decided per process: ask

When one plant makes several products, whether and how its cost is allocated
between them is a methodological choice, and it is made **per process**, not
once for the study:

- Allocate only the steps that are actually multi-output. A single-product
  step gets no allocation factor.
- Don't assume one constant ratio even for one kind of step. Where the ratio
  depends on the activity (its production amount, its region), look it up per
  activity and **raise on a value you have no ratio for**, rather than falling
  back to a default.
- Use the same allocation basis (economic or mass) as the environmental side,
  or state plainly why they differ.

Put each choice to the user, with the options and what each would change, and
record the answer next to the code that applies it.
