# Brightway 2.5 patterns — the 10 steps as code

Concrete, copy-adaptable snippets. Activity/database names are examples — replace
with the ones in the user's project. The functions referenced (`fresh_copy`,
`run_multilca`, …) live in `scripts/lca_helpers.py`.

## 0. Run from the activated conda environment, not just its interpreter

Brightway lives in a conda environment (`env_bw25` on the machine this was built
on). **Pointing at that environment's `python.exe` is not enough.** `bw2calc`'s
`.lci()` calls `scipy.sparse.linalg.spsolve`, which delay-loads a DLL out of the
environment's `Library\bin`. Without the environment on `PATH`, the process dies
with Windows fatal exception `0xc06d007f` — a hard crash, no Python traceback, no
line number.

It reads as a data problem, and it is not. Everything *before* the solve works
fine: imports, iterating a database, creating activities, `process()`. Only
`.lci()` dies. So the failure lands nowhere near its cause.

Activate the environment, or prepend all of these to `PATH`:

```
<env>;<env>\Library\bin;<env>\Library\mingw-w64\bin;<env>\Library\usr\bin;<env>\Scripts
```

## 1. Set up

```python
import bw2data as bd
import bw2calc as bc
import bw2io as bi
import bw2analyzer as bwa
import pandas as pd
import numpy as np

bd.projects              # summary of projects
bd.projects.set_current("<project>")
list(bd.databases)       # what's available in this project
```

## 2. Manage databases (copy before editing; delete deliberately)

```python
# Make a working copy so the source stays pristine:
bd.Database("<source db>").copy("<source db>_working")   # never "DEALA" in the name

# Delete a stale working database (IRREVERSIBLE — confirm the name first):
del bd.databases["<working name>"]

# Bind handles:
mod_db  = bd.Database("<working db>")                                 # working copy
eidb    = bd.Database("ecoinvent-3.10-cutoff")                        # reference
```

Never edit a reference database (ecoinvent, Agri-footprint) directly. See
`working-databases-and-cleanup.md`.

## 3. Inspect activities & exchanges

```python
# Find by name (+ location). Guard against picking a broken/previous copy:
act = [a for a in mod_db
       if "<process name>, at processing" in a["name"]
       and a.get("location") == "AT"
       and not a["name"].startswith(("Cutoff", "DEALA"))][0]

# List exchanges with type and amount:
for e in act.exchanges():
    print(e.get("type"), e["amount"], e.get("unit"), "|", e.input["name"])

# Structure of the supply chain:
bwa.print_recursive_supply_chain(act, max_level=1)
```

Exchange types: `production` (the activity's own output), `technosphere`
(inputs from other activities), `biosphere` (elementary flows / emissions),
and — for economic layering — `marketsphere` (cost flows).

## 4. Edit exchanges (add / change / delete)

```python
# Add an input exchange (e.g. a cost or a substituted input):
act.new_exchange(name=other["name"], input=other, amount=12.3,
                 unit="kilogram", type="technosphere").save()

# Change or zero an amount (cut-off: zero the upstream input, keep the process):
for e in act.exchanges():
    if "<upstream input name>" in e["name"].lower():
        e["amount"] = 0
        e.save()

# Delete an activity (and its exchanges):
act.delete()
```

**Snapshot before adding inside a loop** — otherwise you re-match what you add:

```python
for e in list(act.exchanges()):        # list() = fixed snapshot
    if pattern in e["name"].lower():
        act.new_exchange(...).save()
```

## 5. Define the impact method

```python
# Namespace m[0] MUST match the biosphere version the inventory uses.
key = [m for m in bd.methods
       if m[0] == "ecoinvent-3.10"
       and m[1] == "IPCC 2021"
       and m[2] == "climate change"
       and m[3] == "global warming potential (GWP100)"][0]
config = {"impact_categories": [key]}
```

Default to IPCC 2021 GWP100. For anything else, query first and ask the user —
see `method-selection.md`. Multiple keys are allowed in `impact_categories`, but
a scalar optimization (shortest-path edge weight) needs a single one.

## 6. Define the functional unit(s)

```python
# One functional unit per activity, each demanding `amount` of its own output:
codes = [a.get("code") for a in mod_db if "Cutoff NP" in a["name"]]
fu = {mod_db.get(c)["name"]: {mod_db.get(c).id: 1} for c in codes}
```

Format is `{label: {activity.id: amount}}`. The label becomes part of the score
key, so make it identifying (the activity name is a good choice).

## 7. Construct the matrices

```python
data_objs = bd.get_multilca_data_objs(functional_units=fu, method_config=config)
```

This assembles the shared technosphere (A), biosphere (B), and characterization
datapackages for every functional unit and method.

## 8. Run the evaluation

```python
mlca = bc.MultiLCA(demands=fu, method_config=config,
                   data_objs=data_objs, use_distributions=False)
mlca.lci()    # build & solve the inventory
mlca.lcia()   # apply characterization -> scores
```

`use_distributions=True` switches on Monte Carlo (needs uncertainty data).

## 9. Save as a DataFrame

```python
df = pd.DataFrame.from_dict(mlca.scores, orient="index")   # index = (method, fu_name)
df.to_csv("lca_results.csv")
```

Steps 5–9 collapse to one call if you don't need the intermediate objects:

```python
from lca_helpers import run_multilca
df, mlca = run_multilca(fu, [key])
```

## 10. Show / plot results

Display the DataFrame first. Plot only what the user asks for — don't guess a
chart type. Common asks:

```python
# per-activity bar (parse country/step from the fu label as needed)
df["score"].sort_values().plot.barh()

# contribution of one activity:
bwa.ContributionAnalysis()  # or recursive_calculation, per project convention
```

For network/pathway visualisations built on the scores (edge = process +
transport emission, `nx.shortest_path` for the lowest-impact chain), follow the
project's existing NetworkX code rather than inventing a new layout.
