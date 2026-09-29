"""lca_helpers.working_copy refuses a database name deala would delete.

lca_helpers imports Brightway at module level, so stand-ins are installed
first. The refusal happens before any Brightway call, which is the point.
"""
import sys
import types
from pathlib import Path

import pytest


@pytest.fixture
def lca_helpers(monkeypatch):
    bd = types.ModuleType("bw2data")
    bd.databases = {}
    bd.Database = lambda name: pytest.fail("reached Brightway")
    monkeypatch.setitem(sys.modules, "bw2data", bd)
    monkeypatch.setitem(sys.modules, "bw2calc", types.ModuleType("bw2calc"))
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "plugins"
                                    / "claude-lca-deala-skills" / "skills" / "lca-calculator" / "scripts"))
    monkeypatch.delitem(sys.modules, "lca_helpers", raising=False)
    import lca_helpers
    return lca_helpers


@pytest.mark.parametrize("name", ["DEALA mydb", "Costed_DEALA", "my_DEALA_copy"])
def test_deala_in_name_is_refused(lca_helpers, name):
    with pytest.raises(ValueError, match="deletes every database"):
        lca_helpers.working_copy("src", name)
