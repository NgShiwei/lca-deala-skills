"""Reusable Brightway 2.5 helpers for LCA calculation and safe database editing.

Import these, or copy the ones you need into a notebook. They encode the habits
that prevent the common failure modes: duplicate accumulation, editing the wrong
(broken) duplicate, and re-matching exchanges you just added.

Assumes: bw2data >= 4, bw2calc >= 2.5 (MultiLCA), pandas, numpy.
Set the project first:  import bw2data as bd; bd.projects.set_current("<project>")
"""
import csv
import hashlib
import re
from collections import Counter

import bw2data as bd
import bw2calc as bc
import pandas as pd


# --------------------------------------------------------------------------- #
# Database management
# --------------------------------------------------------------------------- #
def working_copy(source_name, working_name, overwrite=False):
    """Duplicate `source_name` into `working_name` so edits never touch the source.

    Editing an imported reference database (ecoinvent, Agri-footprint) in place is
    the one mistake you cannot cheaply undo. Always branch a working copy first.
    """
    if working_name in bd.databases:
        if not overwrite:
            raise ValueError(
                f"'{working_name}' already exists. Pass overwrite=True to replace it "
                f"(this deletes the current working copy)."
            )
        del bd.databases[working_name]
    return bd.Database(source_name).copy(working_name)


# --------------------------------------------------------------------------- #
# Activity / exchange inspection
# --------------------------------------------------------------------------- #
def has_production(act):
    """True if the activity has a production exchange.

    A copied/duplicate activity missing its production exchange will score as if
    its output were 1 unit -- a classic source of wildly wrong LCA results.
    """
    return any(e.get("type") == "production" for e in act.exchanges())


def find_activities(db, name_contains=None, location=None, exclude_prefixes=(),
                    require_production=False):
    """Return activities in `db` matching the filters.

    Prefer this over a bare `[... for act in db if s in act['name']][0]`: that
    pattern can silently pick a broken duplicate or a previously created copy.
    Set `require_production=True` when you need a complete source activity, and
    `exclude_prefixes=('Cutoff', 'DEALA')` to skip your own generated copies.
    """
    out = []
    for act in db:
        name = act["name"]
        if name_contains and name_contains not in name:
            continue
        if location is not None and act.get("location") != location:
            continue
        if any(name.startswith(p) for p in exclude_prefixes):
            continue
        if require_production and not has_production(act):
            continue
        out.append(act)
    return out


def show_exchanges(act, kinds=("production", "technosphere", "biosphere")):
    """Print an activity's exchanges grouped by type -- for quick inspection."""
    print(act["name"], "|", act.get("location"))
    for e in act.exchanges():
        if e.get("type") in kinds:
            print(f"  [{e.get('type'):>12}] {e['amount']:>14.5g} "
                  f"{e.get('unit',''):<14} | {e.input['name']}")


# --------------------------------------------------------------------------- #
# Safe editing
# --------------------------------------------------------------------------- #
def fresh_copy(db, source_activity, new_name):
    """Copy `source_activity` into `db` under `new_name`, replacing any existing
    activity of that exact name first.

    `activity.copy()` creates a NEW object every call, so re-running a build loop
    accumulates duplicates. Deleting same-named copies first makes the loop
    idempotent -- re-running replaces rather than piling up.
    """
    for old in [a for a in db if a["name"] == new_name]:
        old.delete()
    na = source_activity.copy()
    na["name"] = new_name
    na.save()
    return na


def snapshot_exchanges(act):
    """Return a fixed list of the activity's current exchanges.

    Iterate over THIS, not over `act.exchanges()`, when you add exchanges inside
    the loop: a newly added exchange whose name shares a substring with your match
    pattern (e.g. 'transport, freight train') would otherwise be re-matched and
    duplicated.
    """
    return list(act.exchanges())


def add_marketsphere_exchange(act, deala_activity, amount, unit):
    """Attach a DEALA/marketsphere cost exchange to `act` (economic assessment)."""
    # `input` already identifies the edge; no separate name= needed (it'd be
    # overwritten from the input anyway).
    act.new_exchange(input=deala_activity, amount=amount, unit=unit,
                     type="marketsphere").save()


