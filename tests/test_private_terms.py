"""The pre-release guard: no private-study terms anywhere in the repository.

The real term list (hashed, tools/private_terms.json) exists only on the
maintainer's machine, so the repository scan is skipped anywhere else. The
mechanics are tested against an invented list, which runs everywhere.
"""
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
import check_private_terms as cpt  # noqa: E402
import hash_private_terms as hpt  # noqa: E402


@pytest.mark.skipif(not cpt.TERMS_JSON.is_file(),
                    reason="private term list not on this machine")
def test_repository_is_clean():
    hits = cpt.scan()
    assert not hits, "\n".join(hits)


def _spec(tmp_path):
    terms = [
        "token\t0.12345",
        "phrase\tsecret widget line",
        "substring\tzorbl",
        "countryset\t" + " ".join(["AA", "BB", "CC", "DD", "EE", "FF", "GG", "HH", "II", "JJ"]),
    ]
    p = tmp_path / "terms.json"
    p.write_text(json.dumps(hpt.build(terms, salt="test-salt")))
    return p


def test_guard_catches_each_kind(tmp_path):
    spec = _spec(tmp_path)
    f = tmp_path / "leak.md"
    f.write_text(
        "The optimum was 0.12345.\n"
        "Built on the Secret Widget Line.\n"
        "db = 'xZorbl_v2'\n"
        "\n"
        "countries = [JJ, II, HH, GG, FF,\n"
        "             EE, DD, CC, BB, AA]\n")
    hits = cpt.scan(files=[f], terms_path=spec)
    text = "\n".join(hits)
    assert "0.12345" in text
    assert "secret widget line" in text
    assert "xzorbl_v2" in text
    assert "country list" in text


def test_guard_normalises_route_arrows(tmp_path):
    spec_path = tmp_path / "t.json"
    spec_path.write_text(json.dumps(hpt.build(["phrase\tqq→zz"], salt="s")))
    f = tmp_path / "r.md"
    f.write_text("route QQ -> ZZ\n")
    assert cpt.scan(files=[f], terms_path=spec_path)


def test_guard_passes_clean_text(tmp_path):
    spec = _spec(tmp_path)
    f = tmp_path / "ok.md"
    f.write_text("Nothing private: 0.1234, a widget line, AA BB CC.\n")
    assert cpt.scan(files=[f], terms_path=spec) == []
