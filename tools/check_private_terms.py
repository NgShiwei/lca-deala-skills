#!/usr/bin/env python3
"""Pre-release guard: fail if a private project's terms appear in this repo.

These skills were extracted from an unpublished study. Its numbers, routes,
country lists, process names and database names must never reach this
repository, including its history. This script scans every tracked and
untracked (non-ignored) file for them and exits non-zero on any hit.

The forbidden terms are kept as salted SHA-256 hashes in
``tools/private_terms.json``, which is git-ignored and never leaves the
maintainer's machine (set ``PRIVATE_TERMS_JSON`` to keep it elsewhere). Even
hashed, short terms such as numbers could be recovered by brute force, so the
file is not published. Without it the guard cannot run and says so. A hit
prints the offending text from the scanned file (it is already there), never
the stored list.

Four kinds of term:

* ``ngram``      a whole token or a phrase of up to four tokens, e.g. a number
                 or a multi-word process name;
* ``substring``  a string matched anywhere inside a single token, e.g. a name
                 fragment that appears inside longer identifiers;
* ``countryset`` an exact set of ISO2 codes, compared per line, per paragraph
                 and per file, so a copied country list is caught whatever its
                 order or formatting.

Usage::

    python tools/check_private_terms.py            # scan the repo, exit 1 on a hit
    python tools/hash_private_terms.py terms.txt   # regenerate private_terms.json

Keep the plain-text term file outside the repository. Run the guard before
every commit and every release.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
TERMS_JSON = Path(os.environ.get("PRIVATE_TERMS_JSON") or HERE / "private_terms.json")

MAX_NGRAM = 4
COUNTRYSET_MIN = 10          # smaller sets are too common to be meaningful

_TOKEN_RE = re.compile(r"[a-z0-9_.,/\-→]+")
_EDGE_PUNCT = ".,/-"
_ISO2_RE = re.compile(r"\b[A-Z]{2}\b")


def digest(salt: str, kind: str, term: str) -> str:
    return hashlib.sha256(f"{salt}\0{kind}\0{term}".encode("utf-8")).hexdigest()


def normalise(text: str) -> str:
    """Lower-case, and write every route arrow as a bare '→'.

    'AA -> BB', 'AA→BB' and 'AA → BB' all become 'aa→bb', so one stored hash
    covers every spelling.
    """
    text = text.lower().replace("->", "→")
    return re.sub(r"\s*→\s*", "→", text)


def tokens(text: str) -> list[str]:
    out = []
    for t in _TOKEN_RE.findall(normalise(text)):
        t = t.strip(_EDGE_PUNCT)
        if t:
            out.append(t)
    return out


def country_key(codes) -> str:
    return " ".join(sorted(set(codes)))


def _files() -> list[Path]:
    try:
        listed = subprocess.run(
            ["git", "ls-files", "-co", "--exclude-standard", "-z"],
            cwd=REPO, check=True, capture_output=True).stdout.decode()
        paths = [REPO / p for p in listed.split("\0") if p]
    except (OSError, subprocess.CalledProcessError):
        paths = [p for p in REPO.rglob("*") if ".git" not in p.parts]
    return [p for p in paths if p.is_file() and p != TERMS_JSON]


def _read(path: Path) -> str | None:
    data = path.read_bytes()
    if b"\0" in data[:4096]:
        return None                      # binary
    return data.decode("utf-8", errors="replace")


def scan(files=None, terms_path: Path = TERMS_JSON) -> list[str]:
    """Return one message per hit. Empty list = clean."""
    spec = json.loads(terms_path.read_text(encoding="utf-8"))
    salt = spec["salt"]
    ngrams = set(spec["ngram"])
    substr = {int(k): set(v) for k, v in spec["substring"].items()}
    csets = set(spec["countryset"])

    hits = []
    for path in files if files is not None else _files():
        text = _read(path)
        if text is None:
            continue
        rel = path.relative_to(REPO) if REPO in path.parents else path
        blocks, block = [], []
        file_codes = []
        for lineno, line in enumerate(text.splitlines(), 1):
            toks = tokens(line)
            for n in range(1, MAX_NGRAM + 1):
                for i in range(len(toks) - n + 1):
                    phrase = " ".join(toks[i:i + n])
                    if digest(salt, "ngram", phrase) in ngrams:
                        hits.append(f"{rel}:{lineno}: private term {phrase!r}")
            for tok in toks:
                for length, hashes in substr.items():
                    for i in range(len(tok) - length + 1):
                        if digest(salt, "substring", tok[i:i + length]) in hashes:
                            hits.append(f"{rel}:{lineno}: private fragment in {tok!r}")
                            break
            codes = _ISO2_RE.findall(line)
            file_codes += codes
            if len(set(codes)) >= COUNTRYSET_MIN and \
                    digest(salt, "countryset", country_key(codes)) in csets:
                hits.append(f"{rel}:{lineno}: private country list")
            if line.strip():
                block += codes
            else:
                blocks.append(block)
                block = []
        blocks += [block, file_codes]
        for codes in blocks:
            if len(set(codes)) >= COUNTRYSET_MIN and \
                    digest(salt, "countryset", country_key(codes)) in csets:
                hits.append(f"{rel}: private country list (paragraph or whole file)")
    return sorted(set(hits))


def main() -> int:
    if not TERMS_JSON.is_file():
        print(f"FAIL: no term list at {TERMS_JSON}. It is kept off the public repository; "
              "regenerate it with tools/hash_private_terms.py, or set PRIVATE_TERMS_JSON.")
        return 2
    hits = scan()
    if hits:
        print("\n".join(hits))
        print(f"\nFAIL: {len(hits)} private-study hit(s). Remove them before committing.")
        return 1
    print(f"OK: no private-study terms in {len(_files())} files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
