"""Reusable helpers for DEALA economic (cost) scoring under Brightway 2.5.

Import-or-copy, the same way ``lca_helpers.py`` works for the environmental side::

    import sys; sys.path.insert(0, r"C:\\Users\\<you>\\.claude\\skills\\deala-calculator\\scripts")
    import deala_helpers as dh

Everything here assumes the **native technosphere** DEALA-Cost method:
a process links each cost input as ``type='technosphere'`` to an activity in the
DEALA input database, and ``bc.MultiLCA`` under
``('DEALA-Cost (BEIC 1)', 'total cost', 'TC')`` traverses that link and sums the
input activity's price flow.  See ``references/deala-cost-method.md`` for why
``marketsphere`` silently scores 0.

Hard requirements (see the skill's reference docs):
  * ``matrix_utils >= 0.6.3``  — earlier versions crash on ``.A1`` under scipy>=1.13
  * ``bd.databases.clean()``   — after any injection, before scoring
  * one Python process per Brightway project (SQLite lock)
  * ``PYTHONIOENCODING=utf-8`` on Windows
"""

from __future__ import annotations

import re
from typing import Callable, Iterable, Sequence

import numpy as np
import pandas as pd


class _NeedsBrightway:
    """Stand-in for an absent Brightway package.

    The transport and edge-table helpers are plain pandas and run without
    Brightway (the offline tests and the toy example use them that way). Any
    scoring helper touches ``bd``/``bc`` and gets this error instead.
    """

    def __init__(self, name: str):
        self._name = name

    def __getattr__(self, attr):
        raise ImportError(
            f"{self._name} is not installed in {__import__('sys').executable}. "
            "This helper needs the Brightway 2.5 environment: see SETUP.md.")


try:
    import bw2data as bd
    import bw2calc as bc
except ImportError:
    bd, bc = _NeedsBrightway("bw2data"), _NeedsBrightway("bw2calc")

# --------------------------------------------------------------------------
# constants
# --------------------------------------------------------------------------

#: The DEALA total-cost method key.
COST_METHOD = ("DEALA-Cost (BEIC 1)", "total cost", "TC")

#: Database holding the priced DEALA input activities (electricity, gas,
#: labour, transport, solvent, water). Cost links point *into* this DB.
COST_INPUT_DB = "DEALA_activities_remind_SSP2-NPi"

#: Name-parsing regexes — identical to the environmental notebook's, so cost and
#: emission tables merge on the same ``(process_base, country)`` keys.
COUNTRY_RE = r"\{([A-Z]{2})\}"
_BASE_EXTRACT = r"Cutoff NP,\s*(.*)"
_BASE_STRIP = r",?\s*\{[A-Z]{2}\}.*$"


def check_environment(verbose: bool = True, require_deala: bool = True) -> dict:
    """Run the shared environment check and refuse to continue if it fails.

    The check lives in ``lca-calculator/scripts/check_environment.py`` so every
    Brightway skill runs the same one: interpreter, the Brightway 2.5 pins,
    ``matrix_utils >= 0.6.3`` (below it DEALA-Cost ``.lci()`` crashes on
    ``.A1`` at ``array_mapper.py:78``), ``ecoinvent_interface >= 3.1``, and an
    unmodified deala 1.2.1. Each failure comes with the command that fixes it.

    If this skill was copied without its sibling, only the ``matrix_utils``
    floor is checked. Returns the installed versions.
    """
    import sys
    from pathlib import Path

    shared = Path(__file__).resolve().parents[2] / "lca-calculator" / "scripts"
    if (shared / "check_environment.py").is_file():
        sys.path.insert(0, str(shared))
        import check_environment as ce
        problems = ce.check(require_deala=require_deala, verbose=verbose)
        if problems:
            raise RuntimeError("environment not ready:\n" + "\n".join(
                f"  - {what}\n    fix: {fix}" for what, fix in problems))
    import matrix_utils
    import scipy

    info = {
        "matrix_utils": matrix_utils.__version__,
        "bw2calc": bc.__version__,
        "bw2data": bd.__version__,
        "scipy": scipy.__version__,
        "numpy": np.__version__,
    }
    parts = tuple(int(x) for x in info["matrix_utils"].split(".")[:3])
    if parts < (0, 6, 3):
        raise RuntimeError(
            f"matrix_utils {info['matrix_utils']} < 0.6.3 — DEALA-Cost .lci() will "
            "crash on `.A1`. Run: python -m pip install --no-deps \"matrix_utils==0.6.3\". "
            "Do NOT downgrade scipy; GWP scoring is fine as-is."
        )
    if verbose:
        print("[env] " + ", ".join(f"{k} {v}" for k, v in info.items()))
    return info


