#!/usr/bin/env python3
"""Helpers for the lci-extractor skill -- pure Python, standard library only.

The skill's job is to read a scientific article (PDF + SI) and transcribe its
life-cycle inventory into `assets/lci_extraction_template.csv` (two blocks:
[METADATA] + [EXCHANGES], with provenance columns). These helpers then:

  * load_extraction(path)          -> (metadata: dict, exchanges: list[dict])
  * load_extraction_multi(path)    -> [(metadata, exchanges), ...]  multi-tier study
  * gap_check(metadata, exchanges) -> list[str]   missing categories/fields to raise
  * validate(metadata, exchanges)  -> list[str]   integrity problems to fix
  * to_new_process_template(src,d) -> writes the lca-calculator [HEADER]/[EXCHANGES]
                                      CSV (drops provenance cols + characterized rows)
  * to_nested_template(srcs, dst)  -> writes ONE nested calculator file from several
                                      extractions: internal foreground links wired,
                                      burden-free feedstocks emitted as zero-input
                                      children, ISO/ILCD documentation per process
  * build_nested / format_nested_report -> the same, as data + batched questions
  * pdf_page_count(path)           -> int | None  (drives the >20-page windowed read)
  * page_windows(n, size=20)       -> [(start,end), ...]

CLI:
  python lci_helpers.py --pageinfo <file.pdf>   page count + the <=20-page read windows
  python lci_helpers.py --selftest              round-trips the bundled example template
  python lci_helpers.py --selftest-nested       round-trips the bundled nested fixture
  python lci_helpers.py --to-template <src.csv> [<dst.csv>]   emit calculator template
  python lci_helpers.py --to-nested-template <dst.csv> <src.csv>...
        [--working-db NAME] [--burden-free DESC] [--link 'Proc::desc=Child']
        Emits the multi-tier file. REFUSES to write while any ambiguous internal
        link, unconfirmed burden-free row, internal unit mismatch or duplicate
        process name is outstanding -- settle those with the user, then re-run.

Nothing here touches Brightway; the linking + LCIA happens in the lca-calculator
skill after `to_new_process_template` hands off the CSV.
"""
from __future__ import annotations

import csv
import io
import os
import re
import sys
import tempfile

# --------------------------------------------------------------------------- #
# Template parsing
# --------------------------------------------------------------------------- #

_META_TAG = "[METADATA]"
_EXCH_TAG = "[EXCHANGES]"

# Exchange columns carried over to the lca-calculator new_process_template.
# Everything else in [EXCHANGES] is provenance and is dropped on handoff.
_CALC_EXCHANGE_COLS = ["role", "description", "quantity", "unit",
                       "link_name", "source_db", "location", "factor"]

# The impact-result rows we keep for the cross-check but must NOT hand off as
# inventory flows.
_CHARACTERIZED = "characterized"

_VALID_ROLES = {"material", "energy", "transport", "emission", "coproduct", "waste"}


def _read_blocks_multi(path):
    """Split a template file into ONE OR MORE [METADATA]/[EXCHANGES] block pairs.

    A single-process extraction yields a one-element list. A multi-process extraction
    repeats the pair, exactly as the lca-calculator's nested template repeats
    [HEADER]/[EXCHANGES]. Returns [{_META_TAG: [...], _EXCH_TAG: [...]}, ...].
    """
    with open(path, newline="", encoding="utf-8-sig") as fh:
        rows = [ln for ln in fh
                if ln.strip() and not ln.lstrip().startswith("#")]

    blocks, cur, section = [], None, None
    for ln in rows:
        tag = ln.strip().upper()
        if tag == "[PROCESS]":          # optional visual separator
            continue
        if tag == _META_TAG:
            if cur is not None:
                blocks.append(cur)
            cur, section = {_META_TAG: [], _EXCH_TAG: []}, _META_TAG
            continue
        if tag == _EXCH_TAG:
            if cur is None:
                raise ValueError(f"{path}: {_EXCH_TAG} before any {_META_TAG}.")
            section = _EXCH_TAG
            continue
        if cur is None or section is None:
            raise ValueError(f"Expected a {_META_TAG} marker before any data row.")
        cur[section].append(ln)
    if cur is not None:
        blocks.append(cur)
    return blocks


def _read_blocks(path):
    """Split a SINGLE-process template file into its labelled blocks."""
    blocks = _read_blocks_multi(path)
    if len(blocks) > 1:
        raise ValueError(
            f"{path} holds {len(blocks)} processes. load_extraction() reads a "
            f"single-process extraction; use load_extraction_multi() (and "
            f"to_nested_template) for a multi-tier inventory.")
    return blocks[0] if blocks else {_META_TAG: [], _EXCH_TAG: []}


def load_extraction(path):
    """Parse a filled single-process extraction into (metadata dict, exchanges list).

    `quantity`, `original_quantity` and `factor` are coerced to float where present
    and non-blank; blanks are left as "" so gap_check/validate can flag them.
    """
    return _parse_block(_read_blocks(path), path)


def load_extraction_multi(path):
    """Parse an extraction holding ONE OR MORE processes -> [(metadata, exchanges), ...].

    Mirrors the lca-calculator's `load_inventory_multi`: repeat the
    [METADATA]/[EXCHANGES] pair once per unit process in a multi-tier study, so one
    paper's whole chain can live in one file. Order does not matter.
    """
    blocks = _read_blocks_multi(path)
    if not blocks:
        raise ValueError(f"{path}: no {_META_TAG} block found.")
    return [_parse_block(blk, path) for blk in blocks]


def _parse_block(blocks, path=""):
    """Turn one [METADATA]/[EXCHANGES] block pair into (metadata, exchanges)."""
    if not blocks[_META_TAG] or not blocks[_EXCH_TAG]:
        raise ValueError(f"{path}: template must contain both a {_META_TAG} and an "
                         f"{_EXCH_TAG} block, each with a column-name row.")

    meta_rows = list(csv.DictReader(blocks[_META_TAG]))
    if len(meta_rows) != 1:
        raise ValueError(f"{_META_TAG} must have exactly one value row, got "
                         f"{len(meta_rows)}.")
    metadata = {(k or "").strip(): (v or "").strip()
                for k, v in meta_rows[0].items() if k is not None}

    exchanges = []
    for row in csv.DictReader(blocks[_EXCH_TAG]):
        ex = {(k or "").strip(): (v or "").strip()
              for k, v in row.items() if k is not None}
        for numeric in ("quantity", "original_quantity", "factor"):
            val = ex.get(numeric, "")
            if val not in ("", None):
                try:
                    ex[numeric] = float(val)
                except ValueError:
                    pass  # leave the raw string; validate() will flag it
        exchanges.append(ex)
    return metadata, exchanges


