---
name: supply-chain-optimizer
description: >-
  Find the globally lowest-impact supply chain by turning per-process,
  per-country impact scores into a layered networkx.DiGraph and solving
  nx.shortest_path from a generic START to a generic END sink. Use whenever the
  work involves assembling a modular/layered supply-chain graph and picking the
  cheapest end-to-end pathway across countries and process steps: building
  edge-weight tables (process score x scaling factor + inter-country transport),
  constructing the layered DiGraph, running the shortest path, or plotting the
  network. The edge-driving score column is pluggable: environmental (GWP),
  economic (DEALA total cost), or a pre-combined objective, since the graph
  machinery is identical.
---

# Supply-chain path optimizer

Assemble a layered supply-chain network from per-process, per-country impact
scores and solve for the globally lowest-impact pathway. Built for a modular
cut-off LCA pipeline (environmental *and* DEALA-economic optimization), and
generic to any layered process chain scored per country.

The engine is in `scripts/graph_helpers.py`; it is both importable and runnable
as a standalone CLI, so it can drive a notebook, a separate agent, or a
sequential batch run.

**Consumers should copy the builder, not import it across an absolute path.**
`build_layered_graph` + `solve_shortest_path` are about 60 lines. A
`sys.path.insert(0, "/absolute/path/to/.claude/skills/...")` in a project script makes that
script unrunnable on any other machine and dead the moment the skill is
uninstalled. Vendor them into the project's own code instead, so the project
no longer imports this skill at all.

This file keeps the fuller original — `format_pathway`, `plot_network`, and the
CLI — so it is still the place to look. What must **not** drift between the two
is the node/edge/layer contract below: a copy that changes which edge carries
which process score returns a different answer without erroring.

**Licensed data.** The rules in the `lca-calculator` skill's "Licensed data"
section apply here too: never ask for the ecoinvent password in chat, the user
stores credentials in their own terminal, never read a licensed export whole,
and never commit licensed data or anything derived from it row for row.

## The one idea that makes it reusable

**The score that drives the edges is a single, swappable column.** Everything
else — the node layout, the START/END wiring, the shortest-path call — is
identical whether you are minimizing emissions, cost, or a combined objective.
Point `--score-col` (or the `score_col` argument) at:

- an **environmental** column (e.g. `calculated_emission`, kg CO2e) -> lowest-GWP chain;
- an **economic** column (e.g. `calculated_cost`, USD) -> lowest-cost chain;
- a **combined** column you pre-compute (normalized emission + cost, weighted).

Run it twice with two columns to compare paths; add one pre-combined column for a
single joint objective. No graph code changes.

## The node / edge / layer contract

Keep this exact in every copy of the builder, so results stay reproducible:

- **Node key = `(layer, country)`.** Layer 0 = a single generic `START`; layers
  `1..N` = the `N` processes in `process_order`, one node per country per layer;
  layer `N+1` = a single generic `END`. The process lives in the node's `process`
  attribute; the layer index carries the step order.
- **START -> every layer-1 country node**, weight `start_weight` (default `0`):
  the origin country is chosen freely by the optimizer.
- **Inter-layer edge `(i, from) -> (i+1, to)`** carries the **source** layer's
  process score: `lookup(process_order[i-1], from, to)`. A **missing lookup
  omits the edge**; it is never charged `0.0`. A country with no row for a step
  cannot perform it, and a free edge would let it win by having no data. Key on
  absence, not value: a weight of exactly `0.0` that *is* in the table keeps its
  edge.
- **Every layer-N country node -> END** carries the final process' *same-country*
  score `lookup(process_order[-1], c, c)`.
- **Same-country transport = 0.** Intra-step (within-country) transport is
  already embedded in the process score, so inter-country transport is added
  only when `from != to`. Build your edge table so the score column already
  encodes `scale * (process + transport)` for `from != to` and `scale * process`
  for `from == to` (see `references/graph-construction.md`).

Because START->L1 is free and the final process is charged on the L-N->END edge,
`shortest_path(START, END)` freely selects the cheapest end-to-end country
routing — the *global* lowest pathway, not one pinned to any country.

## Workflow

1. **Get per-process, per-country scores.** Use the `lca-calculator` skill to
   score each modular cut-off process in isolation (environmental method, or a
   DEALA cost metric). One value per (process, country).
2. **Build the edge table.** Merge scores x cumulative scaling factor x
   inter-country transport into one tidy CSV keyed by
   `(process_base, country=from, to_country)` with a numeric score column. The
   formula and the transport-leg model are in
   `references/graph-construction.md`.
3. **Construct + solve.** `build_layered_graph(edge_df, score_col, process_order)`
   then `solve_shortest_path(G, start, end)`. `process_order` has no default:
   ask the user for the study's steps in supply-chain order. Or run the CLI:
   `python scripts/graph_helpers.py --edges <edges.csv> --score-col <col> --process-order <order.txt> --png <out.png>`.
4. **Report.** `format_pathway(G, path)` prints the step-by-step
   `(layer, country, process)` breakdown with per-edge weights and the total;
   `plot_network(G, png)` saves the layered diagram.

## Bundled resources

- `scripts/graph_helpers.py` — `build_layered_graph`, `solve_shortest_path`,
  `format_pathway`, `plot_network`, and a `__main__` CLI. Importable or
  standalone.
- `references/graph-construction.md` — the edge-weight formula, the inter-country
  transport-leg model, the exact layer indexing to preserve, and the
  combined-objective extension (normalize each score, weighted sum).

## When something looks off

- **`NetworkXNoPath` from START to END:** the score column is empty or the
  `process_base` labels in the edge table don't match `process_order`, so every
  lookup missed and every inter-layer edge was omitted. Print the unique
  `process_base` values and compare to `process_order`.
- **A country you expected is never on any path:** it has no rows for an early
  step, so it has no outgoing edge there. That is the builder working as
  intended; check the edge table, not the graph.
- **The path pins to one country everywhere:** usually correct (transport
  dominates, so staying put after the cheapest origin wins). Confirm by checking
  the per-edge weights in `format_pathway`.
- **Costs shifted vs a known baseline:** the layer indexing changed. The final
  process is charged on the last-layer -> END edge (same-country), *not* an
  inter-layer edge; a trailing pass-through process layer with no score rows is
  expected to contribute `0`.
