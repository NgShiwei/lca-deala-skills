"""The shared environment check, with installed versions faked.

Brightway is not needed: the check reads package metadata, so each test
monkeypatches what it sees.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins" / "lca-deala-skills"
                       / "skills" / "lca-calculator" / "scripts"))
import check_environment as ce  # noqa: E402

GOOD = {"bw2data": "4.7", "bw2calc": "2.5.0", "bw2io": "0.9.17",
        "matrix_utils": "0.6.3", "ecoinvent_interface": "3.1",
        "deala": "1.2.1", "brightway2": "2.4.7", "plotly": "6.1.1"}


@pytest.fixture
def env(monkeypatch):
    installed = dict(GOOD)
    monkeypatch.setattr(ce, "_version", lambda d: installed.get(d))
    monkeypatch.setattr(ce, "modified_files", lambda d="deala": [])
    monkeypatch.setattr(ce.sys, "version_info", (3, 11, 9))
    monkeypatch.setattr(ce.os, "name", "posix")
    return installed


def whats(problems):
    return " | ".join(w for w, _ in problems)


def test_verified_environment_passes(env):
    assert ce.check(verbose=False) == []


def test_downgraded_stack_names_the_no_deps_cause(env):
    env["bw2data"] = "3.6.6"
    problems = ce.check(verbose=False)
    assert "--no-deps" in whats(problems)
    assert "requirements-deala.txt" in problems[0][1]


def test_floors_accept_newer_and_reject_older(env):
    env["matrix_utils"] = "0.6.4"
    env["ecoinvent_interface"] = "3.2"
    assert ce.check(verbose=False) == []
    env["matrix_utils"] = "0.6.2"
    env["ecoinvent_interface"] = "3.0"
    text = whats(ce.check(verbose=False))
    assert "A1" in text and "unauthorized_client" in text


def test_deala_optional_for_environmental_work(env):
    del env["deala"], env["brightway2"], env["plotly"]
    assert ce.check(require_deala=False, verbose=False) == []
    assert len(ce.check(verbose=False)) == 3


def test_modified_deala_is_reported_with_reinstall(env, monkeypatch):
    monkeypatch.setattr(ce, "modified_files", lambda d="deala": ["deala/files/x.json"])
    (what, fix), = ce.check(verbose=False)
    assert "x.json" in what and "--force-reinstall" in fix


def test_windows_needs_utf8(env, monkeypatch):
    monkeypatch.setattr(ce.os, "name", "nt")
    monkeypatch.delenv("PYTHONIOENCODING", raising=False)
    assert "PYTHONIOENCODING" in whats(ce.check(verbose=False))
    monkeypatch.setenv("PYTHONIOENCODING", "utf-8")
    assert ce.check(verbose=False) == []


def test_every_problem_has_a_fix(env):
    for k in list(env):
        env[k] = None
    for what, fix in ce.check(verbose=False):
        assert fix.strip(), what


def test_integrity_check_reads_a_real_install_record():
    # networkx is installed wherever these tests run, untouched.
    assert ce.modified_files("networkx") == []
    assert ce.modified_files("no-such-package-xyz") == []
