"""graph_helpers.py — layered supply-chain DiGraph + shortest-path optimizer.

Reusable core of the "supply-chain-optimizer" skill. Turns a tidy per-edge score
table (one numeric column per process x from-country x to-country) into a layered
``networkx.DiGraph`` and solves the globally lowest-impact pathway from a generic
START to a generic END sink with Dijkstra.

The *score column* is pluggable: point it at an emission column, a cost column,
or a pre-combined objective column — the graph machinery is identical. This is
what lets one implementation drive both the environmental (GWP) and the economic
(DEALA cost) layers of a modular LCA study, and a combined objective.

Node/edge contract (any copy of this builder must keep it identical, or results
shift without erroring):
  * Node key = ``(layer, country)``. ``layer`` 0 = START, 1..N = the N processes
    in ``process_order`` (one node per country per layer), N+1 = END.
  * START -> every layer-1 country node, weight = ``start_weight`` (default 0:
    the origin country is chosen freely).
  * Inter-layer edge ``(i, from) -> (i+1, to)`` carries the *source* layer's
    process score: ``lookup(process_order[i-1], from, to)``. A missing lookup
    OMITS the edge -- it is never charged 0.0, or a country with no data for a
    step would get that step for free.
  * Every layer-N country node -> END carries the final process' *same-country*
    score ``lookup(process_order[-1], c, c)``.

Because START->L1 is free and the final process is charged on the L-N->END edge,
``shortest_path(START, END)`` freely selects the cheapest end-to-end routing.

CLI:
    python graph_helpers.py --edges calculated_costs_subset.csv \\
        --score-col calculated_cost --process-order process_order.txt \\
        --png costs_network.png

``process_order`` has no default: it is the study's own list of steps, in
supply-chain order, usually with a trailing pass-through layer (see
``references/graph-construction.md``).
"""
from __future__ import annotations

import argparse
from typing import Iterable, Sequence

import networkx as nx
import pandas as pd

def _lookup_table(
    edge_df: pd.DataFrame,
    score_col: str,
    process_col: str = "process_base",
    from_col: str = "country",
    to_col: str = "to_country",
) -> dict:
    """Build a {(process_base, from_country, to_country): score} dict."""
    missing = [c for c in (process_col, from_col, to_col, score_col) if c not in edge_df.columns]
    if missing:
        raise KeyError(f"edge table missing columns {missing}; has {list(edge_df.columns)}")
    tbl = {}
    for proc, fc, tc, val in zip(
        edge_df[process_col], edge_df[from_col], edge_df[to_col], edge_df[score_col]
    ):
        if pd.notna(val):
            tbl[(proc, fc, tc)] = float(val)
    return tbl


def build_layered_graph(
    edge_df: pd.DataFrame,
    score_col: str,
    process_order: Sequence[str],
    countries: Iterable[str] | None = None,
    start_weight: float = 0.0,
    process_col: str = "process_base",
    from_col: str = "country",
    to_col: str = "to_country",
):
    """Assemble the layered DiGraph. Returns (G, start_node, end_node)."""
    if countries is None:
        countries = sorted(set(edge_df[from_col].dropna().unique()))
    countries = list(countries)
    lut = _lookup_table(edge_df, score_col, process_col, from_col, to_col)

    G = nx.DiGraph()
    start_node = (0, "START")
    G.add_node(start_node, layer=0, process="START", country="START")
    for i, proc in enumerate(process_order):
        layer = i + 1
        for c in countries:
            G.add_node((layer, c), layer=layer, process=proc, country=c)
    n = len(process_order)
    end_node = (n + 1, "END")
    G.add_node(end_node, layer=n + 1, process="END", country="END")

    # START -> layer 1 (free choice of origin country)
    for c in countries:
        G.add_edge(start_node, (1, c), weight=start_weight)

    # Inter-layer edges: source layer's process score, from->to country.
    #
    # OMIT the edge when the lookup MISSES. An absent (process, from, to) row
    # means the source country cannot perform that step, and charging it 0.0
    # would hand that country the step for free -- it would win by having no
    # data. On a real multi-country study the old 0.0 default returned a far
    # lower, wrong optimum by routing through a country with no upstream data.
    #
    # Only the SOURCE side is gated. An edge (i+1, f) -> (i+2, t) carries
    # process_order[i] performed IN f and shipped f->t. Gating the source makes
    # the graph self-prune: a country with no upstream data has no outgoing
    # edge below its entry layer, so Dijkstra cannot route through it.
    #
    # Key on ABSENCE, never on value. A weight of exactly 0.0 that is PRESENT
    # in the table is a legitimately free step and must keep its edge.
    #
    # A project that vendors this loop must keep its copy identical;
    # tests/test_graph_contract.py checks the behaviour.
    _MISSING = object()
    for i in range(n - 1):
        proc = process_order[i]
        for fc in countries:
            for tc in countries:
                w = lut.get((proc, fc, tc), _MISSING)
                if w is _MISSING:
                    continue
                G.add_edge((i + 1, fc), (i + 2, tc), weight=w)

    # Final layer -> END: final process, same-country.
    #
    # The 0.0 default STAYS here, deliberately. process_order[-1] is a trailing
    # pass-through layer with no data by design -- the last real step is charged
    # on the layer N-1 -> N edge and layer N -> END is free. Gating this edge on
    # absence would strip every route's exit to END and leave no path at all.
    last = process_order[-1]
    for c in countries:
        G.add_edge((n, c), end_node, weight=lut.get((last, c, c), 0.0))

    return G, start_node, end_node