# --------------------------------------------------------------------------- #
# Integrity checks
# --------------------------------------------------------------------------- #

# Metadata fields that a defensible extraction should carry.
_REQUIRED_META = ["functional_unit", "reference_flow", "system_boundary",
                  "geography", "allocation", "background_database"]

# Inventory categories to expect (presence of the *category*, not a row count).
_EXPECTED_ROLES = ["material", "energy"]


def gap_check(metadata, exchanges):
    """Return human-readable notes on missing metadata fields / inventory categories.

    Mirrors the lca-calculator gap check: about the *presence* of each category, so
    the extractor knows what to go back to the paper (or the SI) for before handoff.
    """
    notes = []
    for field in _REQUIRED_META:
        if not metadata.get(field):
            notes.append(f"metadata: '{field}' is missing")

    fg = [e for e in exchanges if e.get("data_type") != _CHARACTERIZED]
    roles_present = {e.get("role") for e in fg}
    for role in _EXPECTED_ROLES:
        if role not in roles_present:
            notes.append(f"inventory: no '{role}' flow found -- confirm the paper "
                         f"really reports none, or check the SI")
    if not fg:
        notes.append("inventory: no foreground exchange rows at all")
    return notes


def validate(metadata, exchanges):
    """Return a list of integrity problems that must be fixed before handoff.

    These are correctness issues (bad role, unnormalised or non-numeric quantity,
    missing provenance, a characterized result mis-filed as an inventory flow), as
    opposed to the 'is a category absent' gap check.
    """
    issues = []
    for i, ex in enumerate(exchanges, 1):
        where = f"exchange row {i} ({ex.get('description') or '?'})"

        role = ex.get("role", "")
        dtype = ex.get("data_type", "")

        if dtype == _CHARACTERIZED:
            # A kept impact-result row: fine to store, must never be handed off.
            if role in _VALID_ROLES:
                issues.append(f"{where}: data_type=characterized but role='{role}' "
                              f"looks like an inventory flow -- a characterised impact "
                              f"(kg CO2-eq etc.) is NOT an inventory exchange")
            continue

        if role not in _VALID_ROLES:
            issues.append(f"{where}: role '{role}' is not one of "
                          f"{sorted(_VALID_ROLES)}")

        if not isinstance(ex.get("quantity"), float):
            issues.append(f"{where}: quantity '{ex.get('quantity')}' is not numeric "
                          f"(is it normalised to one functional unit?)")
        if not ex.get("unit"):
            issues.append(f"{where}: unit is missing")
        if not ex.get("source_location"):
            issues.append(f"{where}: source_location is missing -- every value must "
                          f"cite where in the paper/SI it came from")

        # Cheap unit-smell: a characterised unit hiding in a foreground row.
        unit = (ex.get("unit") or "").lower()
        if "co2" in unit or "eq" in unit:
            issues.append(f"{where}: unit '{ex.get('unit')}' looks like an impact "
                          f"score, not an inventory unit -- should this be "
                          f"data_type=characterized (and dropped), not a flow?")
    return issues


# --------------------------------------------------------------------------- #
# Handoff to the lca-calculator new_process_template
# --------------------------------------------------------------------------- #

def _parse_leading_amount(text):
    """Pull a leading '<number> <unit>' out of e.g. '1 kg SPI' -> (1.0, 'kg').

    The unit may contain digits AFTER its first letter (m3, m2, m2a, CO2), but must
    start with a letter or '%'. An earlier `[A-Za-z%/.]+` pattern truncated 'm3' to
    'm' -- silently turning a cubic metre of water into a metre.
    """
    m = re.match(r"\s*([-+]?\d*\.?\d+)\s*([A-Za-z%][A-Za-z0-9%/·.-]*)", text or "")
    if not m:
        return None, None
    try:
        return float(m.group(1)), m.group(2)
    except ValueError:
        return None, m.group(2)


class UnitBasisError(ValueError):
    """The process's output basis cannot be established without guessing.

    Raised instead of silently defaulting to '1 unit', which would rebase the whole
    inventory by an unknown factor. Ask the user for the output amount + unit.
    """


# Mass units -> kilograms. Used to canonicalise the OUTPUT (production) basis only.
# 'mt' is deliberately absent: it reads as both 'metric ton' and 'megatonne', and
# guessing between them is exactly what this module must not do.
_MASS_TO_KG = {
    "kg": 1.0, "kilogram": 1.0, "kilograms": 1.0, "kilogramme": 1.0,
    "g": 1e-3, "gram": 1e-3, "grams": 1e-3, "gramme": 1e-3,
    "mg": 1e-6, "milligram": 1e-6, "milligrams": 1e-6,
    "ug": 1e-9, "µg": 1e-9, "microgram": 1e-9,
    "t": 1e3, "ton": 1e3, "tonne": 1e3, "tonnes": 1e3, "metric ton": 1e3,
    "kt": 1e6, "kilotonne": 1e6,
}

# Mirrors lca_helpers._UNIT_ALIASES so a 'kg' vs 'kilogram' difference does not read
# as a unit mismatch when comparing a parent's consumption to a child's output.
_UNIT_ALIASES = {
    "kg": "kilogram", "kilograms": "kilogram", "kilogramme": "kilogram",
    "g": "gram", "grams": "gram", "mg": "milligram",
    "t": "ton", "tonne": "ton", "tonnes": "ton", "metric ton": "ton",
    "kwh": "kilowatt hour", "wh": "watt hour", "mwh": "megawatt hour",
    "mj": "megajoule", "kj": "kilojoule", "gj": "gigajoule",
    "tkm": "ton kilometer", "tonne kilometer": "ton kilometer",
    "km": "kilometer", "m": "meter", "m2": "square meter",
    "m2a": "square meter-year", "m3": "cubic meter", "m³": "cubic meter",
    "l": "litre", "liter": "litre", "item": "unit", "p": "unit", "pcs": "unit",
    "h": "hour", "hr": "hour",
}


