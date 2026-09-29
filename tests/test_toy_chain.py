"""The toy supply chain, end to end, offline. No Brightway, no licence.

Run with ``python -m pytest tests`` from the repository root.
"""
import sys
from pathlib import Path

import pytest

TOY = Path(__file__).resolve().parents[1] / "plugins" / "claude-lca-deala-skills" / "examples" / "toy-chain"
sys.path.insert(0, str(TOY))
import run_toy  # noqa: E402


@pytest.fixture(scope="module")
def result():
    return run_toy.run(verbose=False)


def test_matches_hand_calculation(result):
    path, total, _, _ = result
    assert total == pytest.approx(run_toy.EXPECTED_TOTAL, abs=1e-12)
    assert [c for _, c in path[1:-1]] == run_toy.EXPECTED_ROUTE


def test_country_without_first_step_cannot_start(result):
    path, _, edges, _ = result
    assert path[1][1] != "C"
    assert not ((edges.process_base == "Toy grow") & (edges.country == "C")).any()


def test_transport_table(result):
    _, _, _, transport = result
    t = transport.set_index(["from_country", "to_country"])["transport_cost"]
    assert len(t) == 9                                   # n^2 pairs
    assert t[("A", "A")] == t[("B", "B")] == t[("C", "C")] == 0.0
    assert t[("A", "B")] == pytest.approx(0.120)          # road, 600 km
    assert t[("A", "C")] == pytest.approx(0.130)          # road + sea + rail
    assert t[("B", "C")] == pytest.approx(0.116)          # road + sea + road


def test_edge_formula(result):
    _, _, edges, _ = result
    e = edges.set_index(["process_base", "country", "to_country"])["calculated_cost"]
    assert e[("Toy grow", "B", "C")] == pytest.approx(2.2 * (0.25 + 0.116))
    assert e[("Toy process", "C", "C")] == pytest.approx(1.2 * 0.20)
    assert len(edges) == 2 * 3 + 3 * 3 + 3 * 3
    assert edges["calculated_cost"].notna().all()
