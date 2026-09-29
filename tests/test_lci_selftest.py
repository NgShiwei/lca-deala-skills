"""The lci-extractor self-tests run offline and write nothing into the skill."""
import sys
from pathlib import Path

LCI = Path(__file__).resolve().parents[1] / "plugins" / "lca-deala-skills" / "skills" / "lci-extractor"
sys.path.insert(0, str(LCI / "scripts"))
import lci_helpers  # noqa: E402


def _assets():
    return sorted(p.name for p in (LCI / "assets").iterdir())


def test_selftests_leave_assets_untouched():
    before = _assets()
    assert lci_helpers._cmd_selftest_nested() == 0
    lci_helpers._cmd_selftest()      # 1 without Brightway (a warning), 0 with it
    assert _assets() == before
