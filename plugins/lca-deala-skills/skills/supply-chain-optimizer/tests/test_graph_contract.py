"""Offline checks on the layered-graph contract. No Brightway, no licence.

Run with either:
    python -m pytest supply-chain-optimizer/tests
    python supply-chain-optimizer/tests/test_graph_contract.py

Any copy of the builder a project vendors must behave exactly like this one.
These tests pin the rule that once drifted between copies: a missing
(process, from, to) row OMITS the edge instead of charging it 0.0.
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import graph_helpers as gh  # noqa: E402

# Three steps plus a trailing pass-through layer, as in a real process order.
ORDER = ["farm", "process", "finish", "at market"]


def _toy_edges():
    """A and B can do every step. C cannot farm: it has no 'farm' rows at all.

    C is by far the cheapest at 'process' and 'finish', so a builder that
    charged C's missing farm step 0.0 would start the route in C.
    """
    rows = []
    cost = {  # per-step cost in each country; C has no farm entry by design
        "farm": {"A": 5.0, "B": 6.0},
        "process": {"A": 4.0, "B": 3.0, "C": 0.5},
        "finish": {"A": 2.0, "B": 2.5, "C": 0.1},
    }
    transport = 0.25  # flat cross-country leg, added only when from != to
    for step, by_country in cost.items():
        for f, c in by_country.items():
            for t in ("A", "B", "C"):
                w = c if f == t else c + transport
                rows.append({"process_base": step, "country": f,
                             "to_country": t, "score": w})
    return pd.DataFrame(rows)


def test_missing_row_omits_edge():
    G, _, _ = gh.build_layered_graph(_toy_edges(), "score", process_order=ORDER)
    # No farm rows for C -> no edge out of (1, C) at all.
    assert G.out_degree((1, "C")) == 0
    # A present row still makes its edge.
    assert G.has_edge((1, "A"), (2, "C"))


def test_country_without_data_cannot_win():
    G, s, t = gh.build_layered_graph(_toy_edges(), "score", process_order=ORDER)
    path, total = gh.solve_shortest_path(G, s, t)
    origin = path[1][1]
    assert origin != "C", f"C won by having no farm data: {path}"
    # Hand-computed optimum: farm in A (5.0) shipped to C (+0.25), process in C
    # (0.5), finish in C (0.1), pass-through to END (0.0) = 5.85.
    assert abs(total - 5.85) < 1e-12, total
    assert [c for _, c in path[1:-1]] == ["A", "C", "C", "C"]


def test_present_zero_weight_keeps_edge():
    df = _toy_edges()
    df.loc[(df.process_base == "farm") & (df.country == "B")
           & (df.to_country == "B"), "score"] = 0.0
    G, _, _ = gh.build_layered_graph(df, "score", process_order=ORDER)
    assert G.has_edge((1, "B"), (2, "B"))
    assert G[(1, "B")][(2, "B")]["weight"] == 0.0


def test_pass_through_layer_still_reaches_end():
    # 'at market' has no rows anywhere; its -> END edges must default to 0.0,
    # or there would be no path at all.
    G, s, t = gh.build_layered_graph(_toy_edges(), "score", process_order=ORDER)
    for c in ("A", "B", "C"):
        assert G[(len(ORDER), c)][t]["weight"] == 0.0


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS", name)