def clean(verbose: bool = True) -> None:
    """``bd.databases.clean()`` — mandatory after any activity/exchange edit.

    Prefer this over a named ``db.process()``: it processes *every* database
    still flagged dirty, so an edit to the DEALA input DB (e.g. a GLO price
    proxy) is caught too, and it refreshes ``depends`` so the modern
    ``get_multilca_data_objs`` path does not hit ``NonsquareTechnosphere``.
    Writes datapackages to ``processed/``, not the multi-GB SQLite file.
    """
    bd.databases.clean()
    if verbose:
        print("[clean] all dirty databases processed; datapackages + depends refreshed")


# --------------------------------------------------------------------------
# parsing
# --------------------------------------------------------------------------

def parse_names(df: pd.DataFrame, name_col: str = "process_name") -> pd.DataFrame:
    """Add ``country`` and ``process_base`` columns parsed from activity names.

    Uses the same regexes as the environmental pipeline, which is what lets the
    cost and emission edge tables merge on ``(process_base, country)``.
    """
    out = df.copy()
    out["country"] = out[name_col].str.extract(COUNTRY_RE)
    out["process_base"] = (
        out[name_col].str.extract(_BASE_EXTRACT, expand=False)
        .str.replace(_BASE_STRIP, "", regex=True).str.strip()
    )
    return out


# --------------------------------------------------------------------------
# native scoring
# --------------------------------------------------------------------------

def find_cutoff_activities(db_name: str, prefix: str = "DEALA", marker: str = "Cutoff NP") -> list:
    """All DEALA-linked cut-off activities in a modular database."""
    db = bd.Database(db_name)
    return [a for a in db if a["name"].startswith(prefix) and marker in a["name"]]


def score_native(activities: Sequence, method=COST_METHOD, verbose: bool = True) -> pd.DataFrame:
    """Native DEALA-Cost score for each activity, FU = ``{act.id: 1}``.

    Returns a DataFrame ``[process_name, process_cost]`` in USD per reference
    unit (per kg here).  Scaling factors and transport are applied afterwards,
    in the edge table — exactly as the environmental pipeline does with GWP.
    """
    cfg = {"impact_categories": [method]}
    fu = {str(a.id): {a.id: 1} for a in activities}
    id2name = {a.id: a["name"] for a in activities}

    data_objs = bd.get_multilca_data_objs(functional_units=fu, method_config=cfg)
    mlca = bc.MultiLCA(demands=fu, method_config=cfg, data_objs=data_objs, use_distributions=False)
    mlca.lci()
    mlca.lcia()

    rows = []
    for score_key, value in mlca.scores.items():
        fk = score_key[1] if isinstance(score_key, tuple) else score_key
        rows.append((id2name[int(fk)], float(value)))
    df = pd.DataFrame(rows, columns=["process_name", "process_cost"])
    if verbose:
        print(f"[score] {len(df)} activities; {df['process_cost'].min():.6f} .. "
              f"{df['process_cost'].max():.6f} USD/kg; "
              f"positive={(df['process_cost'] > 0).sum()}/{len(df)}")
    return df


def price_inputs(keys: Iterable[tuple], method=COST_METHOD) -> dict:
    """Unit price of each DEALA input activity, keyed by ``(db, code)``.

    Each DEALA input activity carries ``production: 1`` plus a ``biosphere``
    exchange to a marketsphere flow equal to its price, so scoring it alone
    returns that price (USD per kWh / MJ / kg / tkm / h).  This is the engine
    behind both the read-only cross-check and the manual verification.
    """
    cfg = {"impact_categories": [method]}
    acts = {k: bd.get_activity(k) for k in keys}
    id2key = {a.id: k for k, a in acts.items()}
    fu = {str(a.id): {a.id: 1} for a in acts.values()}

    data_objs = bd.get_multilca_data_objs(functional_units=fu, method_config=cfg)
    mlca = bc.MultiLCA(demands=fu, method_config=cfg, data_objs=data_objs, use_distributions=False)
    mlca.lci()
    mlca.lcia()

    prices = {}
    for score_key, value in mlca.scores.items():
        fk = score_key[1] if isinstance(score_key, tuple) else score_key
        prices[id2key[int(fk)]] = float(value)
    return prices


# --------------------------------------------------------------------------
# manual verification — the trust-building step
# --------------------------------------------------------------------------