# --------------------------------------------------------------------------- #
# Recovery / cleanup
# --------------------------------------------------------------------------- #
def delete_broken_duplicates(db, name_contains=None, dry_run=True):
    """Delete activities that share a name with a good twin but lack a production
    exchange.

    When a run misbehaves you often end up with duplicate source activities, one
    of which is incomplete. This removes only the broken ones, and only when a
    complete same-named activity still exists. `dry_run=True` reports first --
    review before deleting. Deletion is irreversible, so confirm with the user.
    """
    victims = []
    names = Counter(a["name"] for a in db)
    for name, count in names.items():
        if count <= 1:
            continue
        if name_contains and name_contains not in name:
            continue
        twins = [a for a in db if a["name"] == name]
        if any(has_production(a) for a in twins):
            victims += [a for a in twins if not has_production(a)]
    for a in victims:
        print(("[dry-run] would delete" if dry_run else "deleting"), a["name"])
        if not dry_run:
            a.delete()
    return victims


def delete_by_name_prefix(db, prefix, dry_run=True):
    """Delete every activity whose name starts with `prefix` (e.g. 'Cutoff NP, X',
    'DEALA, '). Use to reset generated activities before a clean re-run."""
    victims = [a for a in db if a["name"].startswith(prefix)]
    for a in victims:
        print(("[dry-run] would delete" if dry_run else "deleting"), a["name"])
        if not dry_run:
            a.delete()
    return victims


# --------------------------------------------------------------------------- #
# LCIA methods
# --------------------------------------------------------------------------- #
def list_methods(version=None, family=None, contains=None):
    """List LCIA method keys, optionally filtered.

    `version` matches m[0] (the biosphere namespace, e.g. 'ecoinvent-3.10');
    `family` is CASE-INSENSITIVE and ALL-WORDS matched on m[1] -- every whitespace-
    separated token must appear somewhere in the family, so 'recipe midpoint (h)'
    finds 'ReCiPe 2016 v1.03, midpoint (H)' even though the words aren't contiguous.
    Family names are fiddly and an exact match silently returns nothing; `contains`
    is a free-text filter over the whole key. To see the exact family strings
    available, use `list_families(version)`.
    """
    fam_tokens = family.lower().split() if family else None
    out = []
    for m in bd.methods:
        if version and m[0] != version:
            continue
        if fam_tokens and (len(m) < 2
                           or not all(t in m[1].lower() for t in fam_tokens)):
            continue
        if contains and contains.lower() not in " ".join(map(str, m)).lower():
            continue
        out.append(m)
    return out


def list_families(version=None):
    """Return the distinct method families (m[1]) present, optionally within a
    namespace. Use this to discover the exact family spelling before filtering."""
    return sorted({m[1] for m in bd.methods if len(m) > 1
                   and (not version or m[0] == version)})


def find_method(version, family, category=None, indicator=None):
    """Resolve exactly one method key, or raise with the near-misses.

    Arguments are in the SAME ORDER as the method key itself, so you can read a key
    off `list_methods()` and pass its parts straight through, positionally:
      * 4-tuple (version, family, category, indicator) -- pass all four:
            find_method("ecoinvent-3.10", "IPCC 2021",
                        "climate change", "global warming potential (GWP100)")
      * 3-tuple (version, family, indicator) -- single-indicator families such as
        Cumulative Energy Demand are stored this way; omit `category` and pass the
        indicator third:  find_method(version, family, indicator)

    The namespace `version` must match the biosphere version your inventory uses,
    or the score will silently come from the wrong characterization set.
    """
    # A 3-tuple key has no category, so a positional 3-arg call lands the indicator
    # in `category`. Treat a lone middle value as the indicator so tuple-order
    # positional calls work for both key shapes.
    if indicator is None and category is not None:
        category, indicator = None, category
    if category is None:
        hits = [m for m in bd.methods if len(m) == 3 and m[0] == version
                and m[1] == family and m[2] == indicator]
        wanted = (version, family, indicator)
    else:
        hits = [m for m in bd.methods if len(m) == 4 and m[0] == version
                and m[1] == family and m[2] == category and m[3] == indicator]
        wanted = (version, family, category, indicator)
    if len(hits) == 1:
        return hits[0]
    near = list_methods(version=version, family=family)
    raise ValueError(
        f"Expected 1 method, found {len(hits)} for {wanted!r}. "
        f"Candidates under {version}/{family}:\n  " + "\n  ".join(map(str, near))
    )


