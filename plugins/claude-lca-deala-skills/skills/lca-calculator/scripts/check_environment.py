#!/usr/bin/env python3
"""Check the Brightway environment before any Brightway skill does real work.

Run this first, in the SAME interpreter the work will run in (the notebook
kernel, or the python that will run the script):

    python check_environment.py            # full check, incl. deala
    python check_environment.py --no-deala # environmental side only

Every failure prints what is wrong AND the command that fixes it. Exit code 0
means every check passed. Importable too: ``problems = check(require_deala=True)``.

Why each check exists (see requirements.txt for the long form):

* ``sys.executable``: the most common fresh-machine failure is installing into
  one Python and running another (a Jupyter kernel on a different env).
* bw2data 4.7 / bw2calc 2.5.0 / bw2io 0.9.17: Brightway 2.5, pinned. A 3.x
  bw2data means deala was installed without ``--no-deps`` and pip downgraded
  the stack to Brightway 2.
* matrix_utils >= 0.6.3: below it, DEALA-Cost scoring crashes on ``.A1``.
* ecoinvent_interface >= 3.1: 3.0 fails the ecoinvent login with
  ``unauthorized_client``, which looks like a wrong password and is not.
* deala 1.2.1, unmodified, plus brightway2 2.4.7 and plotly: deala will not
  import without the latter two, and a hand-edited deala makes results depend
  on files no other machine has.
* PYTHONIOENCODING=utf-8 on Windows: Brightway's logs otherwise kill a run.
"""
from __future__ import annotations

import argparse
import hashlib
import base64
import os
import sys
from importlib import metadata

INSTALL = ("python -m pip install -r requirements.txt\n"
           "        python -m pip install --no-deps -r requirements-deala.txt\n"
           "        (from the claude-lca-deala-skills folder, in this interpreter's environment)")

PINNED = {"bw2data": "4.7", "bw2calc": "2.5.0", "bw2io": "0.9.17"}
FLOORS = {"matrix_utils": "0.6.3", "ecoinvent_interface": "3.1"}
DEALA = {"deala": "1.2.1", "brightway2": "2.4.7"}


def _v(text: str) -> tuple:
    parts = []
    for p in text.split("."):
        digits = "".join(ch for ch in p if ch.isdigit())
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def _version(dist: str):
    try:
        return metadata.version(dist)
    except metadata.PackageNotFoundError:
        return None


def modified_files(dist: str = "deala") -> list:
    """Files of an installed package whose bytes differ from its install record.

    Uses the sha256 hashes pip wrote into the wheel's RECORD, so it needs no
    network and no second copy of deala.
    """
    changed = []
    try:
        files = metadata.distribution(dist).files or []
    except metadata.PackageNotFoundError:
        return changed
    for f in files:
        if f.hash is None or f.hash.mode != "sha256" or not str(f).startswith(dist + "/"):
            continue
        path = f.locate()
        if not os.path.isfile(path):
            changed.append(str(f) + " (missing)")
            continue
        with open(path, "rb") as fh:
            digest = base64.urlsafe_b64encode(hashlib.sha256(fh.read()).digest())
        if digest.rstrip(b"=").decode() != f.hash.value:
            changed.append(str(f))
    return changed


def check(require_deala: bool = True, verbose: bool = True) -> list:
    """Return a list of problems, each a (what, fix) pair. Empty means ready."""
    problems = []
    say = print if verbose else (lambda *a, **k: None)

    say(f"interpreter : {sys.executable}")
    say(f"python      : {sys.version.split()[0]}")
    if sys.version_info[:2] != (3, 11):
        problems.append((
            f"Python {sys.version.split()[0]}; these pins were verified on 3.11",
            "create a Python 3.11 venv and install into it (SETUP.md, step 1)"))

    for dist, want in PINNED.items():
        have = _version(dist)
        say(f"{dist:<20}: {have or 'MISSING'} (want {want})")
        if have is None:
            problems.append((f"{dist} is not installed in this interpreter", INSTALL))
        elif dist == "bw2data" and _v(have) < (4,):
            problems.append((
                f"bw2data {have} is Brightway 2, not 2.5: deala was almost certainly "
                "installed without --no-deps, and pip downgraded the stack",
                "re-run both install commands, in order:\n        " + INSTALL))
        elif _v(have) != _v(want):
            problems.append((f"{dist} {have}, expected {want}", INSTALL))

    for dist, floor in FLOORS.items():
        have = _version(dist)
        say(f"{dist:<20}: {have or 'MISSING'} (want >= {floor})")
        if have is None or _v(have) < _v(floor):
            why = {
                "matrix_utils": "below 0.6.3, DEALA-Cost .lci() crashes with "
                                "'csc_matrix' object has no attribute 'A1'",
                "ecoinvent_interface": "3.0 and below fail the ecoinvent login with "
                                       "unauthorized_client, whatever the password",
            }[dist]
            fix = {
                # the verified version, without letting pip touch its deps
                "matrix_utils": 'python -m pip install --no-deps "matrix_utils==0.6.3"',
                # a floor on purpose: it follows ecoinvent's live login service
                "ecoinvent_interface": 'python -m pip install --upgrade "ecoinvent_interface>=3.1"',
            }[dist]
            problems.append((f"{dist} {have or 'missing'}: {why}", fix))

    if require_deala:
        for dist, want in DEALA.items():
            have = _version(dist)
            say(f"{dist:<20}: {have or 'MISSING'} (want {want})")
            if have is None or _v(have) != _v(want):
                problems.append((
                    f"{dist} {have or 'missing'}, expected {want}",
                    "python -m pip install --no-deps -r requirements-deala.txt"))
        if _version("plotly") is None:
            problems.append(("plotly is missing, and deala will not import without it",
                             INSTALL))
        if _version("deala"):
            changed = modified_files("deala")
            say(f"deala files : {'unmodified' if not changed else f'{len(changed)} MODIFIED'}")
            if changed:
                problems.append((
                    "deala's installed files differ from its install record: "
                    + ", ".join(changed[:5]) + (" ..." if len(changed) > 5 else ""),
                    "python -m pip install --force-reinstall --no-deps deala==1.2.1\n"
                    "        then patch a private copy instead (deala-calculator skill)"))

    if os.name == "nt" and os.environ.get("PYTHONIOENCODING", "").lower() != "utf-8":
        problems.append((
            "PYTHONIOENCODING is not utf-8: Brightway's logs can kill a run part-way",
            "set PYTHONIOENCODING=utf-8   (cmd)   or   "
            '$env:PYTHONIOENCODING = "utf-8"   (PowerShell)'))

    return problems


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Check the Brightway 2.5 + deala environment.")
    p.add_argument("--no-deala", action="store_true",
                   help="skip the deala checks (environmental work only)")
    args = p.parse_args(argv)
    problems = check(require_deala=not args.no_deala)
    if not problems:
        print("\nOK: environment ready.")
        return 0
    print(f"\n{len(problems)} problem(s):")
    for what, fix in problems:
        print(f"  - {what}\n    fix: {fix}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