def read_cost_links(activity, cost_input_db: str = COST_INPUT_DB):
    """``(production_amount, [(exchange_amount, input_key), ...])`` for one activity.

    Cost links are identified by their **input database**, not by exchange
    ``type``, so this stays correct even if a database is left in a mixed
    marketsphere/technosphere state.  Reads ``e["input"]`` rather than
    ``e.input.id`` — the latter fires a SQLite query per exchange and is slow.
    """
    production, links = 1.0, []
    for e in activity.exchanges():
        if e.get("type") == "production":
            production = e["amount"]
            continue
        key = e["input"]
        if key[0] == cost_input_db:
            links.append((e["amount"], key))
    return production, links


def manual_cost(activity, method=COST_METHOD, cost_input_db: str = COST_INPUT_DB):
    """Hand-compute ``Σ(input_amount × unit_price) / production`` for one activity.

    Returns ``(cost, breakdown_df)``.  The DataFrame has one row per cost input
    with its amount, unit, unit price and contribution — this is what you show
    the user when proving the native score is real.
    """
    production, links = read_cost_links(activity, cost_input_db)
    prices = price_inputs({k for _, k in links}, method=method)

    rows = []
    for amount, key in links:
        leaf = bd.get_activity(key)
        unit_price = prices.get(key, 0.0)
        rows.append({
            "input": leaf["name"],
            "location": leaf["location"],
            "amount": amount,
            "unit": leaf["unit"],
            "unit_price_USD": unit_price,
            "contribution_USD": amount * unit_price,
        })
    breakdown = pd.DataFrame(rows)
    total = float(breakdown["contribution_USD"].sum()) if len(breakdown) else 0.0
    cost = total / production if production else 0.0
    breakdown.attrs["production"] = production
    breakdown.attrs["gross_USD"] = total
    return cost, breakdown


def verify(activity, method=COST_METHOD, cost_input_db: str = COST_INPUT_DB,
           tol: float = 1e-6, verbose: bool = True) -> dict:
    """Manual sum vs. native ``bc.MultiLCA`` score for one activity.

    Returns ``{'manual', 'native', 'ratio', 'abs_diff', 'passed', 'breakdown'}``.
    A ratio of 1.000000 is the evidence that the native method is doing what the
    hand calculation says it is.
    """
    manual, breakdown = manual_cost(activity, method=method, cost_input_db=cost_input_db)
    native = float(score_native([activity], method=method, verbose=False)["process_cost"].iloc[0])
    ratio = native / manual if manual else float("nan")
    result = {
        "activity": activity["name"],
        "manual": manual,
        "native": native,
        "ratio": ratio,
        "abs_diff": abs(native - manual),
        "passed": abs(native - manual) <= tol * max(1.0, abs(native)),
        "breakdown": breakdown,
    }
    if verbose:
        print(format_verification(result))
    return result


def format_verification(result: dict) -> str:
    """Render :func:`verify` output as the step-by-step worked example."""
    b = result["breakdown"]
    lines = [f"Manual verification — {result['activity']}", "=" * 72]
    lines.append("Step 1. Cost inputs linked into the DEALA input database:")
    for _, r in b.iterrows():
        lines.append(f"    {r['input']} [{r['location']}]")
        lines.append(f"        {r['amount']:.6g} {r['unit']} x {r['unit_price_USD']:.6f} USD/{r['unit']}"
                     f" = {r['contribution_USD']:.6f} USD")
    lines.append("")
    lines.append("Step 2. Unit prices above are each input activity's own DEALA-Cost score")
    lines.append("        (production:1 + a marketsphere price flow), scored alone.")
    lines.append("")
    lines.append(f"Step 3. Sum of contributions   = {b.attrs['gross_USD']:.6f} USD")
    lines.append(f"        Production amount      = {b.attrs['production']:.6g}")
    lines.append(f"        Manual cost            = {b.attrs['gross_USD']:.6f} / {b.attrs['production']:.6g}"
                 f" = {result['manual']:.6f} USD/kg")
    lines.append("")
    lines.append(f"Step 4. Native bc.MultiLCA score = {result['native']:.6f} USD/kg")
    lines.append(f"        ratio native/manual      = {result['ratio']:.6f}")
    lines.append(f"        abs diff                 = {result['abs_diff']:.3e}")
    lines.append("")
    lines.append("PASS — native scoring reproduces the hand calculation."
                 if result["passed"] else
                 "FAIL — native and manual disagree; do not trust the scores.")
    return "\n".join(lines)