# --------------------------------------------------------------------------- #
# Run
# --------------------------------------------------------------------------- #
def run_multilca(functional_units, method_keys, use_distributions=False):
    """Build matrices, run inventory + impact assessment, return (DataFrame, MultiLCA).

    functional_units: {name: {activity.id: amount}}
    method_keys:      list of method tuples from bd.methods
    Returns a DataFrame indexed by (method, fu_name) with a 'score' column.
    """
    config = {"impact_categories": list(method_keys)}
    data_objs = bd.get_multilca_data_objs(functional_units=functional_units,
                                          method_config=config)
    mlca = bc.MultiLCA(demands=functional_units, method_config=config,
                       data_objs=data_objs, use_distributions=use_distributions)
    mlca.lci()
    mlca.lcia()
    df = pd.DataFrame.from_dict(mlca.scores, orient="index", columns=["score"])
    return df, mlca


# --------------------------------------------------------------------------- #
# Non-square technosphere diagnosis
# --------------------------------------------------------------------------- #
def diagnose_nonsquare(demand):
    """Explain a NonsquareTechnosphere error by comparing the row (product) and
    column (activity) index sets of the assembled matrix.

    `demand` is a mapping usable by bw2calc.LCA, e.g. {activity: 1} or {id: 1}.
    Returns a dict with 'square' plus, when non-square, 'orphan_products'
    (product rows with no producing activity column) and 'orphan_activities'
    (activity columns with no product row), each a list of (name, location, db).

    Reading the result -- there are TWO common causes of the same error:
      * orphan_products present -> a referenced input has no producer in the
        matrix. The usual, easily-missed cause is that the edited database was
        not processed before the calc, so its datapackage was stale: call
        `db.process()` on the edited database and retry. (It can also be a
        genuinely missing producer.)
      * orphan_activities present -> an activity has zero or mismatched
        production exchanges, or is a redundant duplicate; inspect and remove.
    """
    lca = bc.LCA(demand)
    try:
        lca.lci()
        return {"square": True, "orphan_products": [], "orphan_activities": []}
    except Exception:
        acts = set(lca.activity_dict.keys())
        prods = set(lca.product_dict.keys())

        def describe(keys):
            out = []
            for k in keys:
                try:
                    a = bd.get_activity(k)
                    out.append((a["name"], a.get("location"), a["database"]))
                except Exception:
                    out.append((str(k), None, None))
            return out

        return {"square": False,
                "orphan_products": describe(prods - acts),
                "orphan_activities": describe(acts - prods)}


# --------------------------------------------------------------------------- #
# Building a brand-new process from a user-supplied inventory
# --------------------------------------------------------------------------- #
# An inventory is a header dict plus a list of exchange dicts. There may be ANY
# number of exchange rows per role (several materials, several energy carriers,
# several transport legs, several emissions) -- one row per input or output.
#
# header = {
#   "name": str, "reference_product": str, "output_amount": float,
#   "output_unit": str, "location": str, "comment": str (optional),
# }
# exchange = {
#   "role": "material"|"energy"|"transport"|"emission"|"coproduct"|"waste",
#   "description": str, "quantity": float, "unit": str,
#   "link_name": str,        # substring of the background activity / biosphere flow
#   "source_db": str,        # database to search for the link
#   "location": str,         # ISO2/GLO/RoW (technosphere) OR compartment (emission)
#   "factor": float,         # optional; multiplies quantity to match the link's unit
# }
# A process may have MULTIPLE outputs, but exactly one reference product (carried
# in the header). Extra outputs are "coproduct" rows. Multifunctionality is a
# methodological choice, so build_process refuses to guess -- see coproduct_handling.
# NOTE on 'waste': ecoinvent models waste *treatment* as a technosphere link whose
# amount is usually NEGATIVE (the treatment activity "produces" a negative amount of
# the waste). A positive quantity here links the treatment but with the opposite sign
# to ecoinvent's convention -- confirm the sign with the user before building.
_ROLE_TO_TYPE = {"material": "technosphere", "energy": "technosphere",
                 "transport": "technosphere", "waste": "technosphere",
                 "emission": "biosphere", "coproduct": "technosphere"}

