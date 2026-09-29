"""List / search available LCIA methods in a Brightway project.

The method namespace (first tuple element) must match the biosphere version your
inventory is linked to -- otherwise you characterize against the wrong factors.

Examples:
  python query_methods.py --project <project>
  python query_methods.py --project <project> --families
  python query_methods.py --project <project> --version ecoinvent-3.10 --contains "global warming"
  python query_methods.py --project <project> --version ecoinvent-3.10 --family "IPCC 2021"
"""
import argparse

import bw2data as bd


def main():
    ap = argparse.ArgumentParser(description="List/search Brightway LCIA methods.")
    ap.add_argument("--project", required=True, help="Brightway project name")
    ap.add_argument("--version", help="Filter by namespace m[0], e.g. ecoinvent-3.10")
    ap.add_argument("--family", help="Case-insensitive ALL-WORDS filter on method "
                                     "family m[1] (every word must appear), e.g. "
                                     "'ipcc' or 'recipe midpoint (h)'")
    ap.add_argument("--contains", help="Free-text filter over the whole method key")
    ap.add_argument("--families", action="store_true",
                    help="Print the distinct method families (optionally within --version)")
    args = ap.parse_args()

    bd.projects.set_current(args.project)
    methods = list(bd.methods)

    if args.families:
        fams = sorted({m[1] for m in methods if len(m) > 1
                       and (not args.version or m[0] == args.version)})
        scope = f" under {args.version}" if args.version else ""
        print(f"{len(fams)} method families{scope}:")
        for f in fams:
            print("  -", f)
        return

    fam_tokens = args.family.lower().split() if args.family else None
    shown = 0
    for m in methods:
        if args.version and m[0] != args.version:
            continue
        if fam_tokens and (len(m) < 2
                           or not all(t in m[1].lower() for t in fam_tokens)):
            continue
        if args.contains and args.contains.lower() not in " ".join(map(str, m)).lower():
            continue
        try:
            unit = bd.Method(m).metadata.get("unit", "?")
        except Exception:
            unit = "?"
        print(f"{m}  |  {unit}")
        shown += 1
    print(f"\n{shown} method(s) matched (of {len(methods)} total).")
    if shown == 0:
        fams = sorted({m[1] for m in methods if len(m) > 1
                       and (not args.version or m[0] == args.version)})
        print("No matches. Available families"
              + (f" under {args.version}" if args.version else "") + ":")
        for f in fams:
            print("  -", f)


if __name__ == "__main__":
    main()