def cross_check_all(activities: Sequence, method=COST_METHOD,
                    cost_input_db: str = COST_INPUT_DB, verbose: bool = True) -> pd.DataFrame:
    """Read-only direct-sum cost for many activities, vs. native scores.

    Prices the distinct input activities *once* (typically far fewer than the
    activities themselves), then sums per activity — cheap enough to run over the whole set
    as a regression gate.  Returns
    ``[process_name, manual, native, ratio, abs_diff]``.
    """
    per_act, leaf_keys = {}, set()
    for a in activities:
        production, links = read_cost_links(a, cost_input_db)
        per_act[a["name"]] = (production, links)
        leaf_keys.update(k for _, k in links)
    prices = price_inputs(leaf_keys, method=method)

    manual = {
        name: (sum(amt * prices.get(k, 0.0) for amt, k in links) / prod if prod else 0.0)
        for name, (prod, links) in per_act.items()
    }
    native = score_native(activities, method=method, verbose=False).set_index("process_name")["process_cost"]

    df = pd.DataFrame({"manual": pd.Series(manual)}).join(native.rename("native"))
    df["ratio"] = df["native"] / df["manual"]
    df["abs_diff"] = (df["native"] - df["manual"]).abs()
    df = df.reset_index().rename(columns={"index": "process_name"})
    if verbose:
        print(f"[cross-check] {len(df)} activities; max abs diff = {df['abs_diff'].max():.3e}; "
              f"ratio range {df['ratio'].min():.6f} .. {df['ratio'].max():.6f}")
    return df


# --------------------------------------------------------------------------
# transport + edge table
# --------------------------------------------------------------------------

#: Land legs <= 800 km go by road, longer legs by rail. A modelling choice:
#: confirm it with the user for a new study.
RAIL_THRESHOLD_KM = 800

MODE_LABELS = {
    "lorry": "transport - transport, freight, lorry >32 metric ton, EURO6, non-hazardous, foreground",
    "train": "transport - transport, freight train, non-hazardous, foreground",
    "sea": "transport - transport, freight, sea, container ship, non-hazardous, foreground",
}


def pick_deala(db, label: str, country: str):
    """The DEALA input activity named ``label`` in ``country``, else its GLO one.

    Matches name AND location EXACTLY and raises unless the match is unique.
    Never a substring test and never ``[0]``: a substring match on a label can
    hit a longer label that shares its prefix (the electricity bands do), and
    a database you have written into yourself (a GLO proxy, say) can hold two
    activities that a lax selector would silently choose between.
    """
    for loc in (country, "GLO"):
        hits = [a for a in db if a["name"] == label and a["location"] == loc]
        if len(hits) > 1:
            raise ValueError(f'{len(hits)} DEALA activities named "{label}" at {loc}; '
                             "expected exactly one")
        if hits:
            return hits[0]
    raise ValueError(f'No DEALA activity found for "{label}" ({country} or GLO)')


def transport_rates(cost_input_db: str = COST_INPUT_DB, method=COST_METHOD,
                    verbose: bool = True) -> dict:
    """``{(mode, location): USD/tkm}`` from the DEALA freight activities.

    Scores every location DEALA carries for each of :data:`MODE_LABELS`, so
    :func:`build_transport_table` uses a country's own rate wherever one exists
    and GLO everywhere else. Nothing about which countries have rates is
    hard-coded here.

    Sanity check (GLO): sea should be far cheaper per tonne-km than rail, and
    rail cheaper than road. If not, something is mis-linked.
    """
    cfg = {"impact_categories": [method]}
    db = bd.Database(cost_input_db)
    fu, meta = {}, {}
    for mode, label in MODE_LABELS.items():
        by_loc = {}
        for a in db:
            if a["name"] == label:
                by_loc.setdefault(a["location"], []).append(a)
        if "GLO" not in by_loc:
            raise ValueError(f'no GLO activity named "{label}" in {cost_input_db}')
        for loc, hit in sorted(by_loc.items()):
            if len(hit) > 1:
                raise ValueError(f'{len(hit)} activities named "{label}" at {loc}; '
                                 "expected at most one")
            k = f"{mode}|{loc}"
            fu[k] = {hit[0].id: 1}
            meta[k] = (mode, loc)
    data_objs = bd.get_multilca_data_objs(functional_units=fu, method_config=cfg)
    mlca = bc.MultiLCA(demands=fu, method_config=cfg, data_objs=data_objs, use_distributions=False)
    mlca.lci()
    mlca.lcia()
    rates = {}
    for score_key, value in mlca.scores.items():
        fk = score_key[1] if isinstance(score_key, tuple) else score_key
        rates[meta[fk]] = float(value)
    if verbose:
        print("[transport] USD/tkm:", {f"{m}|{l}": round(r, 5) for (m, l), r in sorted(rates.items())})
    return rates