# Unit synonyms, so 'kg' and 'kilogram' (etc.) don't read as a mismatch. A genuine
# mismatch (e.g. m3 vs kg) still surfaces so the user can confirm a conversion factor.
_UNIT_ALIASES = {
    "kg": "kilogram", "kilograms": "kilogram",
    "g": "gram", "t": "ton", "tonne": "ton", "metric ton": "ton",
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


def _safe_code(name):
    """Derive a Brightway activity code that is filesystem/DB-safe and collision-free.

    A bare `name.replace(' ', '_')[:60]` collides whenever two process names share
    their first 60 characters, and leaves punctuation/non-ASCII in the code. Slugify
    the name and append a short hash of the FULL name: deterministic (idempotent
    re-runs keep the same code) yet unique across distinct names.
    """
    slug = re.sub(r"[^0-9A-Za-z]+", "_", name).strip("_")[:50] or "process"
    return f"{slug}_{hashlib.md5(name.encode('utf-8')).hexdigest()[:8]}"


# Header keys the template/CSV may use -> the keys build_process reads.
_HEADER_ALIASES = {"process_name": "name", "output_quantity": "output_amount"}
_HEADER_FLOATS = ("output_amount",)


def load_inventory_csv(path):
    """Parse a filled inventory template into `(header, exchanges)` for build_process.

    Pure Python (no Brightway needed). The file has two labelled blocks; `#` comment
    lines and blank lines are ignored:

        [HEADER]
        name,reference_product,output_quantity,output_unit,location,working_database,...
        <one row of values>
        [EXCHANGES]
        role,description,quantity,unit,link_name,source_db,location,factor
        <one row per input/output>

    Header field names are normalised to what build_process expects
    (`process_name`->`name`, `output_quantity`->`output_amount`); `output_amount`,
    `quantity` and `factor` are coerced to float, and a blank `factor` is dropped so
    it defaults to 1.0 downstream. Returns (header: dict, exchanges: list[dict]).
    """
    processes = load_inventory_multi(path)
    if len(processes) != 1:
        raise ValueError(
            f"{path} holds {len(processes)} processes. load_inventory_csv() reads a "
            f"single-process template; use load_inventory_multi() (and build_chain) "
            f"for a nested/multi-tier inventory.")
    return processes[0]


def _header_from_rows(lines, path):
    header_rows = list(csv.DictReader(lines))
    if len(header_rows) != 1:
        raise ValueError(f"{path}: each [HEADER] must have exactly one value row, "
                         f"got {len(header_rows)}.")
    header = {}
    for k, v in header_rows[0].items():
        if k is None:
            continue
        key = _HEADER_ALIASES.get(k.strip(), k.strip())
        val = (v or "").strip()
        if key in _HEADER_FLOATS:
            val = float(val)
        header[key] = val
    return header


def _exchanges_from_rows(lines):
    exchanges = []
    for row in csv.DictReader(lines):
        ex = {k.strip(): (v or "").strip()
              for k, v in row.items() if k is not None}
        ex["quantity"] = float(ex["quantity"])
        if ex.get("factor"):
            ex["factor"] = float(ex["factor"])
        else:
            ex.pop("factor", None)          # blank -> default 1.0 in build_process
        for opt in ("location",):
            if not ex.get(opt):
                ex[opt] = None
        exchanges.append(ex)
    return exchanges


def load_inventory_multi(path):
    """Parse a template holding ONE OR MORE processes -> [(header, exchanges), ...].

    A multi-tier (nested) inventory repeats the two blocks, one pair per process:

        [HEADER]
        name,reference_product,output_quantity,...
        Chitin production,1 kg chitin,1,...
        [EXCHANGES]
        role,description,quantity,unit,link_name,source_db,location,factor
        material,hydrochloric acid,2.56,kg,market for ...,ecoinvent-3.10-cutoff,RoW,
        [HEADER]
        name,reference_product,output_quantity,...
        Chitosan production,1 kg chitosan,1,...
        [EXCHANGES]
        role,description,quantity,unit,link_name,source_db,location,factor
        material,chitin,1.4,kg,Chitin production,LCA_working,,

    Order in the file does not matter -- `build_chain` sorts children before
    parents from the links themselves. An [EXCHANGES] block with only its
    column-name row and no data rows is a **burden-free** process (production
    exchange only, no inputs).

    Returns a list of (header, exchanges) in file order.
    """
    with open(path, newline="", encoding="utf-8-sig") as fh:
        rows = [ln for ln in fh
                if ln.strip() and not ln.lstrip().startswith("#")]

    processes, cur, section = [], None, None
    for ln in rows:
        tag = ln.strip().upper()
        if tag == "[PROCESS]":          # optional visual separator
            continue
        if tag == "[HEADER]":
            if cur is not None:
                processes.append(cur)
            cur, section = {"[HEADER]": [], "[EXCHANGES]": []}, "[HEADER]"
            continue
        if tag == "[EXCHANGES]":
            if cur is None:
                raise ValueError(f"{path}: [EXCHANGES] before any [HEADER].")
            section = "[EXCHANGES]"
            continue
        if cur is None or section is None:
            raise ValueError(f"{path}: expected a [HEADER] marker before any data row.")
        cur[section].append(ln)
    if cur is not None:
        processes.append(cur)

    if not processes:
        raise ValueError(f"{path}: no [HEADER] block found.")

    out = []
    for blk in processes:
        if not blk["[HEADER]"] or not blk["[EXCHANGES]"]:
            raise ValueError(f"{path}: every process needs both a [HEADER] and an "
                             f"[EXCHANGES] block, each with a column-name row "
                             f"(a burden-free process has the column row and no "
                             f"data rows).")
        out.append((_header_from_rows(blk["[HEADER]"], path),
                    _exchanges_from_rows(blk["[EXCHANGES]"])))
    return out


def resolve_links(exchanges):
    """Resolve each exchange's link to a real background activity / biosphere flow.

    Read-only. Returns a dict with five lists so the caller can decide what to ask
    the user about (per the strict-confirmation principle -- never silently pick):
      'resolved'           : [(exchange, node)]              one match in the requested
                                                             geography, unit ok
      'ambiguous'          : [(exchange, [candidate nodes])] >1 match -> ask which
      'missing'            : [exchange]                      0 matches -> ask / fix
      'unit_mismatch'      : [(exchange, node)]              matched but unit != link unit
      'geography_fallback' : [(exchange, node)]              no match in the requested
                                                             country; a GLO/RoW proxy was
                                                             found -> CONFIRM before use
                                                             (a country->global swap can
                                                             move the score materially).
    """
    resolved, ambiguous, missing, unit_mismatch, geography_fallback = [], [], [], [], []
    for ex in exchanges:
        db = bd.Database(ex["source_db"])
        loc = ex.get("location")
        etype = _ROLE_TO_TYPE.get(ex["role"], "technosphere")
        used_geo_fallback = False
        # ALL-WORDS match: every word of link_name must appear in the activity name.
        # Tolerates punctuation/word-order gaps (e.g. 'electricity low voltage' finds
        # 'market for electricity, low voltage'), unlike a contiguous substring.
        toks = ex["link_name"].lower().split()
        def _named(a):
            return all(t in a["name"].lower() for t in toks)
        if etype == "biosphere":
            # match on flow name and (optionally) compartment held in 'location'.
            # Match against the categories tuple elements, not the stringified tuple,
            # so 'air' can't accidentally match a substring of another compartment.
            hits = [a for a in db if _named(a)
                    and (not loc or loc in (a.get("categories") or ()))]
        else:
            hits = [a for a in db if _named(a)
                    and (loc is None or a.get("location") == loc)]
            if not hits and loc not in (None, "GLO", "RoW"):   # geography fallback
                hits = [a for a in db if _named(a)
                        and a.get("location") in ("GLO", "RoW")]
                used_geo_fallback = bool(hits)
        if len(hits) == 0:
            missing.append(ex)
        elif len(hits) > 1:
            ambiguous.append((ex, hits))
        else:
            node = hits[0]
            if (node.get("unit") and not ex.get("factor")
                    and _norm_unit(node["unit"]) != _norm_unit(ex["unit"])):
                unit_mismatch.append((ex, node))
            elif used_geo_fallback:
                # a proxy geography was substituted -- surface it, don't fold it in
                geography_fallback.append((ex, node))
            else:
                resolved.append((ex, node))
    return {"resolved": resolved, "ambiguous": ambiguous,
            "missing": missing, "unit_mismatch": unit_mismatch,
            "geography_fallback": geography_fallback}


def build_process(header, resolved, working_db_name, coproduct_handling=None,
                  process_after=True):
    """Create a new activity in `working_db_name` from a header and RESOLVED
    exchanges, then process the database so it is ready to calculate.

    `resolved` is a list of (exchange, node) pairs (from resolve_links, after any
    ambiguities/mismatches have been settled with the user). The single reference
    product's production exchange is added automatically from the header.

    Multiple outputs: extra outputs are `coproduct` rows. Because handling them is a
    methodological choice, this refuses to proceed if any co-products are present
    unless `coproduct_handling` is given -- ASK THE USER which to use:
      * 'substitution' -> each co-product becomes a NEGATIVE technosphere input of
        the market activity it displaces (avoided burden); keeps the matrix square.
        (The co-product row's link must point at that displaced market activity.)
      * allocation / pre-allocated splitting is not done here -- it needs per-output
        value or mass and usually a different modelling step; handle it explicitly.

    Refuses to write into a database whose name looks like a reference database.
    """
    coproducts = [(ex, node) for ex, node in resolved if ex["role"] == "coproduct"]
    if coproducts and coproduct_handling is None:
        raise ValueError(
            f"This process has {len(coproducts)} co-product output(s). Multifunctionality "
            f"is a methodological choice -- ask the user how to handle it and pass "
            f"coproduct_handling='substitution' (avoided burden) or handle allocation "
            f"explicitly. See references/new-process-template.md."
        )
    # Refuse to write into anything that looks like an imported reference database.
    # Heuristic: it carries a known ecoinvent/biosphere prefix, or names an
    # Agri-footprint import. (A working copy should be named distinctly, e.g.
    # '<db>_working' / 'DEALA ...'.)
    _REF_PREFIXES = ("ecoinvent-", "biosphere")
    if (working_db_name.startswith(_REF_PREFIXES)
            or working_db_name.lower().startswith("agri-footprint")):
        raise ValueError(f"Refusing to build into what looks like a reference "
                         f"database: {working_db_name!r}. Use a working copy.")
    if working_db_name not in bd.databases:
        bd.Database(working_db_name).register()
    wdb = bd.Database(working_db_name)

    # replace any existing activity of the same name (idempotent re-run)
    for old in [a for a in wdb if a["name"] == header["name"]]:
        old.delete()

    act = wdb.new_activity(code=_safe_code(header["name"]),
                           name=header["name"],
                           unit=header["output_unit"],
                           location=header.get("location"),
                           comment=header.get("comment", ""))
    # carry the reference product onto the activity (Brightway's field has a space)
    if header.get("reference_product"):
        act["reference product"] = header["reference_product"]
    act.save()
    # reference production exchange -- MUST exist, or the activity scores as 1 unit
    act.new_exchange(input=act, amount=header["output_amount"],
                     type="production", unit=header["output_unit"]).save()

    for ex, node in resolved:
        amount = ex["quantity"] * ex.get("factor", 1.0)
        if ex["role"] == "coproduct":
            if coproduct_handling == "substitution":
                # avoided burden: negative input of the displaced market activity
                act.new_exchange(input=node, amount=-amount, type="technosphere",
                                 unit=node.get("unit", ex["unit"])).save()
            else:
                raise NotImplementedError(
                    f"coproduct_handling={coproduct_handling!r} is not implemented; "
                    f"only 'substitution' is built in. Allocation needs per-output "
                    f"value/mass and a separate modelling step.")
            continue
        etype = _ROLE_TO_TYPE.get(ex["role"], "technosphere")
        act.new_exchange(input=node, amount=amount, type=etype,
                         unit=node.get("unit", ex["unit"])).save()

    if process_after:
        wdb.process()          # rebuild datapackage so the calc sees a square matrix
    return act


# --------------------------------------------------------------------------- #
# Nested / multi-tier chains: many child processes, then the parent
# --------------------------------------------------------------------------- #
def is_internal_link(ex, working_db_name):
    """True if this exchange points at ANOTHER foreground process in the chain
    (source_db == the working database) rather than at a background activity."""
    return (ex.get("source_db") or "").strip() == working_db_name


def _internal_target(ex, names):
    """Which sibling process does this internal exchange point at?

    Prefers an exact `link_name` match, then an exact `description` match (the
    convention when the extractor left link_name blank because the row is a
    foreground sub-process). Returns the process name, or None if neither matches.
    """
    for candidate in (ex.get("link_name"), ex.get("description")):
        c = (candidate or "").strip()
        if c and c in names:
            return c
    return None


def resolve_chain(processes, working_db_name):
    """DRY RUN for a multi-tier inventory. Builds nothing, decides nothing.

    `processes` is [(header, exchanges), ...] from `load_inventory_multi`.

    Splits every exchange into an internal link (to a sibling process) or a
    background link (resolved with `resolve_links`, same five buckets), then
    works out the build order so children are created before parents.

    Returns a dict:
      'order'          : [process names] in dependency order (children first)
      'cycles'         : [names] involved in a circular dependency (empty = fine)
      'duplicates'     : process names defined more than once
      'per_process'    : {name: {'header', 'internal': [(ex, target_name)],
                                 'dangling': [ex]   -- internal link matching no
                                                       sibling and not already in
                                                       the working database,
                                 'buckets': <resolve_links output>,
                                 'burden_free': bool}}
    Surface every non-empty bucket AND every 'dangling' row to the user before
    building -- principle 3 applies to a chain exactly as it does to one process.
    """
    names = [h["name"] for h, _ in processes]
    duplicates = sorted({n for n in names if names.count(n) > 1})
    nameset = set(names)
    try:
        existing = {a["name"] for a in bd.Database(working_db_name)} \
            if working_db_name in bd.databases else set()
    except Exception:
        existing = set()

    per_process, edges = {}, {n: set() for n in names}
    for header, exchanges in processes:
        name = header["name"]
        internal, dangling, background = [], [], []
        for ex in exchanges:
            if is_internal_link(ex, working_db_name):
                target = _internal_target(ex, nameset)
                if target is not None:
                    internal.append((ex, target))
                    edges[name].add(target)          # name depends on target
                elif _internal_target(ex, existing) is not None:
                    internal.append((ex, _internal_target(ex, existing)))
                else:
                    dangling.append(ex)
            else:
                background.append(ex)
        per_process[name] = {
            "header": header,
            "internal": internal,
            "dangling": dangling,
            "buckets": resolve_links(background),
            "burden_free": not exchanges,
        }

    # Kahn topological sort: emit a process once everything it depends on is out.
    order, remaining = [], dict(edges)
    while remaining:
        ready = sorted(n for n, deps in remaining.items()
                       if not (deps & set(remaining)))
        if not ready:                       # everything left is in a cycle
            break
        for n in ready:
            order.append(n)
            remaining.pop(n)
    cycles = sorted(remaining)

    return {"order": order, "cycles": cycles, "duplicates": duplicates,
            "per_process": per_process}


def build_chain(processes, working_db_name, background_resolved,
                coproduct_handling=None):
    """Build a whole nested inventory: children first, then their parents.

    `background_resolved` is {process_name: [(exchange, node), ...]} covering ONLY
    the background links -- i.e. what `resolve_chain` put in 'buckets', after every
    ambiguity, unit mismatch, geography fallback and missing link has been settled
    WITH THE USER. Internal (foreground-to-foreground) links are wired here
    automatically, because by construction the child already exists by the time its
    parent is built.

    Refuses to start if the chain has cycles, duplicate names, or dangling internal
    links -- those are structural errors, not judgement calls.

    Returns {process_name: Activity} and processes the database once at the end.
    """
    plan = resolve_chain(processes, working_db_name)
    if plan["duplicates"]:
        raise ValueError(f"Process name defined more than once: {plan['duplicates']}")
    if plan["cycles"]:
        raise ValueError(
            f"Circular dependency between processes: {plan['cycles']}. A chain must "
            f"be a tree/DAG -- a child cannot consume its own parent.")
    dangling = {n: p["dangling"] for n, p in plan["per_process"].items()
                if p["dangling"]}
    if dangling:
        detail = "; ".join(
            f"{n}: " + ", ".join(repr(ex.get("link_name") or ex.get("description"))
                                 for ex in exs)
            for n, exs in dangling.items())
        raise ValueError(
            f"Internal link(s) point at no process in this file and no existing "
            f"activity in {working_db_name}: {detail}. Fix the link_name, or add the "
            f"missing child process to the template.")

    by_name = {h["name"]: (h, e) for h, e in processes}
    built = {}
    for name in plan["order"]:
        header, _ = by_name[name]
        pairs = list(background_resolved.get(name, []))
        for ex, target in plan["per_process"][name]["internal"]:
            node = built.get(target) or _working_activity(working_db_name, target)
            pairs.append((ex, node))
        # process_after=False: the datapackage is rebuilt once, after the whole
        # chain is in place, instead of len(processes) times.
        built[name] = build_process(header, pairs, working_db_name,
                                    coproduct_handling=coproduct_handling,
                                    process_after=False)
    bd.Database(working_db_name).process()
    return built


def _working_activity(working_db_name, name):
    hits = [a for a in bd.Database(working_db_name) if a["name"] == name]
    if len(hits) != 1:
        raise ValueError(f"Expected exactly one activity named {name!r} in "
                         f"{working_db_name}, found {len(hits)}.")
    return hits[0]
