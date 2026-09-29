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

It writes datapackages (~720 MB here) to `processed/`, **not** to the multi-GB
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

```bash
pip install --no-deps "matrix_utils==0.6.3"
```

Pinned `==` with `--no-deps` deliberately: `bw2calc` 2.5.0 requires only
`matrix_utils>=0.6` with no upper bound, so an unbounded upgrade could jump to
3.x and break the pinned bw2calc 2.5 stack. Earlier interim workarounds — a
runtime monkeypatch of `ArrayMapper.map_array`, and a hand-edit of the library
source — are both **superseded and removed**; if you find either in old code,
delete it. `deala_helpers.check_environment()` enforces the floor.

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

Country resolution is **country-first with a GLO fallback**, and a selector that
returns nothing raises rather than guessing:

```python
def pick_deala(label, country):
    hits = [a for a in deala_ssp2_npi if label in a["name"] and country in a["location"]]
    if not hits:
        hits = [a for a in deala_ssp2_npi if label in a["name"] and "GLO" in a["location"]]
    if not hits:
        raise ValueError(f'No DEALA activity for "{label}" ({country} or GLO)')
    return hits[0]
```

Match the process's country on `'{XX}'` (with braces), not the bare code —
`'AT'` is a substring of `"at farm"` and will collide.

### Cost mappings are methodological choices — ask, don't default

Every row below is a decision the user makes for their own inventory. The
middle column names the DEALA activity *family* to search, not a pick. Tier,
category and proxy choice all change the answer, so put each one to the user
and record what they chose.

| Flow | DEALA activity family | What to ask |
|---|---|---|
| Electricity | `electricity - Non-household, <band> MWh` | which consumption band: compute it from the plant's annual use rather than picking one band for every step |
| Gas heat | `gas - non-household, <band> GJ` | which band; what proxy for a country DEALA has no gas price for; whether a country's data is sector-based rather than banded |
| Solvents | `consumables and supplies - solvent, organic` (GLO) | whether one proxy may stand for several solvents |
| Wastewater | `waste treatment - waste water, industrial` (GLO) | the unit conversion (m³ → kg is a factor of 1000) |
| Tap water | `consumables and supplies - Tap water production` (GLO) | |
| Freight | DEALA foreground transport (GLO, or country where it exists) | mode per leg |
| Labour | `personnel - <category>` (h) | which category; the rate in h/tonne and its source; hours = rate × production_kg / 1000 |

Some flows have no suitable DEALA activity, or are negligible, and are left
unpriced: agree that list with the user and state it. Capital,
land, facility/equipment depreciation and overheads are **deferred pending data**
— if a user asks for "full cost", say plainly that these are absent rather than
implying the number is complete.

**The GLO proxy pattern.** When a country has no price, build an explicit proxy
activity rather than letting the fallback pick something arbitrary: copy a
covered country's activity, set `location='GLO'`, overwrite the biosphere price
amount with the computed average, and write the derivation into `comment` so the
choice is auditable. Compute the average from the **imported DB exchange
amounts** (already currency-adjusted), not from raw source JSON, so it is
consistent with every other DEALA activity. Make it idempotent by deleting any
existing GLO entry first.