def solve_shortest_path(G, source, target, weight: str = "weight"):
    """Dijkstra shortest path. Returns (path, total_weight)."""
    path = nx.shortest_path(G, source=source, target=target, weight=weight)
    total = sum(G[u][v][weight] for u, v in zip(path[:-1], path[1:]))
    return path, total


def format_pathway(G, path, weight: str = "weight") -> str:
    """Human-readable step-by-step breakdown of a solved path."""
    lines = []
    total = 0.0
    for u, v in zip(path[:-1], path[1:]):
        w = G[u][v][weight]
        total += w
        layer, country = v
        proc = G.nodes[v].get("process", "")
        lines.append(f"  L{layer:<2} {country:<6} {w:12.5f}   {proc}")
    header = f"Total: {total:.5f}   ({len(path)} nodes)"
    return header + "\n" + "\n".join(lines)


def plot_network(G, out_png: str, weight: str = "weight", title: str = "Layered supply-chain network"):
    """Multipartite layered plot with country + edge-weight labels. Saves a PNG."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # ensure a numeric 'layer' attribute for the multipartite layout
    for node in G.nodes():
        G.nodes[node]["layer"] = node[0]
    pos = nx.multipartite_layout(G, subset_key="layer")
    fig, ax = plt.subplots(figsize=(20, 12))
    nx.draw_networkx_nodes(G, pos, node_size=300, node_color="#cfe8ff", ax=ax)
    nx.draw_networkx_edges(G, pos, arrows=False, edge_color="#bbbbbb", width=0.4, ax=ax)
    nx.draw_networkx_labels(G, pos, labels={nd: nd[1] for nd in G.nodes()}, font_size=6, ax=ax)
    ax.set_title(title)
    ax.axis("off")
    fig.tight_layout()
    fig.savefig(out_png, dpi=120)
    plt.close(fig)
    return out_png


def _read_process_order(path: str):
    with open(path, encoding="utf-8") as fh:
        return [ln.strip() for ln in fh if ln.strip()]


def main(argv=None):
    p = argparse.ArgumentParser(description="Solve the layered supply-chain shortest path.")
    p.add_argument("--edges", required=True, help="edge-score CSV (process_base, country, to_country, <score>)")
    p.add_argument("--score-col", required=True, help="numeric column to use as edge weight")
    p.add_argument("--process-order", required=True,
                   help="text file, one process label per line, in supply-chain order")
    p.add_argument("--process-col", default="process_base")
    p.add_argument("--from-col", default="country")
    p.add_argument("--to-col", default="to_country")
    p.add_argument("--png", default=None, help="optional output PNG path")
    args = p.parse_args(argv)

    edge_df = pd.read_csv(args.edges)
    order = _read_process_order(args.process_order)
    G, s, t = build_layered_graph(
        edge_df, args.score_col, process_order=order,
        process_col=args.process_col, from_col=args.from_col, to_col=args.to_col,
    )
    path, total = solve_shortest_path(G, s, t)
    print(f"Score column: {args.score_col}")
    print(format_pathway(G, path))
    if args.png:
        plot_network(G, args.png, title=f"Supply-chain network ({args.score_col})")
        print(f"Saved plot: {args.png}")
    return path, total


if __name__ == "__main__":
    main()
