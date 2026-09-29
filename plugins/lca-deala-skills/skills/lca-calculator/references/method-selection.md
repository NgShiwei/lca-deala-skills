# Selecting an LCIA method

## Method-key structure

A Brightway method is a **tuple**, usually length 4:

```
( m[0] namespace , m[1] family , m[2] category , m[3] indicator )
```

Example (the default):

```
('ecoinvent-3.10', 'IPCC 2021', 'climate change', 'global warming potential (GWP100)')
```

- **m[0] — namespace.** Ties the method to a biosphere version. A project can
  hold the same family under several versions (e.g. `ecoinvent-3.9.1`,
  `ecoinvent-3.10`, `ecoinvent-3.12`) plus economic families (DEALA). This
  element **must match the biosphere version the inventory is linked to**, or the
  characterization factors won't align with the flows and the score is wrong.
  Omitting this filter makes selection ambiguous.
- **m[1] — family.** IPCC 2021, ReCiPe 2016 (midpoint/endpoint, H/E/I variants),
  EF v3.0 / v3.1, CML v4.8, Ecological Scarcity 2021, CED, CExD, EDIP 2003, …
  A `" no LT"` suffix means "no long-term emissions".
- **m[2] / m[3] — category and indicator.** e.g. `climate change` /
  `global warming potential (GWP100)`. Read the unit from
  `bd.Method(key).metadata["unit"]`.

## Query what's available

```python
list(bd.methods)                                   # everything
# families under a namespace:
sorted({m[1] for m in bd.methods if m[0] == "ecoinvent-3.10"})
# indicators within a family:
[(m[2], m[3]) for m in bd.methods
 if m[0] == "ecoinvent-3.10" and m[1] == "IPCC 2021"]
```

Or from the shell: `python scripts/query_methods.py --project <p> --version
ecoinvent-3.10 --family "IPCC 2021"` (and `--families` to list families,
`--contains` for free-text search).

## Confirming the namespace (important for Agri-footprint / mixed databases)

The default namespace guess is right for a plainly ecoinvent-3.10 inventory, but a
database can be named for one system (e.g. Agri-footprint) while its flows link to
an ecoinvent biosphere — and several ecoinvent biosphere versions may coexist in
the project. Don't guess; confirm empirically by looking at where an activity's
biosphere flows come from:

```python
from collections import Counter
act = next(a for a in db if NAME in a["name"])
srcs = Counter()
# walk a couple of levels of the supply chain and tally biosphere-flow databases
for e in act.biosphere():
    srcs[e.input["database"]] += 1
print(srcs)   # e.g. {'ecoinvent-3.10-biosphere': 46918, 'Agri-footprint 7.0 new biosphere': 1916}
```

Pick the method namespace matching the dominant biosphere. **Caveat for mixed
databases:** if some flows come from a *different* biosphere (e.g. an Agri-footprint
biosphere alongside ecoinvent), those flows may not be characterized by the chosen
method, so a small part of land-use/biogenic impact can be silently uncounted. Flag
this to the user when it could affect the categories they care about.

## The selection rule

1. Default to **IPCC 2021 GWP100** in the namespace matching the inventory's
   biosphere.
2. If the user wants a different impact (toxicity, land use, water, a full
   ReCiPe set, an endpoint score, …), **query the options and ask** which
   family / category / indicator before hardcoding. Don't assume — the choice
   changes results and is the user's methodological decision.
3. `impact_categories` accepts a list, so multiple methods can be evaluated at
   once. But a scalar optimization (a single shortest-path edge weight) needs
   exactly one; if the user asks for several, clarify whether they want one path
   per method or one method to drive the path.

`find_method(version, family, category=None, indicator=None)` in `lca_helpers.py`
resolves exactly one key or raises with the near-misses listed, so a typo fails
loudly instead of silently selecting the wrong method. Its arguments are in the
**same order as the key itself**, so read a key off `list_methods()` and pass its
parts straight through. For IPCC 2021 GWP100:

```python
key = find_method("ecoinvent-3.10", "IPCC 2021",
                  "climate change", "global warming potential (GWP100)")
# -> ('ecoinvent-3.10', 'IPCC 2021', 'climate change',
#     'global warming potential (GWP100)')
```

It handles both key shapes: pass `category` for a 4-tuple
`(version, family, category, indicator)`, or omit it for a 3-tuple
`(version, family, indicator)` — some single-indicator families (e.g. CED) are
stored as 3-tuples, and hardcoding length 4 would never find them.
