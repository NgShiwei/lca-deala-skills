#!/usr/bin/env python3
"""Store ecoinvent credentials once, and install ecoinvent into a project.

THE USER RUNS THIS IN THEIR OWN TERMINAL. It asks for the password with
``getpass``, which needs a real terminal; an agent's shell has none, and a
password typed into a chat ends up in a transcript. Agents: tell the user the
command, and afterwards verify with ``--check``, which prints the username only.

    python ecoinvent_setup.py --project <name>                 # interactive
    python ecoinvent_setup.py --project <name> --check         # read-only status
    python ecoinvent_setup.py --project <name> --reprompt      # replace stored credentials
    python ecoinvent_setup.py --project <name> --import        # import without asking
    python ecoinvent_setup.py --project <name> --methods-only  # re-install LCIA methods only

``--project`` has no default: the Brightway project is the user's choice, and
``bd.projects.set_current`` silently CREATES a project that does not exist, so
a typo would install 1.6 GB into a new empty one. The script says which
happened.

Credentials resolve in this order, the first hit winning:

1. ``ECOINVENT_USERNAME`` / ``ECOINVENT_PASSWORD`` environment variables;
2. ``EI_USERNAME`` / ``EI_PASSWORD`` (the names ecoinvent_interface documents);
3. the ecoinvent_interface secrets folder, written by
   ``ecoinvent_interface.permanent_setting()``. That folder is outside any
   repository (``~/.config/pylca/EcoinventInterface/secrets`` on macOS/Linux,
   ``%LOCALAPPDATA%\\pylca\\EcoinventInterface\\secrets`` on Windows), so a
   password stored there cannot be committed by accident.

The password is never printed, logged or written anywhere but that folder.

The import (``bi.import_ecoinvent_release``) downloads and installs ecoinvent
and its biosphere in one call: about 35 minutes and 1.6 GB. It is offered,
default No, and runs only if either database is missing. Afterwards the script
asserts both databases AND the LCIA method exist, because a method installed
without its namespace (an old bw2io) otherwise surfaces much later as scores
of exactly zero.
"""
from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

IMPORT_COST = "about 35 minutes and 1.6 GB of disk"


def _secrets_dir():
    try:
        from ecoinvent_interface.settings import secrets_dir
        return Path(secrets_dir)
    except Exception:          # ecoinvent_interface absent or unreadable
        return None


def resolve_credential(kind: str):
    """``(value, source)`` for ``kind`` in {'username', 'password'}; ``("", None)`` if unset."""
    if kind not in ("username", "password"):
        raise ValueError(kind)
    for var in (f"ECOINVENT_{kind.upper()}", f"EI_{kind.upper()}"):
        value = os.environ.get(var)
        if value:
            return value, f"environment variable {var}"
    d = _secrets_dir()
    if d is not None:
        fp = d / f"EI_{kind}"
        if fp.is_file():
            value = fp.read_text(encoding="utf-8").strip()
            if value:
                return value, f"secrets folder {d}"
    return "", None


def names(version: str, system_model: str):
    """(ecoinvent db, biosphere db, GWP100 method key) as bw2io 0.9.17 names them."""
    return (f"ecoinvent-{version}-{system_model}",
            f"ecoinvent-{version}-biosphere",
            (f"ecoinvent-{version}", "IPCC 2021", "climate change",
             "global warming potential (GWP100)"))


def _ask_yes_no(question: str, default: bool) -> bool:
    hint = "[Y/n]" if default else "[y/N]"
    answer = input(f"{question} {hint} ").strip().lower()
    return default if not answer else answer in ("y", "yes")


def _need_terminal(what: str):
    if not sys.stdin.isatty():
        sys.exit(f"{what} needs a real terminal, and this one has none. Run this "
                 "script yourself, in your own terminal (not through an agent).")


