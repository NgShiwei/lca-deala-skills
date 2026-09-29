"""Prove a DEALA cost score by hand.

Hand-computes ``Σ(input_amount × unit_price) / production`` for one activity,
prints every term, and compares it to the native ``bc.MultiLCA`` score under
``('DEALA-Cost (BEIC 1)', 'total cost', 'TC')``.  A ratio of 1.000000 is the
evidence that the native method does what the arithmetic says.

Usage (Windows: use the ``py`` launcher; ``python`` is often not on PATH)::

    set PYTHONIOENCODING=utf-8
    py verify_cost.py --project <project> ^
        --db "Costed_<modular db>" ^
        --activity "<activity name substring>" --country <XX>

    # regression gate over every cut-off activity
    py verify_cost.py --project <project> --db "Costed_<modular db>" --all

Only one Python process may hold the project at a time — kill stray
``python.exe`` (and shut the Jupyter *server*, not just the tab) first.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bw2data as bd  # noqa: E402

import deala_helpers as dh  # noqa: E402


def select_activity(db_name: str, pattern: str, country: str | None):
    """Find exactly one activity. Never silently picks ``[0]`` on ambiguity."""
    db = bd.Database(db_name)
    hits = [a for a in db if pattern.lower() in a["name"].lower()]
    if country:
        hits = [a for a in hits if "{" + country + "}" in a["name"]]
    if not hits:
        raise SystemExit(f"No activity in '{db_name}' matches {pattern!r}"
                         + (f" for country {country}" if country else ""))
    if len(hits) > 1:
        listing = "\n".join(f"    {a['name']}" for a in hits[:20])
        raise SystemExit(
            f"{len(hits)} activities match {pattern!r}"
            + (f" for {country}" if country else "")
            + f" — narrow the selector, do not guess:\n{listing}"
        )
    return hits[0]


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--project", required=True, help="Brightway project name")
    p.add_argument("--db", required=True, help="modular database holding the DEALA cut-off activities")
    p.add_argument("--input-db", default=dh.COST_INPUT_DB, help="DEALA input (priced) activity database")
    p.add_argument("--activity", help="substring of the activity name to verify")
    p.add_argument("--country", help="2-letter code, matched as '{XX}' in the name")
    p.add_argument("--all", action="store_true",
                   help="cross-check every cut-off activity instead of one worked example")
    p.add_argument("--clean", action="store_true",
                   help="run bd.databases.clean() first (needed after any edit)")
    p.add_argument("--csv", help="write results to this CSV")
    p.add_argument("--tol", type=float, default=1e-6, help="relative tolerance for PASS")
    args = p.parse_args(argv)

    if not args.all and not args.activity:
        p.error("give --activity (worked example) or --all (regression gate)")

    dh.check_environment()
    bd.projects.set_current(args.project)
    if args.clean:
        dh.clean()

    if args.all:
        acts = dh.find_cutoff_activities(args.db)
        print(f"[read] {len(acts)} cut-off activities in '{args.db}'")
        df = dh.cross_check_all(acts, cost_input_db=args.input_db)
        worst = df.loc[df["abs_diff"].idxmax()]
        ok = bool((df["abs_diff"] <= args.tol * df["native"].abs().clip(lower=1.0)).all())
        print(f"[worst] {worst['process_name']}: manual {worst['manual']:.9f} vs "
              f"native {worst['native']:.9f} (ratio {worst['ratio']:.6f})")
        print("PASS — every activity's native score reproduces its hand calculation."
              if ok else "FAIL — at least one activity disagrees.")
        if args.csv:
            df.to_csv(args.csv, index=False)
            print(f"[out] wrote {args.csv}")
        return 0 if ok else 1

    act = select_activity(args.db, args.activity, args.country)
    result = dh.verify(act, cost_input_db=args.input_db, tol=args.tol)
    if args.csv:
        result["breakdown"].to_csv(args.csv, index=False)
        print(f"[out] wrote {args.csv}")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
