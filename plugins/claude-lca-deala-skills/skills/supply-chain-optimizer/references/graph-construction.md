# Graph construction reference

The complete recipe for turning per-process, per-country scores into the layered
DiGraph and solving it. The structure is generic. For a complete worked run with
numbers you can check by hand, see `../../../examples/toy-chain/` (three invented
countries, three steps, runs offline).

## 1. The edge table

One tidy row per `(process_base, from_country, to_country)` with a numeric score
column. Columns the helpers expect (names overridable):

| column | meaning |
|---|---|
| `process_base` | process/step label; must match an entry in `process_order` |
| `country` | the **from** country (origin of this leg) |
| `to_country` | the **to** country (destination of this leg) |
| `<score_col>` | the edge weight, e.g. `calculated_emission` or `calculated_cost` |

Build it by merging three inputs:

1. **Per-process score** — one value per (process, country), from scoring each
   modular cut-off activity in isolation (see `lca-calculator`). Cut-off
   activities zero their upstream, so each score is that step's own impact.
2. **Cumulative scaling factor** `scale` — per (country, process), the reverse
   cumulative product of per-step input/output mass ratios. Parsed from the
   scaling-factor CSV (one bracketed list per country) and assigned
   positionally to the process order.
3. **Inter-country transport** — per (from, to), the transport impact of moving
   one unit of product between countries (see §3). Same-country = 0.

## 2. The edge-weight formula

```
weight = where(from == to,  scale * process_score,
                            scale * (process_score + transport))
```

Same-country legs carry no transport term (intra-step transport is already in the
process score). Keep both units consistent (per kg of product): if the process
score is per kg, the transport term must be per kg too.

## 3. Inter-country transport model (economic layer)

For the DEALA cost layer, transport is a **multi-leg** move priced per
tonne-kilometre and then normalized to per kg. Distances come from
`seadistance.csv` (ISO3 pairs: `seadistance`, `capitalport1`, `capitalport2`,
`roaddistance`, `short`):

- `short == 1` (no international sea leg): land only over `roaddistance`.
- otherwise: origin capital -> port (`capitalport1`, land) + port -> port
  (`seadistance`, sea) + port -> destination capital (`capitalport2`, land).

Per leg: `tonne_km (= km for 1 tonne) x DEALA_rate(mode, location)`, summed, then
`/1000` for per-kg. Land mode by leg distance: **road (lorry) <= 800 km, rail
(train) > 800 km**. Sea = container ship, non-hazardous. Rate location: legs 1-2
keyed to the **origin** country, leg 3 to the **destination** (country-specific
DEALA rate where DEALA has one; otherwise GLO). Same-country pair -> 0.

(The environmental layer uses a pre-computed per-kg transport-emission table with
the same from/to shape; only the numbers differ.)

## 4. Node / layer layout (must preserve)

`process_order` is the study's `N` real steps plus a trailing "at market"
pass-through layer, `N + 1` entries in all. The edge table carries only the `N`
real `process_base` values, so the pass-through layer's lookups resolve to `0.0`
(a free pass-through to END). This is intentional and must be kept, or per-step
charges shift:

- The **first** step's cost is charged on the L1->L2 edge (source layer = step 1).
- The **last real** step's cost is charged on the L`N`->L`N+1` edge.
- The L`N+1`->END edge (final `process_order[-1]`, same-country) resolves to `0.0`.

`build_layered_graph` reproduces exactly this: START at layer 0, processes at
layers 1..N, END at layer N+1; inter-layer edges use the source layer's score;
the last real layer -> END uses the final process' same-country score.

**Missing rows omit the edge; they are not free.** An inter-layer edge is added
only when its `(process, from, to)` row exists in the edge table. A country with
no data for a step (for example, a country that processes but does not grow the
crop) therefore has no outgoing edge at that layer, and the graph prunes it
without any assertion. The single exception is the pass-through layer -> END
edge above, which keeps its `0.0` default: that layer has no data by design, and
gating it would leave no path at all.

An earlier version of this builder charged `0.0` for every missing lookup. On
a real study with downstream-only countries that version returned a far lower,
wrong optimum, by routing through a country that got the upstream steps for
free. `tests/test_graph_contract.py` guards the rule.

## 5. Solve + report

```python
from graph_helpers import build_layered_graph, solve_shortest_path, format_pathway, plot_network
G, s, t = build_layered_graph(edge_df, score_col="calculated_cost",
                              process_order=process_order)
path, total = solve_shortest_path(G, s, t)      # Dijkstra on weight="weight"
print(format_pathway(G, path))                   # per-edge breakdown + total
plot_network(G, "costs_network.png")
```

`nx.shortest_path(..., weight="weight")` uses Dijkstra (all weights are >= 0). The
total is recomputed by summing edge weights along the returned path as a check.

## 6. Combined objective (future extension)

To minimize cost and emissions jointly instead of separately:

1. Build both edge tables (same from/to/process keys), giving `calculated_cost`
   and `calculated_emission` per edge.
2. Normalize each to a common scale (e.g. divide by its column max, or z-score),
   because USD and kg CO2e are not comparable raw.
3. Add a weighted column `combined = w_cost * norm_cost + w_env * norm_env` with
   user-chosen weights, and pass `score_col="combined"`.

The graph, nodes, and shortest-path call are unchanged — only the pre-computed
column differs. Ask the user for the weights and normalization; do not assume.
```