def _norm_unit(u):
    u = (u or "").strip().lower()
    return _UNIT_ALIASES.get(u, u)


def _resolve_output_basis(metadata):
    """Establish the process's production (output) amount + unit, or refuse.

    Returns `(quantity, unit, note)` where `note` describes any conversion applied
    (None when none was needed).

    WHY THIS EXISTS -- the gram/kilogram basis bug:
    Brightway does NOT convert units across an exchange. It scales a child process by
    the raw ratio `parent_amount / child_output_amount`. So a lab process whose
    `reference_flow` reads "0.64 g", written out verbatim as output `0.64` unit `g`
    and then consumed by a parent as "0.11 kg", is scaled by 0.11/0.64 instead of
    110/0.64 -- a silent 1000x underestimate. This bit the FLAM lab tiers (T4/T5).

    THE FIX is an exact relabelling, not a guess: the physical output is unchanged, so
    "0.64 g" becomes "0.00064 kg". The exchange rows are deliberately NOT rescaled --
    they are already expressed per that same physical output, so converting only the
    output's unit leaves the process internally consistent while making its unit match
    the kg basis parents consume in.

    When no leading '<number> <unit>' can be found at all, this REFUSES (raises
    UnitBasisError) rather than falling back to '1 unit' -- an unknown rebase is worse
    than a stop-and-ask.
    """
    ref = metadata.get("reference_flow", "")
    qty, unit = _parse_leading_amount(ref)
    if qty is None:
        qty, unit = _parse_leading_amount(metadata.get("functional_unit", ""))
    if qty is None or not unit:
        raise UnitBasisError(
            f"Cannot establish the output basis: neither reference_flow ({ref!r}) nor "
            f"functional_unit ({metadata.get('functional_unit', '')!r}) begins with a "
            f"'<number> <unit>' amount. Ask the user for this process's output amount "
            f"and unit. Refusing to default to '1 unit', which would silently rebase "
            f"every exchange by an unknown factor.")

    factor = _MASS_TO_KG.get(unit.strip().lower())
    if factor is None or factor == 1.0:
        return qty, unit, None
    converted = qty * factor
    return converted, "kg", (
        f"output basis {_num(qty)} {unit} -> {_num(converted)} kg "
        f"(exact unit conversion of the SAME physical output; exchange rows left "
        f"untouched. Brightway does not convert units across an exchange, so a "
        f"sub-kg output unit silently mis-scales every parent that consumes it)")


