"""The marketplace and plugin manifests, checked against the documented rules.

`claude plugin validate .` is the authoritative check; this is the offline
subset of it, plus one thing it does not check: that every path the skill docs
name actually exists. Paths in a skill are relative to the skill's own folder.
"""
import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
MARKET = json.loads((REPO / ".claude-plugin" / "marketplace.json").read_text())
KEBAB = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
PLUGIN_FIELDS = {"$schema", "name", "displayName", "version", "description", "author",
                 "homepage", "repository", "license", "keywords", "metadata",
                 "defaultEnabled", "dependencies", "settings", "userConfig", "channels",
                 "skills", "commands", "agents", "hooks", "mcpServers", "lspServers",
                 "outputStyles", "workflows", "experimental"}


def entries():
    return MARKET["plugins"]


def plugin_dir(entry):
    return REPO / entry["source"]


def test_marketplace_required_fields():
    assert KEBAB.match(MARKET["name"])
    assert MARKET["owner"]["name"]
    assert MARKET["description"]
    assert entries()


@pytest.mark.parametrize("entry", entries(), ids=lambda e: e["name"])
def test_entry_source_and_manifest(entry):
    assert entry["source"].startswith("./") and ".." not in entry["source"]
    assert entry["description"]
    manifest = json.loads((plugin_dir(entry) / ".claude-plugin" / "plugin.json").read_text())
    assert manifest["name"] == entry["name"]            # must match the entry
    assert KEBAB.match(manifest["name"])
    assert set(manifest) <= PLUGIN_FIELDS, set(manifest) - PLUGIN_FIELDS
    assert manifest["author"]["name"] and manifest["description"] and manifest["version"]
    assert "version" not in entry                       # plugin.json is the one place
    # Installs update only when this changes, so every release bumps it.
    assert re.fullmatch(r"\d+\.\d+\.\d+", manifest["version"]), manifest["version"]
    # only the manifest and the directory icon live in .claude-plugin/
    assert sorted(p.name for p in (plugin_dir(entry) / ".claude-plugin").iterdir()
                  if not p.name.startswith(".")) == ["icon.svg", "plugin.json"]


def skills():
    for entry in entries():
        yield from sorted(p for p in (plugin_dir(entry) / "skills").iterdir() if p.is_dir())


@pytest.mark.parametrize("skill", list(skills()), ids=lambda p: p.name)
def test_skill_frontmatter(skill):
    text = (skill / "SKILL.md").read_text()
    front = text.split("---")[1]
    assert re.search(rf"^name: {re.escape(skill.name)}$", front, re.M)
    assert re.search(r"^description:", front, re.M)


PATH_RE = re.compile(r"`((?:\.\./|scripts/|references/|assets/)[^`\s]*)`")


@pytest.mark.parametrize("skill", list(skills()), ids=lambda p: p.name)
def test_paths_named_in_skill_docs_exist(skill):
    missing = []
    for md in [skill / "SKILL.md", *sorted((skill / "references").glob("*.md"))]:
        for ref in PATH_RE.findall(md.read_text()):
            target = ref.split("::")[0].rstrip(".,;:")
            if "<" in target or "*" in target:
                continue                                  # a placeholder, not a path
            if not (skill / target).exists():
                missing.append(f"{md.relative_to(REPO)}: {ref}")
    assert not missing, "\n".join(missing)


def test_licence_ships_with_the_plugin():
    for entry in entries():
        manifest = json.loads((plugin_dir(entry) / ".claude-plugin" / "plugin.json").read_text())
        assert manifest["license"] == "BSD-3-Clause"
        assert (plugin_dir(entry) / "LICENSE").read_text() == (REPO / "LICENSE").read_text()
        assert "BSD 3-Clause License" in (REPO / "LICENSE").read_text()


def test_renamed_plugin_migrates():
    # The plugin was first published under another name; existing installs
    # follow this map instead of breaking. Keep entries forever (append-only).
    names = {e["name"] for e in entries()}
    for old, new in MARKET.get("renames", {}).items():
        assert new is None or new in names, (old, new)
