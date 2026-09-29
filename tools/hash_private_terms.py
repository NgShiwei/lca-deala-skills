#!/usr/bin/env python3
"""Regenerate ``private_terms.json`` from a plain-text term file.

The term file must live OUTSIDE this repository. One term per line, as
``<kind><TAB><term>``, where kind is ``token``, ``phrase``, ``substring`` or
``countryset`` (space-separated ISO2 codes). Blank lines and ``#`` lines are
ignored. ``token`` and ``phrase`` are stored together as ``ngram``.

    python tools/hash_private_terms.py ~/private/terms.txt
"""
from __future__ import annotations

import json
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_private_terms import (MAX_NGRAM, TERMS_JSON, country_key,  # noqa: E402
                                 digest, normalise, tokens)


def build(lines, salt: str) -> dict:
    spec = {"salt": salt, "ngram": [], "substring": {}, "countryset": []}
    for raw in lines:
        raw = raw.rstrip("\n")
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        kind, term = raw.split("\t", 1)
        if kind in ("token", "phrase"):
            toks = tokens(term)
            if not 1 <= len(toks) <= MAX_NGRAM:
                raise ValueError(f"{term!r} is {len(toks)} tokens; max {MAX_NGRAM}")
            spec["ngram"].append(digest(salt, "ngram", " ".join(toks)))
        elif kind == "substring":
            frag = normalise(term)
            spec["substring"].setdefault(str(len(frag)), []).append(
                digest(salt, "substring", frag))
        elif kind == "countryset":
            spec["countryset"].append(digest(salt, "countryset", country_key(term.split())))
        else:
            raise ValueError(f"unknown kind {kind!r}")
    spec["ngram"].sort()
    spec["countryset"].sort()
    for v in spec["substring"].values():
        v.sort()
    return spec


def main(argv) -> int:
    if len(argv) != 1:
        print(__doc__)
        return 2
    src = Path(argv[0]).resolve()
    if TERMS_JSON.parent.parent in src.parents:
        print("Refusing: keep the plain-text term file outside the repository.")
        return 2
    salt = secrets.token_hex(16)
    spec = build(src.read_text(encoding="utf-8").splitlines(), salt)
    TERMS_JSON.write_text(json.dumps(spec, indent=1) + "\n", encoding="utf-8")
    n = len(spec["ngram"]) + sum(map(len, spec["substring"].values())) + len(spec["countryset"])
    print(f"wrote {n} hashed terms to {TERMS_JSON}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