def to_new_process_template(src, dst=None, working_database="LCA_working"):
    """Convert a filled extraction template into the lca-calculator [HEADER]/[EXCHANGES]
    CSV, dropping every provenance column and every characterized (impact-result) row.

    Returns the destination path. The output parses cleanly with the lca-calculator's
    `load_inventory_csv`; linking + LCIA happen there. `link_name`/`source_db`/etc.
    pass through as suggestions if present but are left for `resolve_links` to confirm.
    """
    metadata, exchanges = load_extraction(src)
    if dst is None:
        base, _ = os.path.splitext(src)
        dst = base + "_calc.csv"

    # Reconciles the reference-flow unit against the kg basis a parent would consume
    # in, or refuses. See _resolve_output_basis for the 1000x gram/kilogram bug.
    out_qty, out_unit, basis_note = _resolve_output_basis(metadata)

    name = (metadata.get("title") or metadata.get("reference_flow")
            or "Extracted process")
    ref_product = metadata.get("reference_flow") or name
    # new_process_template allocation vocabulary is none|economic|mass.
    allocation = (metadata.get("allocation") or "none").lower()
    if allocation not in ("none", "economic", "mass"):
        allocation = "none"  # e.g. 'substitution' is handled at build time, not here
    comment = "; ".join(x for x in (
        metadata.get("reference", ""),
        "extracted via lci-extractor",
    ) if x)

    kept = [e for e in exchanges if e.get("data_type") != _CHARACTERIZED]

    lines = []
    lines.append("# Generated by lci-extractor to_new_process_template().")
    lines.append("# Provenance columns and characterized (impact-result) rows dropped.")
    lines.append("# Review link_name/source_db/location before building -- these are")
    lines.append("# suggestions only; the lca-calculator's resolve_links confirms them.")
    if basis_note:
        lines.append(f"# UNIT BASIS: {basis_note}")
    lines.append(_META_TAG.replace("METADATA", "HEADER"))  # -> [HEADER]
    lines.append("name,reference_product,output_quantity,output_unit,location,"
                 "working_database,allocation,comment")
    lines.append(_csv_row([name, ref_product, _num(out_qty), out_unit or "unit",
                           metadata.get("geography", ""), working_database,
                           allocation, comment]))
    lines.append(_EXCH_TAG)
    lines.append(",".join(_CALC_EXCHANGE_COLS))
    for e in kept:
        lines.append(_csv_row([
            e.get("role", ""), e.get("description", ""), _num(e.get("quantity", "")),
            e.get("unit", ""), e.get("link_name", ""), e.get("source_db", ""),
            e.get("location", ""), _num(e.get("factor", "")),
        ]))

    with open(dst, "w", newline="", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return dst


def _num(v):
    """Render a float without a trailing '.0'; pass strings/blanks through."""
    if isinstance(v, float):
        return str(int(v)) if v.is_integer() else repr(v)
    return "" if v is None else str(v)


def _csv_row(values):
    buf = io.StringIO()
    csv.writer(buf).writerow(["" if v is None else v for v in values])
    return buf.getvalue().rstrip("\r\n")


# --------------------------------------------------------------------------- #
# Nested / multi-tier handoff: many extractions -> ONE lca-calculator file
# --------------------------------------------------------------------------- #
# Emits assets/new_process_template_nested.csv format: the [HEADER]/[EXCHANGES] pair
# repeated once per process, consumed by lca_helpers.load_inventory_multi ->
# resolve_chain -> build_chain.
#
# Three things this does that the single-process handoff cannot:
#   1. A foreground-to-foreground row gets source_db = the working database and
#      link_name = the child's EXACT name, instead of a blank link the calculator
#      would then try (and fail) to find in a background database.
#   2. A burden-free feedstock becomes its own process with an empty [EXCHANGES]
#      block -- a zero-input child that scores zero -- rather than a blank-link row.
#      Dropping the row instead would hide the cut-off assumption and break the mass
#      balance; see the nested template's own note.
#   3. The ISO 14040/44 + ILCD documentation fields are carried PER PROCESS, because
#      tiers legitimately differ: a lab-scale child routinely has a different
#      reference_year, technology_coverage and data_source from its commercial parent.

_NESTED_HEADER_COLS = [
    "name", "reference_product", "output_quantity", "output_unit", "location",
    "working_database", "allocation", "allocation_justification", "system_boundary",
    "cutoff_rules", "technology_coverage", "reference_year", "data_source", "comment",
]
_NESTED_EXCHANGE_COLS = [
    "role", "description", "quantity", "unit", "link_name", "source_db",
    "location", "factor", "link_rationale",
]

# Brightway eval()s the location string when processing a database, so descriptive
# prose ("India (Case A) / VN proxy") raises a SyntaxError at build time. Accept only
# things that look like real location codes; send anything else to the user.
_GEO_OK = re.compile(r"^(?:GLO|RoW|RoE|[A-Z]{2,3}|[A-Z]{2}-[A-Za-z0-9-]{1,12}|"
                     r"[A-Z]{2,5}(?:,\s?[A-Z]{2,5})*)$")

# Structural words dropped before matching an exchange to a sibling process, so
# "chitosan" matches a process named "Chitosan production".
_LINK_STOPWORDS = {
    "production", "producing", "produced", "market", "for", "of", "the", "a", "an",
    "and", "process", "processing", "from", "at", "plant", "input", "inputs",
    "kg", "g", "mg", "t", "l", "mj", "kwh", "tkm", "km", "m2", "m3", "unit", "units",
}

# A blank-link row whose notes say this is only ever burden-free by CHOICE. Detected,
# never acted on unconfirmed: promoting a row to a zero-burden child is a modelling
# decision, so it surfaces as a question.
_BF_HINTS = ("burden-free", "burden free", "burdenfree", "cut-off", "cutoff",
             "cut off", "zero burden", "no burden", "free of burden",
             "carries no burden", "waste input")


def _tokens(text):
    return {t for t in re.split(r"[^0-9a-z]+", (text or "").lower())
            if t and t not in _LINK_STOPWORDS}


def _geography_code(geo):
    """(code, note) -- blank the code and explain when `geo` is prose, not a code."""
    g = (geo or "").strip()
    if not g:
        return "", None
    if _GEO_OK.match(g):
        return g, None
    return "", (f"geography {g!r} is prose, not a Brightway location code -- left "
                f"BLANK (Brightway eval()s this field, so prose raises a SyntaxError "
                f"at build time) and preserved in comment. Ask the user for the "
                f"ISO2 / GLO / RoW code.")


def _sibling_matches(ex, siblings):
    """Which sibling processes could this exchange be pointing at?

    An exact (case-insensitive) name match wins outright. Otherwise every meaningful
    token of the exchange must appear in the candidate's name or reference product --
    so "chitosan" finds "Chitosan production" but never "Chitin production". Returns
    a list; >1 hit is an ambiguity for the user, not something to pick from.
    """
    cand = (ex.get("link_name") or "").strip() or (ex.get("description") or "").strip()
    if not cand:
        return []
    exact = [p["name"] for p in siblings
             if cand.lower() == p["name"].strip().lower()]
    if exact:
        return exact
    ctok = _tokens(cand)
    if not ctok:
        return []
    return [p["name"] for p in siblings
            if ctok <= (_tokens(p["name"]) | _tokens(p["reference_product"]))]


def _looks_burden_free(ex):
    """True if an unlinked row reads like a burden-free feedstock (a CANDIDATE only)."""
    if (ex.get("link_name") or "").strip():
        return False
    txt = " ".join(str(ex.get(k, "")) for k in ("notes", "description")).lower()
    return any(h in txt for h in _BF_HINTS)


def _bf_key(proc_name, desc):
    return (proc_name.strip().lower(), (desc or "").strip().lower())


def _header_from_metadata(metadata, working_database):
    """Map one extraction's [METADATA] onto the calculator's [HEADER] fields."""
    notes = []
    name = (metadata.get("process_name") or metadata.get("title")
            or metadata.get("reference_flow") or "").strip()
    if not name:
        raise ValueError(
            "This extraction has no process_name, title or reference_flow, so its "
            "process cannot be named -- and a nested file links children BY NAME. "
            "Ask the user what to call it.")

    out_qty, out_unit, basis_note = _resolve_output_basis(metadata)
    if basis_note:
        notes.append(("unit_basis", name, basis_note))

    location, geo_note = _geography_code(metadata.get("geography"))
    if geo_note:
        notes.append(("geography", name, geo_note))

    alloc_raw = (metadata.get("allocation") or "none").strip().lower()
    allocation = alloc_raw if alloc_raw in ("none", "economic", "mass") else "none"
    if allocation != alloc_raw:
        notes.append(("allocation", name, (
            f"paper states allocation={alloc_raw!r}, which is outside the template's "
            f"none|economic|mass vocabulary; written as 'none'. If it is substitution, "
            f"the co-product rows drive it at build time -- confirm with the user.")))

    comment_bits = [metadata.get("notes", ""), "extracted via lci-extractor"]
    if geo_note:
        comment_bits.insert(0, f"geography as stated: {metadata.get('geography')}")

    header = {
        "name": name,
        "reference_product": metadata.get("reference_flow") or name,
        "output_quantity": out_qty,
        "output_unit": out_unit,
        "location": location,
        "working_database": working_database,
        "allocation": allocation,
        "allocation_justification": metadata.get("allocation_justification", ""),
        "system_boundary": metadata.get("system_boundary", ""),
        "cutoff_rules": metadata.get("cutoff_rules", ""),
        "technology_coverage": metadata.get("technology_coverage", ""),
        "reference_year": metadata.get("reference_year", ""),
        "data_source": (metadata.get("data_source")
                        or metadata.get("reference", "")),
        "comment": "; ".join(x for x in comment_bits if x),
    }
    return header, notes


def _burden_free_child(parent, ex, working_database):
    """A zero-input child process standing in for a burden-free feedstock.

    Its output unit is taken VERBATIM from the parent's row rather than canonicalised:
    the parent consumes N of this unit, so matching them exactly is what keeps the
    internal link correctly scaled.
    """
    name = (ex.get("description") or "").strip() or "burden-free feedstock"
    return {
        "name": name,
        "reference_product": name,
        "output_quantity": 1.0,
        "output_unit": ex.get("unit") or parent["output_unit"],
        "location": parent["location"],
        "working_database": working_database,
        "allocation": "none",
        "allocation_justification": "single output; no burden to allocate",
        "system_boundary": parent["system_boundary"],
        "cutoff_rules": ("burden-free under cut-off: enters the system from an "
                         "upstream system that already bears its impacts"),
        # NOT inherited from the parent: the parent's technology describes how the
        # parent converts this feedstock, not where the feedstock comes from. Copying
        # it down would state something the paper never said (a lab synthesis line as
        # the "technology" of a waste stream). Left blank and reported, so it is asked.
        "technology_coverage": "",
        "reference_year": parent["reference_year"],
        "data_source": parent["data_source"],
        "comment": (f"burden-free feedstock of {parent['name']}; zero-input child -- "
                    f"production exchange only, scores zero"),
        "rows": [],
        "burden_free": True,
        "deps": set(),
    }


def _blank_report():
    return {"duplicates": [], "internal_auto": [], "internal_confirmed": [],
            "internal_ambiguous": [], "unit_mismatch_internal": [],
            "burden_free_created": [], "burden_free_candidates": [],
            "unit_basis": [], "geography": [], "allocation": [],
            "missing_documentation": [], "background_rows": 0}


def build_nested(srcs, working_database="LCA_working", link_map=None,
                 burden_free=None, auto_link=True):
    """Assemble several extractions into one nested-template structure + a report.

    `srcs`        : one path, or a list of paths. Each file may itself hold several
                    processes (load_extraction_multi), so both shapes the handover
                    calls for -- N single-process files, or one multi-process file --
                    work identically.
    `link_map`    : {(process_name, exchange_description): child_name} to settle an
                    ambiguous internal link, or child_name="" to force the row to stay
                    a background link.
    `burden_free` : iterable of exchange descriptions, or (process_name, description)
                    tuples, CONFIRMED by the user as burden-free. Each becomes its own
                    zero-input child process.
    `auto_link`   : link a row to a sibling when EXACTLY ONE sibling matches. Several
                    matches is an ambiguity and always goes to the report instead.

    Returns `(processes, report)`. Nothing is written; `to_nested_template` does that
    only once the report has no blockers. Every judgement call lands in the report.
    """
    if isinstance(srcs, str):
        srcs = [srcs]
    link_map = {(_bf_key(*k)): v for k, v in (link_map or {}).items()}
    bf_spec = set()
    for item in (burden_free or []):
        if isinstance(item, (tuple, list)) and len(item) == 2:
            bf_spec.add(_bf_key(item[0], item[1]))
        else:
            bf_spec.add((None, str(item).strip().lower()))

    report = _blank_report()

    # ---- 1. headers -------------------------------------------------------- #
    procs = []
    for src in srcs:
        for metadata, exchanges in load_extraction_multi(src):
            header, notes = _header_from_metadata(metadata, working_database)
            for kind, who, msg in notes:
                report[kind].append((who, msg))
            for field in ("allocation_justification", "cutoff_rules",
                          "technology_coverage", "reference_year", "data_source"):
                if not header[field]:
                    report["missing_documentation"].append((header["name"], field))
            header["rows"] = [e for e in exchanges
                              if e.get("data_type") != _CHARACTERIZED]
            header["burden_free"] = not header["rows"]
            header["deps"] = set()
            header["src"] = src
            procs.append(header)

    names = [p["name"] for p in procs]
    report["duplicates"] = sorted({n for n in names if names.count(n) > 1})

    # ---- 2. classify every exchange row ------------------------------------ #
    extra = {}          # burden-free children, by name
    for p in procs:
        siblings = [q for q in procs if q["name"] != p["name"]]
        out_rows = []
        for ex in p["rows"]:
            desc = ex.get("description", "")
            key = _bf_key(p["name"], desc)
            target, settled = None, False

            if key in link_map:                       # user settled it explicitly
                target, settled = link_map[key] or None, True
                if target:
                    report["internal_confirmed"].append((p["name"], desc, target))
            elif key in bf_spec or (None, key[1]) in bf_spec:
                child = _burden_free_child(p, ex, working_database)
                if child["name"] in {q["name"] for q in procs}:
                    child["name"] += " (burden-free feedstock)"
                    child["reference_product"] = child["name"]
                if child["name"] not in extra:
                    extra[child["name"]] = child
                    report["burden_free_created"].append(child["name"])
                target = child["name"]
            elif auto_link:
                hits = _sibling_matches(ex, siblings)
                if len(hits) == 1:
                    target = hits[0]
                    report["internal_auto"].append((p["name"], desc, target))
                elif len(hits) > 1:
                    report["internal_ambiguous"].append((p["name"], desc, sorted(hits)))

            # `settled` matters: without it, a row the user deliberately forced to
            # stay a background link (link_map[...] = "") would be re-flagged as a
            # burden-free candidate on every run -- an ask-loop with no way out.
            if target is None and not settled and _looks_burden_free(ex):
                report["burden_free_candidates"].append(
                    (p["name"], desc, ex.get("notes", "")))

            if target is not None:
                tgt = extra.get(target) or next(
                    (q for q in procs if q["name"] == target), None)
                if tgt is not None and _norm_unit(ex.get("unit")) != \
                        _norm_unit(tgt["output_unit"]):
                    report["unit_mismatch_internal"].append(
                        (p["name"], desc, ex.get("unit"), target, tgt["output_unit"]))
                p["deps"].add(target)
                out_rows.append({
                    "role": ex.get("role", ""), "description": desc,
                    "quantity": ex.get("quantity", ""), "unit": ex.get("unit", ""),
                    "link_name": target, "source_db": working_database,
                    "location": "", "factor": ex.get("factor", ""),
                    "link_rationale": (
                        f"INTERNAL foreground link to the '{target}' process defined "
                        f"in this file" + (f"; {ex['notes']}" if ex.get("notes") else "")),
                })
            else:
                report["background_rows"] += 1
                out_rows.append({
                    "role": ex.get("role", ""), "description": desc,
                    "quantity": ex.get("quantity", ""), "unit": ex.get("unit", ""),
                    "link_name": ex.get("link_name", ""),
                    "source_db": ex.get("source_db", ""),
                    "location": ex.get("location", ""),
                    "factor": ex.get("factor", ""),
                    "link_rationale": ex.get("notes", ""),
                })
        p["rows"] = out_rows

    # Burden-free children are synthesised, so their documentation gaps have to be
    # reported here too -- they were not present during the header pass above.
    for child in extra.values():
        for field in ("technology_coverage", "reference_year", "data_source"):
            if not child[field]:
                report["missing_documentation"].append((child["name"], field))

    procs.extend(extra.values())
    return _order_children_first(procs), report


def _order_children_first(procs):
    """Kahn sort so a child is written before every parent that consumes it.

    Order does not change what build_chain does -- it sorts the tiers itself -- but a
    file that reads deepest-child-first is the one a human can actually check. A cycle
    is left at the end rather than dropped, so build_chain still reports it.
    """
    by_name = {p["name"]: p for p in procs}
    remaining = {p["name"]: {d for d in p["deps"] if d in by_name} for p in procs}
    ordered = []
    while remaining:
        ready = sorted(n for n, deps in remaining.items()
                       if not (deps & set(remaining)))
        if not ready:
            ordered += [by_name[n] for n in sorted(remaining)]
            break
        for n in ready:
            ordered.append(by_name[n])
            remaining.pop(n)
    return ordered


def write_nested_template(procs, dst, working_database="LCA_working", report=None):
    """Write the [HEADER]/[EXCHANGES]-per-process file consumed by load_inventory_multi."""
    lines = [
        "# Generated by lci-extractor to_nested_template().",
        "# Nested / multi-tier inventory: the [HEADER]+[EXCHANGES] pair repeats once",
        "# per process. Load with lca_helpers.load_inventory_multi(path), dry-run with",
        "# resolve_chain(processes, working_db), then build with build_chain().",
        "# Written children-first; build_chain re-derives the order regardless.",
        "#",
        "# A row with source_db=" + working_database + " is an INTERNAL foreground link",
        "# to another process in this file. A process with a column row and no data",
        "# rows under [EXCHANGES] is a burden-free (zero-input) feedstock.",
        "# Every other row still needs resolve_links to confirm its background link.",
    ]
    for kind in ("unit_basis", "geography", "allocation"):
        for who, msg in (report or {}).get(kind, []):
            lines.append(f"# {kind.upper()} [{who}]: {msg}")

    for p in procs:
        lines.append("#")
        lines.append("# " + "-" * 75)
        kind = "burden-free child (no inputs)" if p.get("burden_free") else "process"
        lines.append(f"# {kind}: {p['name']}")
        lines.append("[HEADER]")
        lines.append(",".join(_NESTED_HEADER_COLS))
        lines.append(_csv_row([_num(p[c]) if c == "output_quantity" else p.get(c, "")
                               for c in _NESTED_HEADER_COLS]))
        lines.append("[EXCHANGES]")
        lines.append(",".join(_NESTED_EXCHANGE_COLS))
        for r in p["rows"]:
            lines.append(_csv_row([_num(r.get(c, "")) if c in ("quantity", "factor")
                                   else r.get(c, "") for c in _NESTED_EXCHANGE_COLS]))

    with open(dst, "w", newline="", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return dst


class NestedNeedsConfirmation(ValueError):
    """The chain cannot be written without the user settling something first."""

    def __init__(self, report, message):
        super().__init__(message)
        self.report = report


# Report buckets that must be empty before a file is written. Each is a judgement
# call the user owns -- picking one silently is the failure mode this whole skill
# exists to avoid.
_BLOCKING = ("duplicates", "internal_ambiguous", "unit_mismatch_internal",
             "burden_free_candidates")


def format_nested_report(report):
    """Render the report as batched, answerable questions (blockers first)."""
    out = []
    if report["duplicates"]:
        out.append("BLOCKER - duplicate process names (a child is linked BY name, so "
                   "these are unaddressable):")
        out += [f"    {n}" for n in report["duplicates"]]
    if report["internal_ambiguous"]:
        out.append("BLOCKER - ambiguous internal links (which sibling does each row "
                   "mean?):")
        out += [f"    [{p}] '{d}' -> {c}" for p, d, c in report["internal_ambiguous"]]
    if report["unit_mismatch_internal"]:
        out.append("BLOCKER - internal link unit mismatch (Brightway does NOT convert "
                   "units across an exchange, so these WILL mis-scale):")
        out += [f"    [{p}] '{d}' is {u} but '{t}' outputs {tu}"
                for p, d, u, t, tu in report["unit_mismatch_internal"]]
    if report["burden_free_candidates"]:
        out.append("BLOCKER - rows that read as burden-free but were not confirmed "
                   "(promote to a zero-input child, or link to a background "
                   "activity?):")
        out += [f"    [{p}] '{d}' - {n}"
                for p, d, n in report["burden_free_candidates"]]

    if report["internal_auto"]:
        out.append("Auto-linked internal (exactly one sibling matched) - check these:")
        out += [f"    [{p}] '{d}' -> {t}" for p, d, t in report["internal_auto"]]
    if report["internal_confirmed"]:
        out.append("Internal links you confirmed:")
        out += [f"    [{p}] '{d}' -> {t}" for p, d, t in report["internal_confirmed"]]
    if report["burden_free_created"]:
        out.append("Burden-free children created (empty [EXCHANGES]):")
        out += [f"    {n}" for n in report["burden_free_created"]]
    for kind in ("unit_basis", "geography", "allocation"):
        for who, msg in report[kind]:
            out.append(f"{kind} [{who}]: {msg}")
    if report["missing_documentation"]:
        out.append("Documentation fields still blank (ISO 14040/44 + ILCD; ask the "
                   "user - do not invent):")
        out += [f"    [{p}] {f}" for p, f in report["missing_documentation"]]
    out.append(f"Background rows left for resolve_links: {report['background_rows']}")
    return "\n".join(out)


def to_nested_template(srcs, dst=None, working_database="LCA_working",
                       link_map=None, burden_free=None, strict=True, auto_link=True):
    """Write ONE nested lca-calculator file from several extractions.

    Raises NestedNeedsConfirmation (with `.report`) while any blocking judgement call
    is outstanding, so an ambiguous chain is never quietly written. Pass `strict=False`
    only to inspect a draft.
    """
    procs, report = build_nested(srcs, working_database=working_database,
                                 link_map=link_map, burden_free=burden_free,
                                 auto_link=auto_link)
    if strict and any(report[k] for k in _BLOCKING):
        raise NestedNeedsConfirmation(
            report,
            "Cannot write the nested template yet -- settle these with the user "
            "first:\n" + format_nested_report(report))
    if dst is None:
        base, _ = os.path.splitext(srcs[0] if isinstance(srcs, list) else srcs)
        dst = base + "_nested_calc.csv"
    write_nested_template(procs, dst, working_database, report)
    return dst, report


# --------------------------------------------------------------------------- #
# PDF page counting -- drives the >20-page windowed read strategy
# --------------------------------------------------------------------------- #

def pdf_page_count(path):
    """Best-effort page count of a PDF using only the standard library.

    Reads the raw bytes and (1) prefers the largest '/Count N' on a '/Type /Pages'
    node, else (2) counts '/Type /Page' object markers. Returns int, or None if the
    file can't be parsed -- in which case the skill falls back to reading successive
    20-page windows until Read reports an out-of-range page.
    """
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError:
        return None

    counts = [int(m) for m in re.findall(rb"/Type\s*/Pages\b[^>]*?/Count\s+(\d+)", data)]
    counts += [int(m) for m in re.findall(rb"/Count\s+(\d+)[^>]*?/Type\s*/Pages\b", data)]
    if counts:
        return max(counts)

    pages = re.findall(rb"/Type\s*/Page\b", data)
    # Exclude '/Type /Pages' (the tree nodes) which the above also matched.
    trees = re.findall(rb"/Type\s*/Pages\b", data)
    n = len(pages) - len(trees)
    return n if n > 0 else None


def page_windows(n, size=20):
    """[(1,20),(21,40),...] -- the <=`size`-page ranges to feed Read one at a time."""
    if not n or n < 1:
        return []
    return [(s, min(s + size - 1, n)) for s in range(1, n + 1, size)]


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def _cmd_pageinfo(path):
    n = pdf_page_count(path)
    if n is None:
        print(f"Could not determine page count for {path!r}.")
        print("Fallback: read successive 20-page windows (1-20, 21-40, ...) until "
              "Read reports an out-of-range page.")
        return 0
    windows = page_windows(n)
    print(f"{path}: {n} pages")
    print(f"Read in {len(windows)} window(s) of <=20 pages each:")
    for a, b in windows:
        print(f'  Read(pages="{a}-{b}")')
    if n > 20:
        print("This PDF exceeds 20 pages: one Read call CANNOT cover it. Sweep every "
              "window above and keep a coverage log so no inventory table is missed.")
    return 0


def _cmd_to_template(src, dst=None):
    out = to_new_process_template(src, dst)
    print(f"Wrote lca-calculator template: {out}")
    return 0


def _cmd_to_nested(argv):
    """--to-nested-template <dst.csv> <src.csv>... [options]"""
    dst, srcs, working_db = None, [], "LCA_working"
    burden_free, link_map = [], {}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--working-db":
            working_db = argv[i + 1]; i += 2
        elif a == "--burden-free":                    # --burden-free "desc"
            burden_free.append(argv[i + 1]); i += 2   #   or "Process::desc"
        elif a == "--link":                           # --link "Process::desc=Child"
            spec = argv[i + 1]; i += 2
            lhs, _, child = spec.partition("=")
            proc, _, desc = lhs.partition("::")
            link_map[(proc, desc)] = child
        elif dst is None:
            dst = a; i += 1
        else:
            srcs.append(a); i += 1
    burden_free = [tuple(b.split("::", 1)) if "::" in b else b for b in burden_free]

    if not dst or not srcs:
        print("usage: --to-nested-template <dst.csv> <src.csv>... "
              "[--working-db NAME] [--burden-free DESC] [--link 'Proc::desc=Child']")
        return 2
    try:
        out, report = to_nested_template(srcs, dst, working_database=working_db,
                                         link_map=link_map or None,
                                         burden_free=burden_free or None)
    except NestedNeedsConfirmation as exc:
        print(exc)
        print("\nNothing was written. Resolve the BLOCKERs above with the user, then "
              "re-run with --link / --burden-free.")
        return 3
    print(format_nested_report(report))
    print(f"\nWrote nested lca-calculator template: {out}")
    return 0


def _cmd_selftest_nested():
    """Round-trip the bundled multi-process fixture into the nested calculator file."""
    here = os.path.dirname(os.path.abspath(__file__))
    example = os.path.normpath(os.path.join(
        here, "..", "assets", "lci_extraction_nested_example.csv"))
    tmp = tempfile.TemporaryDirectory(prefix="lci_selftest_")
    dst = os.path.join(tmp.name, "selftest_nested.csv")
    print(f"Nested self-test on: {example}")

    blocks = load_extraction_multi(example)
    assert len(blocks) == 2, f"fixture should hold 2 processes, got {len(blocks)}"
    print(f"  load_extraction_multi: {len(blocks)} processes")

    # 1. Unconfirmed burden-free row must BLOCK, not be quietly guessed at.
    try:
        to_nested_template(example, dst)
    except NestedNeedsConfirmation as exc:
        assert exc.report["burden_free_candidates"], \
            "the unlinked 'demo waste shell' row should surface as a candidate"
        print("  strict mode correctly refused an unconfirmed burden-free row")
    else:
        raise AssertionError("strict mode should have refused to write")

    # 2. With the user's confirmation, it writes.
    out, report = to_nested_template(example, dst,
                                     burden_free=["demo waste shell"])
    assert report["burden_free_created"] == ["demo waste shell"], \
        f"expected a burden-free child, got {report['burden_free_created']}"
    assert ("Demo composite panel production", "demo binder",
            "Demo binder production") in report["internal_auto"], \
        f"parent->child link not made: {report['internal_auto']}"
    assert not report["unit_mismatch_internal"], report["unit_mismatch_internal"]
    assert report["geography"], "prose geography should have been caught"
    print(f"  to_nested_template -> {out}")
    print("  " + format_nested_report(report).replace("\n", "\n  "))

    # 3. The gram/kilogram basis fix.
    procs, _ = build_nested(example, burden_free=["demo waste shell"])
    binder = next(p for p in procs if p["name"] == "Demo binder production")
    assert binder["output_unit"] == "kg", binder["output_unit"]
    assert abs(binder["output_quantity"] - 0.00064) < 1e-12, binder["output_quantity"]
    print(f"  unit basis: 0.64 g -> {binder['output_quantity']} "
          f"{binder['output_unit']} (was 1000x wrong)")

    # 4. Burden-free child carries an EMPTY exchange block.
    shell = next(p for p in procs if p["name"] == "demo waste shell")
    assert shell["rows"] == [], "burden-free child must have no exchange rows"
    assert shell["output_unit"] == "kg" and shell["output_quantity"] == 1.0

    # 5. Children before parents, and every process documented.
    order = [p["name"] for p in procs]
    assert order.index("demo waste shell") < order.index("Demo binder production") \
        < order.index("Demo composite panel production"), order
    print(f"  written children-first: {order}")

    ok = _crosscheck_nested(dst)
    tmp.cleanup()
    print("NESTED SELFTEST PASSED" if ok else "NESTED SELFTEST completed with warnings")
    return 0 if ok else 1


def _crosscheck_nested(dst):
    """Parse the emitted file with the real lca-calculator loader (no Brightway)."""
    calc_scripts = os.path.normpath(os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..", "..", "lca-calculator", "scripts"))
    if not os.path.isdir(calc_scripts):
        print("  (lca-calculator scripts not found; skipped cross-loader parse)")
        return True
    sys.path.insert(0, calc_scripts)
    try:
        # load_inventory_multi is pure Python, but lca_helpers imports Brightway at
        # module scope -- so fall back to a direct read when bw2data is absent.
        try:
            import lca_helpers                     # type: ignore
            processes = lca_helpers.load_inventory_multi(dst)
        except ImportError as exc:
            print(f"  (Brightway not importable here: {exc}; "
                  f"run --selftest-nested in the Brightway environment for the full check)")
            return True
        names = [h["name"] for h, _ in processes]
        assert len(processes) == 3, f"expected 3 processes, got {len(processes)}"
        empty = [h["name"] for h, ex in processes if not ex]
        assert empty == ["demo waste shell"], f"burden-free block not empty: {empty}"
        print(f"  lca-calculator.load_inventory_multi parsed it: {names}")
        return True
    except Exception as exc:  # noqa: BLE001 -- surface any handoff mismatch
        print(f"  WARNING: lca-calculator loader could not parse handoff: {exc}")
        return False


def _cmd_selftest():
    here = os.path.dirname(os.path.abspath(__file__))
    example = os.path.join(here, "..", "assets", "lci_extraction_template.csv")
    example = os.path.normpath(example)
    print(f"Self-test on bundled example: {example}")

    metadata, exchanges = load_extraction(example)
    assert metadata.get("functional_unit"), "FU should be present in the example"
    fg = [e for e in exchanges if e.get("data_type") != _CHARACTERIZED]
    chr_rows = [e for e in exchanges if e.get("data_type") == _CHARACTERIZED]
    assert fg, "example should have foreground rows"
    assert chr_rows, "example should include a characterized row for the cross-check"
    print(f"  load_extraction: {len(exchanges)} rows "
          f"({len(fg)} foreground, {len(chr_rows)} characterized), "
          f"FU={metadata['functional_unit']!r}")

    gaps = gap_check(metadata, exchanges)
    issues = validate(metadata, exchanges)
    print(f"  gap_check: {len(gaps)} note(s) -> {gaps if gaps else 'none'}")
    print(f"  validate:  {len(issues)} issue(s) -> {issues if issues else 'none'}")
    assert not issues, f"the bundled example must validate cleanly; got: {issues}"

    tmp = tempfile.TemporaryDirectory(prefix="lci_selftest_")
    dst = os.path.join(tmp.name, "selftest_calc.csv")
    to_new_process_template(example, dst)
    print(f"  to_new_process_template -> {dst}")

    # Round-trip: the emitted CSV must parse with the lca-calculator's loader.
    calc_scripts = os.path.normpath(os.path.join(
        here, "..", "..", "lca-calculator", "scripts"))
    ok = False
    if os.path.isdir(calc_scripts):
        sys.path.insert(0, calc_scripts)
        try:
            import lca_helpers  # type: ignore
            header, calc_ex = lca_helpers.load_inventory_csv(dst)
            assert header.get("name"), "handoff header missing name"
            assert calc_ex, "handoff produced no exchanges"
            assert all(e["role"] != _CHARACTERIZED for e in calc_ex), \
                "characterized rows must be dropped on handoff"
            print(f"  lca-calculator.load_inventory_csv parsed it: "
                  f"header name={header['name']!r}, {len(calc_ex)} exchanges, "
                  f"output={header.get('output_amount')} {header.get('output_unit')}")
            ok = True
        except Exception as exc:  # noqa: BLE001 -- surface any handoff mismatch
            print(f"  WARNING: lca-calculator loader could not parse handoff: {exc}")
    else:
        # Fall back to our own loader as a structural check.
        h_meta, h_ex = _read_blocks(dst), None
        print("  (lca-calculator scripts not found; skipped cross-loader parse)")
        ok = True

    tmp.cleanup()
    print("SELFTEST PASSED" if ok else "SELFTEST completed with warnings")
    return 0 if ok else 1


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd = argv[0]
    if cmd == "--pageinfo" and len(argv) >= 2:
        return _cmd_pageinfo(argv[1])
    if cmd == "--selftest":
        return _cmd_selftest()
    if cmd == "--selftest-nested":
        return _cmd_selftest_nested()
    if cmd == "--to-template" and len(argv) >= 2:
        return _cmd_to_template(argv[1], argv[2] if len(argv) >= 3 else None)
    if cmd == "--to-nested-template":
        return _cmd_to_nested(argv[1:])
    print(f"Unrecognised arguments: {argv}\n")
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
