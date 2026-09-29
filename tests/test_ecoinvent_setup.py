"""Credential handling in ecoinvent_setup.py, offline.

No ecoinvent_interface, no Brightway, no network: the secrets folder is a temp
directory and stdin is not a terminal, exactly as in an agent's shell.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins" / "lca-deala-skills"
                       / "skills" / "lca-calculator" / "scripts"))
import ecoinvent_setup as es  # noqa: E402

VARS = ("ECOINVENT_USERNAME", "ECOINVENT_PASSWORD", "EI_USERNAME", "EI_PASSWORD")


@pytest.fixture
def secrets(tmp_path, monkeypatch):
    for v in VARS:
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setattr(es, "_secrets_dir", lambda: tmp_path)
    monkeypatch.setattr(es.sys.stdin, "isatty", lambda: False, raising=False)
    return tmp_path


def test_resolution_order(secrets, monkeypatch):
    assert es.resolve_credential("username") == ("", None)
    (secrets / "EI_username").write_text("from-folder\n")
    assert es.resolve_credential("username")[0] == "from-folder"
    monkeypatch.setenv("EI_USERNAME", "from-ei")
    assert es.resolve_credential("username")[0] == "from-ei"
    monkeypatch.setenv("ECOINVENT_USERNAME", "from-ecoinvent")
    assert es.resolve_credential("username") == ("from-ecoinvent",
                                                 "environment variable ECOINVENT_USERNAME")


def test_no_terminal_and_nothing_stored_refuses_to_prompt(secrets):
    with pytest.raises(SystemExit, match="your own terminal"):
        es.ensure_credentials()


def test_stored_credentials_show_username_never_password(secrets, capsys):
    (secrets / "EI_username").write_text("alice")
    (secrets / "EI_password").write_text("s3cret-value")
    es.ensure_credentials()                    # no terminal: accepts, no prompt
    out = capsys.readouterr().out
    assert "alice" in out
    assert "s3cret-value" not in out


def test_reprompt_without_terminal_refuses(secrets):
    (secrets / "EI_username").write_text("alice")
    (secrets / "EI_password").write_text("x")
    with pytest.raises(SystemExit, match="your own terminal"):
        es.ensure_credentials(reprompt=True)


def test_project_is_required():
    with pytest.raises(SystemExit):
        es.main([])


def test_names_follow_version_and_system_model():
    db, bio, method = es.names("3.10", "cutoff")
    assert (db, bio) == ("ecoinvent-3.10-cutoff", "ecoinvent-3.10-biosphere")
    assert method[0] == "ecoinvent-3.10"
    assert es.names("3.11", "consequential")[0] == "ecoinvent-3.11-consequential"
