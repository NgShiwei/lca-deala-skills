"""A tiny made-up supply chain with a known answer: a check that the skills work.

A product is made in three steps: Grow, Process, Finish. Each step can happen
in country A, B or C, and the product can be shipped between countries after
any step. Which countries should do which step to make the finished product as
cheaply as possible? This script answers that with the same code a real study
uses, and README.md works out the same answer by hand: 1.1452 USD per kg of
finished product, grown in B, then processed and finished in C.

Everything is invented: the countries, the costs, the distances and the
freight rates. Nothing here needs Brightway, deala or a licence; pandas and
networkx are enough. Run it from any folder:

    python run_toy.py

It prints the route and ends with "OK: matches the hand calculation". Anything
else means the installed skills do not behave as documented.
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

# The transport code looks countries up in the distance table by 3-letter
# code, as real distance data is keyed on ISO3 codes (DEU, FRA, ...). These
# three codes are placeholders for the made-up countries.
ISO2_TO_ISO3 = {"A": "AAA", "B": "BBB", "C": "CCC"}

# The steps, in the order the product goes through them.
STEPS = ["Grow", "Process", "Finish"]

# The graph needs one more stage after the last step: "At market", where the
# finished product ends up. It carries no cost of its own. Its job is to give
# the Finish step somewhere to ship to, so Finish is charged (with any shipping)
# like every other step. See "The stages of the graph" in README.md.
PROCESS_ORDER = STEPS + ["At market"]

# Freight rates in USD per tonne-km, by (mode, country). "GLO" is the global
# rate, used for any country without its own. A real study gets these from
# deala's freight activities with dh.transport_rates(), which needs Brightway.
RATES = {("lorry", "GLO"): 0.20, ("train", "GLO"): 0.10, ("sea", "GLO"): 0.004}

# The answer, worked by hand in README.md: the cost per kg of finished
# product, and the country at each stage (Grow, Process, Finish, At market).
EXPECTED_TOTAL = 1.1452
EXPECTED_ROUTE = ["B", "C", "C", "C"]


def run(verbose: bool = True):
    """Build every table and solve. Returns ``(path, total, edges, transport)``."""
    # 1. What it costs to ship 1 kg between each pair of countries.
    transport = dh.build_transport_table(
        RATES, HERE / "distances.csv", COUNTRIES, ISO2_TO_ISO3)
    # 2. The cost of every (step, from country, to country) move, per kg of
    #    FINISHED product: scale x step cost, plus scale x shipping if it moves.
    edges = dh.build_edge_table(
        pd.read_csv(HERE / "process_costs.csv"), transport,
        HERE / "scaling_factors.csv", STEPS, COUNTRIES,
        score_col="calculated_cost", verbose=verbose)
    # 3. The cheapest way through all the steps.
    G, s, t = gh.build_layered_graph(edges, "calculated_cost", PROCESS_ORDER)
    path, total = gh.solve_shortest_path(G, s, t)
    if verbose:
        print(gh.format_pathway(G, path))
        print()
        print(describe(path, total))
    return path, total, edges, transport


def describe(path, total) -> str:
    """The solved route in plain words, one line per step."""
    where = [country for _, country in path[1:-1]]      # one per stage
    lines = ["Cheapest route:"]
    for i, step in enumerate(STEPS):
        here, then = where[i], where[i + 1]
        move = f"stays in {here}" if here == then else f"is shipped from {here} to {then}"
        after = "and is sold there" if i == len(STEPS) - 1 and here == then else ""
        lines.append(f"  {step:<8} in {here}; the product {move} {after}".rstrip())
    lines.append(f"Cost: {total:.4f} USD per kg of finished product")
    return "\n".join(lines)


if __name__ == "__main__":
    path, total, _, _ = run()
    route = [c for _, c in path[1:-1]]
    ok = abs(total - EXPECTED_TOTAL) < 1e-9 and route == EXPECTED_ROUTE
    print("\nOK: matches the hand calculation" if ok else
          f"\nMISMATCH: expected {EXPECTED_TOTAL} via {EXPECTED_ROUTE}")
    sys.exit(0 if ok else 1)