def iso2_to_iso3_map(countries: Sequence[str]) -> dict:
    """``{ISO2: ISO3}`` for ``countries``, via ``country_converter``.

    Raises on any code it cannot convert, rather than dropping it: a country
    missing from the map is a country whose transport pairs are never built.
    """
    import country_converter as coco

    out, bad = {}, []
    for c in countries:
        # not_found=None would echo the input back; a sentinel cannot be mistaken
        iso3 = coco.convert(c, src="ISO2", to="ISO3", not_found="<not found>")
        if not isinstance(iso3, str) or len(iso3) != 3 or not iso3.isalpha():
            bad.append(c)
        else:
            out[c] = iso3
    if bad:
        raise ValueError(f"country_converter cannot map {bad} to ISO3; pass iso2_to_iso3 explicitly")
    return out


def build_transport_table(rates: dict, seadistance_csv, countries: Sequence[str],
                          iso2_to_iso3: dict | None = None) -> pd.DataFrame:
    """Per-country-pair transport cost in **USD/kg**, for every pair of ``countries``.

    ``iso2_to_iso3`` maps each ISO2 code to the ISO3 code the distance CSV uses.
    Omit it to derive it with ``country_converter``. Every country must be in
    the map and every cross-country pair in the CSV, or this raises naming the
    gap: a missing pair would otherwise surface later as a missing edge.

    Route model: ``short == 1`` (neighbours) -> road only over ``roaddistance``;
    otherwise three legs, origin capital -> origin port (``capitalport1``), sea
    (``seadistance``), destination port -> destination capital (``capitalport2``).
    Land legs are priced by :data:`RAIL_THRESHOLD_KM`; the first two legs use
    the origin's rate, the last leg the destination's, each falling back to GLO
    when ``rates`` has no ``(mode, country)`` entry. Built per tonne, then
    divided by 1000 to match the per-kg emission table. Same-country = 0.
    """
    countries = list(countries)
    if iso2_to_iso3 is None:
        iso2_to_iso3 = iso2_to_iso3_map(countries)
    unmapped = [c for c in countries if c not in iso2_to_iso3]
    if unmapped:
        raise ValueError(f"no ISO3 code for {unmapped} in iso2_to_iso3")
    iso3_to_iso2 = {iso2_to_iso3[c]: c for c in countries}

    def rate(mode, iso2):
        return rates[(mode, iso2)] if (mode, iso2) in rates else rates[(mode, "GLO")]

    def land_rate(dist_km, iso2):
        return rate("lorry" if dist_km <= RAIL_THRESHOLD_KM else "train", iso2)

    def num(x):
        return 0.0 if pd.isna(x) else float(x)

    sea_df = pd.read_csv(seadistance_csv, encoding="utf-8-sig")
    sea_df = sea_df[sea_df["isoA"].isin(iso3_to_iso2) & sea_df["isoB"].isin(iso3_to_iso2)].copy()

    def pair_cost(r):
        o, d = iso3_to_iso2[r["isoA"]], iso3_to_iso2[r["isoB"]]
        if o == d:
            return 0.0
        if int(num(r["short"])) == 1:
            road = num(r["roaddistance"])
            return road * land_rate(road, o)
        cp1, seadist, cp2 = num(r["capitalport1"]), num(r["seadistance"]), num(r["capitalport2"])
        return cp1 * land_rate(cp1, o) + seadist * rate("sea", o) + cp2 * land_rate(cp2, d)

    recs = []
    for _, r in sea_df.iterrows():
        o, d = iso3_to_iso2[r["isoA"]], iso3_to_iso2[r["isoB"]]
        recs.append({"helper": f"{o}x{d}", "from_country": o, "to_country": d,
                     "transport_cost": pair_cost(r) / 1000.0, "same_country": o == d})
    have = {(x["from_country"], x["to_country"]) for x in recs}
    missing = [f"{o}->{d}" for o in countries for d in countries if o != d and (o, d) not in have]
    if missing:
        raise ValueError(f"{len(missing)} country pairs have no row in the distance CSV: "
                         f"{missing[:10]}{' ...' if len(missing) > 10 else ''}")
    for c in countries:
        if (c, c) not in have:
            recs.append({"helper": f"{c}x{c}", "from_country": c, "to_country": c,
                         "transport_cost": 0.0, "same_country": True})
    return pd.DataFrame(recs)


