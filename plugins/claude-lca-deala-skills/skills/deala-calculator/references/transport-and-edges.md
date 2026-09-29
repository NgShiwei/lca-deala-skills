# Transport cost, edge weights, and the graph handoff

Per-process costs are per kg *at the gate*. Turning them into a supply-chain
pathway needs two more things: the cost of moving product between countries, and
the scaling factor that converts each step's per-kg cost into a contribution to
one kg of final product.

## Freight rates

The three DEALA foreground freight activities are scored like any other input —
alone, FU `{act.id: 1}` — which returns USD per tonne-kilometre.

```python
rates = dh.transport_rates()      # {(mode, location): USD/tkm}
```

Country-specific rates exist only for **CN, DE, SE**; every other origin or
destination falls back to **GLO**.

**Sanity anchors (GLO, validated):** lorry `0.207`, train `0.097`, sea `0.0032`
USD/tkm. Sea being ~65× cheaper than road per tonne-km is the expected shape; if
your rates don't show that ordering, something is mis-linked.

## Route model

From `seadistance.csv` (ISO3 country pairs), per pair:

- **Neighbours** (`short == 1`): road only, over `roaddistance`.
- **Otherwise**, three legs:
  1. origin capital → origin port (`capitalport1`), land
  2. sea leg (`seadistance`), container ship, non-hazardous
  3. destination port → destination capital (`capitalport2`), land
- **Same country**: 0.

**Land-mode tiering (LOCKED):** a land leg ≤ **800 km** goes by road (lorry
>32 t, EURO6); longer than that, by rail. `RAIL_THRESHOLD_KM = 800`.

**Rate keying:** legs 1 and 2 use the **origin** country's rate; leg 3 uses the
**destination** country's. (Only matters when one end is CN/DE/SE.)

**Units:** built per tonne, then divided by 1000 → **USD/kg**, matching the
per-kg basis of the emission table. Getting this wrong is a silent 1000× error
that still produces a plausible-looking graph, so check one pair by hand.

```python
transport = dh.build_transport_table(rates, "seadistance.csv", country_list, iso2_to_iso3)
```

Expect `n²` pairs for `n` countries, same-country rows all 0, no NaN.

## Edge-weight formula

Identical to the environmental notebook's, with cost substituted for GWP — which
is exactly what makes the two tables mergeable into a combined objective:

```
same country:   weight = scale × process_cost
cross country:  weight = scale × (process_cost + transport_cost)
```

`scale` is the **reverse cumulative product** of per-step input/output mass
ratios, read from the scaling-factor CSV (one bracketed list per country) and
exploded against `process_order` (the modular steps, in order). It converts
"cost per kg of *this* step's output" into "cost contribution per kg of *final*
product", so upstream steps are weighted by how much of them one kg of the final
product consumes.

Note the asymmetry: transport is added **before** scaling, so it is scaled too —
transport of an upstream intermediate is likewise charged per kg of final
product.

```python
edges = dh.build_edge_table(
    cost_results, transport,
    scaling_csv="scaling_factors.csv",
    process_order=process_order, countries=country_list,
    score_col="calculated_cost")
edges.to_csv("calculated_costs_subset.csv", index=False)
```

Gate before continuing: **0 NaN** in `scale` and in the score column. A NaN scale
means a `(country, process_base)` pair failed to merge — usually a name-parsing
mismatch, not missing data. `dh.parse_names()` uses the same regexes as the
environmental pipeline precisely to prevent this.

Expect one row per (origin, step, destination): for `n` countries and `k`
steps that can all be done everywhere, `n × k × n`.

## Handoff to `supply-chain-optimizer`

The edge table is the contract between the two skills. The graph skill's
`score_col` is pluggable, so the same machinery solves the environmental path,
the cost path, or a pre-combined objective:

```python
import graph_helpers as gh          # see the note below on where this comes from

G, s, t = gh.build_layered_graph(edges, score_col="calculated_cost",
                                 process_order=process_order)
path, total = gh.solve_shortest_path(G, s, t)
print(gh.format_pathway(G, path))
gh.plot_network(G, "costs_network_with_labels.png", title="DEALA cost network")
```

**Do not reach into the skill folder with a `sys.path.insert` of an absolute
path.** That is what this file used to show, and it makes the consuming script
unrunnable on any other machine, and dead the moment the skill is uninstalled.
`build_layered_graph` + `solve_shortest_path` are about 60 lines: copy them into
the script that needs them and keep the node/edge/layer contract identical. Only
the fuller extras (`format_pathway`, `plot_network`, the CLI) are worth importing
rather than copying, and only when the skill is genuinely present.

or from the shell:

```bash
py graph_helpers.py --edges calculated_costs_subset.csv \
   --score-col calculated_cost --process-order process_order.txt \
   --png costs_network_with_labels.png
```

Nodes are `(layer, country)` between a generic `START` and a generic `END` sink —
the answer is the **globally** lowest pathway, not one tied to a destination
market. Constraining the start or end node instead answers "what does it cost if
I insist on sourcing from X", which is usually the more interesting question.

Cost and emissions are solved as *separate* objectives and usually pick
*different* winners. A combined objective must therefore be an explicit
methodological choice, not an average taken silently.
