"""deala_helpers' offline half: selectors, transport table, edge-table gates.

Built on the toy supply chain, so every expected number can be checked by hand
against plugins/claude-lca-deala-skills/examples/toy-chain/README.md.
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

TOY = Path(__file__).resolve().parents[1] / "plugins" / "claude-lca-deala-skills" / "examples" / "toy-chain"
sys.path.insert(0, str(TOY))
import run_toy  # noqa: E402
import deala_helpers as dh  # noqa: E402  (put on the path by run_toy)
import graph_helpers as gh  # noqa: E402


def transport(rates=run_toy.RATES, countries=run_toy.COUNTRIES, iso=run_toy.ISO2_TO_ISO3,
              csv=TOY / "distances.csv"):
    return dh.build_transport_table(rates, csv, countries, iso)


def edges(**kw):
    args = dict(cost_results=pd.read_csv(TOY / "process_costs.csv"), transport=transport(),
                scaling_csv=TOY / "scaling_factors.csv", process_order=run_toy.STEPS,
                countries=run_toy.COUNTRIES, verbose=False)
    args.update(kw)
    return dh.build_edge_table(**args)


# --- pick_deala -------------------------------------------------------------

DB = [
    {"name": "electricity - Non-household, 20-499 MWh", "location": "AA"},
    {"name": "electricity - Non-household, 2000-19999 MWh", "location": "AA"},
    {"name": "electricity - Non-household, 20-499 MWh", "location": "GLO"},
    {"name": "gas - industrial", "location": "GLO"},
    {"name": "gas - industrial", "location": "GLO"},
]


def test_pick_deala_exact_country_then_glo():
    assert dh.pick_deala(DB, "electricity - Non-household, 20-499 MWh", "AA") is DB[0]
    assert dh.pick_deala(DB, "electricity - Non-household, 20-499 MWh", "BB") is DB[2]


def test_pick_deala_never_matches_a_substring():
    with pytest.raises(ValueError, match="No DEALA activity"):
        dh.pick_deala(DB, "electricity - Non-household, 20", "AA")


def test_pick_deala_raises_on_two_hits():
    with pytest.raises(ValueError, match="expected exactly one"):
        dh.pick_deala(DB, "gas - industrial", "BB")


# --- transport ------------------------------------------------------------

def test_country_specific_rate_used_where_it_exists():
    rates = dict(run_toy.RATES)
    rates[("lorry", "A")] = 0.15
    t = transport(rates).set_index(["from_country", "to_country"])["transport_cost"]
    assert t[("A", "B")] == pytest.approx(600 * 0.15 / 1000)   # origin-keyed
    assert t[("B", "A")] == pytest.approx(600 * 0.20 / 1000)   # B has no own rate


def test_unmapped_country_raises():
    with pytest.raises(ValueError, match=r"no ISO3 code for \['C'\]"):
        transport(iso={"A": "AAA", "B": "BBB"})


def test_missing_pair_raises(tmp_path):
    csv = tmp_path / "d.csv"
    rows = pd.read_csv(TOY / "distances.csv")
    rows[~((rows.isoA == "BBB") & (rows.isoB == "CCC"))].to_csv(csv, index=False)
    with pytest.raises(ValueError, match="B->C"):
        transport(csv=csv)


def test_iso_map_from_country_converter():
    pytest.importorskip("country_converter")
    assert dh.iso2_to_iso3_map(["DE", "FR"]) == {"DE": "DEU", "FR": "FRA"}
    with pytest.raises(ValueError, match="cannot map"):
        dh.iso2_to_iso3_map(["DE", "ZZ"])


# --- edge table gates -------------------------------------------------------

def test_missing_scaling_factor_raises_naming_the_country():
    scal = pd.read_csv(TOY / "scaling_factors.csv")
    with pytest.raises(ValueError, match=r"countries \['B'\]"):
        edges(scaling_csv=scal[scal.country != "B"])


def test_missing_cost_raises():
    costs = pd.read_csv(TOY / "process_costs.csv")
    costs.loc[0, "process_cost"] = float("nan")
    with pytest.raises(ValueError, match=r"no calculated_cost, for countries \['A'\]"):
        edges(cost_results=costs)


def test_cost_row_outside_scope_raises():
    with pytest.raises(ValueError, match=r"not in `countries`: \['C'\]"):
        edges(countries=["A", "B"], transport=transport(countries=["A", "B"]))


def test_feasibility_filter_drops_dead_end_rows():
    # C may not finish; A, B, C may do everything else. Steps are 1-based and
    # step 4 is the pass-through layer.
    can = {1: ["A", "B"], 2: ["A", "B", "C"], 3: ["A", "B"], 4: ["A", "B", "C"]}
    e = edges(countries_for_step=lambda step: can[step])
    to_c = e[(e.process_base == "Toy process") & (e.to_country == "C")]
    assert to_c.empty                      # nobody may ship "process" output to C
    assert len(e) == 6 + 3 * 2 + 3 * 3
    G, s, t = gh.build_layered_graph(e, "calculated_cost", run_toy.PROCESS_ORDER)
    path, total = gh.solve_shortest_path(G, s, t)
    assert path[3] != (3, "C")             # the finish step is done outside C


def test_feasibility_filter_rejects_unknown_step():
    costs = pd.read_csv(TOY / "process_costs.csv")
    costs.loc[0, "process_base"] = "Toy mystery"
    with pytest.raises(ValueError, match="not in process_order"):
        edges(cost_results=costs, countries_for_step=lambda s: run_toy.COUNTRIES)