def parse_scale_list(x):
    """Parse the bracketed scaling-factor string from the scaling-factor CSV."""
    if pd.isna(x):
        return []
    x = str(x).strip().strip("[]")
    return [float(v) for v in x.split(",") if v.strip()]


def build_edge_table(cost_results: pd.DataFrame, transport: pd.DataFrame,
                     scaling_csv, process_order: Sequence[str],
                     countries: Sequence[str], score_col: str = "calculated_cost",
                     countries_for_step: Callable[[int], Iterable[str]] | None = None,
                     verbose: bool = True) -> pd.DataFrame:
    """Edge-weight table for ``supply-chain-optimizer``.

    ``weight = scale × process_cost`` within a country, and
    ``scale × (process_cost + transport_cost)`` across countries — the same
    formula the environmental side applies to GWP, so the two tables are
    directly comparable and mergeable.

    ``cost_results`` needs ``process_name`` and ``process_cost``; ``country``
    and ``process_base`` are parsed from the name unless already present.
    ``scaling_csv`` is a path or a DataFrame of ``(country, bracketed list)``.
    ``process_order`` is the study's real steps, in order: the scaling list is
    assigned to it by position.

    ``countries_for_step(step)`` (optional) returns the countries able to
    perform the 1-based ``step``; it is called for steps ``1..N+1``, where
    ``N+1`` is the pass-through layer. With it, a row for step ``i`` is kept
    only if its destination can perform step ``i+1``. An edge into a country
    that cannot take the next step is a dead end, not a route: the graph would
    prune it anyway, but a table that carries such rows makes any row count
    meaningless.

    Raises, naming the countries, if any row has no scaling factor or no cost.
    Such a row would pass a row-count check and then be dropped by the graph
    builder, which skips NaN weights: the country would vanish from the graph
    instead of failing.
    """
    have_keys = {"country", "process_base"} <= set(cost_results.columns)
    cr = cost_results.copy() if have_keys else parse_names(cost_results)

    outside = sorted(set(cr["country"]) - set(countries))
    if outside:
        raise ValueError(f"cost rows for countries not in `countries`: {outside}")

    scal = scaling_csv.copy() if isinstance(scaling_csv, pd.DataFrame) else pd.read_csv(scaling_csv)
    scal.columns = ["country", "scaling_factor_raw"]
    scal["scale_list"] = scal["scaling_factor_raw"].apply(parse_scale_list)
    scal = scal.explode("scale_list", ignore_index=True)
    scal["process_idx"] = scal.groupby("country").cumcount()
    scal["process_base"] = scal["process_idx"].map(
        lambda i: process_order[i] if i < len(process_order) else None)
    scal["scale"] = scal["scale_list"].astype(float)
    scal = scal[["country", "process_base", "scale"]]

    df = cr.merge(scal, on=["country", "process_base"], how="left")
    df = df.merge(transport[["helper", "from_country", "to_country", "transport_cost", "same_country"]],
                  left_on="country", right_on="from_country", how="left")
    df = df.loc[df["to_country"].isin(countries)].copy()

    if countries_for_step is not None:
        next_ok = {p: set(countries_for_step(i + 1))
                   for i, p in enumerate(process_order, start=1)}
        unknown = sorted(set(df["process_base"]) - set(next_ok))
        if unknown:
            raise ValueError(f"process_base values not in process_order: {unknown}")
        df = df.loc[[t in next_ok[p] for p, t in zip(df["process_base"], df["to_country"])]].copy()

    df[score_col] = np.where(
        df["same_country"],
        df["scale"] * df["process_cost"],
        df["scale"] * (df["process_cost"] + df["transport_cost"]))

    nan_scale = df["scale"].isna()
    nan_score = df[score_col].isna()
    if (nan_scale | nan_score).any():
        bad = df.loc[nan_scale | nan_score]
        raise ValueError(
            f"{int(nan_scale.sum())} rows have no scaling factor and "
            f"{int(nan_score.sum())} have no {score_col}, for countries "
            f"{sorted(set(bad['country']))} at steps {sorted(set(bad['process_base'].astype(str)))}. "
            "The graph would drop these edges silently. A missing scale is usually "
            "a (country, process_base) name mismatch, not missing data.")
    if verbose:
        print(f"[edges] {len(df)} rows; no NaN in scale or {score_col}")
    return df