def ensure_credentials(reprompt: bool = False) -> None:
    """Use stored credentials if the user confirms them; otherwise prompt and store."""
    user, source = resolve_credential("username")
    _, psource = resolve_credential("password")
    if user and psource and not reprompt:
        print(f"ecoinvent username: {user}   (from {source})")
        if not sys.stdin.isatty() or _ask_yes_no("Use these credentials?", True):
            return
    _need_terminal("Entering ecoinvent credentials")
    import ecoinvent_interface as ei

    new_user = input("ecoinvent username (not your email address): ").strip()
    new_pass = getpass.getpass("ecoinvent password (not shown): ")
    if not new_user or not new_pass:
        sys.exit("Username and password are both required. Nothing was stored.")
    ei.permanent_setting("username", new_user)
    ei.permanent_setting("password", new_pass)
    del new_pass
    print(f"Stored for {new_user} in {_secrets_dir()}")
    for kind in ("username", "password"):
        value, src = resolve_credential(kind)
        if src and src.startswith("environment"):
            print(f"WARNING: {src} is set and takes precedence over what you just "
                  "stored. Unset it, or it will keep being used.")


def status(project: str, version: str, system_model: str) -> dict:
    """Read-only: credentials (username only), project, databases, method."""
    import bw2data as bd

    user, source = resolve_credential("username")
    _, psource = resolve_credential("password")
    print(f"ecoinvent username : {user or '(none)'}" + (f"   (from {source})" if source else ""))
    print(f"password stored    : {'yes' if psource else 'no'}")
    exists = project in {p.name for p in bd.projects}
    print(f"Brightway project  : {project} ({'exists' if exists else 'DOES NOT EXIST'})")
    if not exists:
        return {"project": False}
    bd.projects.set_current(project)
    db, bio, method = names(version, system_model)
    have = {"project": True, "db": db in bd.databases, "bio": bio in bd.databases,
            "method": method in bd.methods}
    print(f"{db:<28}: {'present' if have['db'] else 'missing'}")
    print(f"{bio:<28}: {'present' if have['bio'] else 'missing'}")
    print(f"GWP100 method        : {'present' if have['method'] else 'missing'}  {method}")
    return have


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--project", required=True, help="Brightway project to install into")
    p.add_argument("--version", default="3.10", help="ecoinvent version (default 3.10)")
    p.add_argument("--system-model", default="cutoff", help="system model (default cutoff)")
    p.add_argument("--check", action="store_true", help="read-only status; prints the username only")
    p.add_argument("--reprompt", action="store_true", help="ask for credentials even if stored")
    p.add_argument("--import", dest="do_import", action="store_true",
                   help=f"import if missing, without asking ({IMPORT_COST})")
    p.add_argument("--methods-only", action="store_true",
                   help="re-install only the namespaced LCIA methods (minutes, not the full import)")
    args = p.parse_args(argv)

    if args.check:
        status(args.project, args.version, args.system_model)
        return 0

    import bw2data as bd
    import bw2io as bi

    ensure_credentials(reprompt=args.reprompt)
    user, _ = resolve_credential("username")
    password, _ = resolve_credential("password")

    is_new = args.project not in {p.name for p in bd.projects}
    bd.projects.set_current(args.project)
    print(("CREATED a new, empty Brightway project: " if is_new
           else "Using existing Brightway project: ") + args.project)
    db, bio, method = names(args.version, args.system_model)

    if args.methods_only:
        bi.import_ecoinvent_release(
            version=args.version, system_model=args.system_model,
            username=user, password=password, biosphere_name=bio,
            lci=False, lcia=True, namespace_lcia_methods=True)
    elif db not in bd.databases or bio not in bd.databases:
        print(f"Missing: {', '.join(n for n in (db, bio) if n not in bd.databases)}")
        if not args.do_import:
            _need_terminal("Confirming the import")
            if not _ask_yes_no(f"Download and import ecoinvent {args.version} "
                               f"{args.system_model} now? This takes {IMPORT_COST}.", False):
                print("Not imported. Re-run when ready.")
                return 0
        bi.import_ecoinvent_release(
            version=args.version, system_model=args.system_model,
            username=user, password=password, biosphere_name=bio)
    else:
        print("Both databases already present; nothing to import.")

    for name in (bio, db):
        assert name in bd.databases, f"missing database after import: {name}"
    assert method in bd.methods, (
        f"LCIA method not installed: {method}. The databases exist, so the "
        "import ran under a bw2io older than 0.9.17 and the methods have no "
        "namespace. Upgrade (see SETUP.md), then re-run with --methods-only.")
    print(f"Ready: {len(bd.Database(db))} activities, {len(bd.Database(bio))} "
          f"biosphere flows, {len(bd.methods)} LCIA methods.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
