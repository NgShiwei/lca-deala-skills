"""A made-up three-country, three-step supply chain, solved end to end offline.

Everything here is invented: the countries A, B and C, the step names, the
costs, the scaling factors, the distances and the freight rates. It needs no
Brightway and no licence. It exercises the same code a real study uses from
the transport table onwards:

    deala_helpers.build_transport_table   distances + freight rates -> USD/kg per pair
    deala_helpers.build_edge_table        scale x (process cost + transport)
    graph_helpers.build_layered_graph     START -> 3 steps + pass-through -> END
    graph_helpers.solve_shortest_path     the globally cheapest route

In a real study the per-process costs come from ``deala_helpers.score_native``
and the freight rates from ``deala_helpers.transport_rates``; both need
Brightway, so here they are typed in.

Country C cannot perform the first step: it has no "Toy grow" cost. It is
cheapest at the later steps, so a builder that charged its missing first step
0.0 would start the route in C.

    python run_toy.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
SKILLS = HERE.parents[1] / "skills"
sys.path.insert(0, str(SKILLS / "deala-calculator" / "scripts"))
sys.path.insert(0, str(SKILLS / "supply-chain-optimizer" / "scripts"))

import deala_helpers as dh  # noqa: E402
import graph_helpers as gh  # noqa: E402

COUNTRIES = ["A", "B", "C"]
ISO2_TO_ISO3 = {"A": "AAA", "B": "BBB", "C": "CCC"}

# The study's real steps, in supply-chain order ...
STEPS = ["Toy grow", "Toy process", "Toy finish"]
# ... plus the trailing pass-through layer the graph charges nothing for.
PROCESS_ORDER = STEPS + ["Toy finish, at market"]

# USD per tonne-km. A real study scores these from DEALA's freight activities.
RATES = {("lorry", "GLO"): 0.20, ("train", "GLO"): 0.10, ("sea", "GLO"): 0.004}

# The answer, worked by hand in README.md.
EXPECTED_TOTAL = 1.1452
EXPECTED_ROUTE = ["B", "C", "C", "C"]


def run(verbose: bool = True):
    """Build every table and solve. Returns ``(path, total, edges, transport)``."""
    transport = dh.build_transport_table(
        RATES, HERE / "distances.csv", COUNTRIES, ISO2_TO_ISO3)
    edges = dh.build_edge_table(
        pd.read_csv(HERE / "process_costs.csv"), transport,
        HERE / "scaling_factors.csv", STEPS, COUNTRIES,
        score_col="calculated_cost", verbose=verbose)
    G, s, t = gh.build_layered_graph(edges, "calculated_cost", PROCESS_ORDER)
    path, total = gh.solve_shortest_path(G, s, t)
    if verbose:
        print(gh.format_pathway(G, path))
    return path, total, edges, transport


if __name__ == "__main__":
    path, total, _, _ = run()
    route = [c for _, c in path[1:-1]]
    ok = abs(total - EXPECTED_TOTAL) < 1e-9 and route == EXPECTED_ROUTE
    print("OK: matches the hand calculation" if ok else
          f"MISMATCH: expected {EXPECTED_TOTAL} via {EXPECTED_ROUTE}")
    sys.exit(0 if ok else 1)
