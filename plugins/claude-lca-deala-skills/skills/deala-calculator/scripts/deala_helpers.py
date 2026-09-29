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
from typing import Iterable, Sequence

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
            "This helper needs the Brightway 2.5 environment.")


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


def check_environment(verbose: bool = True) -> dict:
    """Assert the version floor that makes DEALA-Cost scoring work at all.

    ``matrix_utils`` < 0.6.3 raises ``AttributeError: 'csc_matrix' object has no
    attribute 'A1'`` at ``array_mapper.py:78`` for *any* method characterised
    against the biosphere — which DEALA-Cost is, and GWP is not.  Fix by
    ``pip install --no-deps "matrix_utils==0.6.3"`` (pinned, so pip cannot jump
    to 3.x and break the bw2calc 2.5 stack).
    """
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
            "crash on `.A1`. Run: pip install --no-deps \"matrix_utils==0.6.3\". "
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

#: LOCKED: land legs <= 800 km go by road, longer legs by rail.
RAIL_THRESHOLD_KM = 800

#: Country-specific DEALA freight rates exist only for these; all else -> GLO.
COUNTRY_RATE_LOCS = {"CN", "DE", "SE"}

MODE_LABELS = {
    "lorry": "transport - transport, freight, lorry >32 metric ton, EURO6, non-hazardous, foreground",
    "train": "transport - transport, freight train, non-hazardous, foreground",
    "sea": "transport - transport, freight, sea, container ship, non-hazardous, foreground",
}


def transport_rates(cost_input_db: str = COST_INPUT_DB, method=COST_METHOD,
                    verbose: bool = True) -> dict:
    """``{(mode, location): USD/tkm}`` from the DEALA freight activities.

    Sanity anchors (GLO): lorry ~0.207, train ~0.097, sea ~0.0032 USD/tkm.
    """
    cfg = {"impact_categories": [method]}
    db = bd.Database(cost_input_db)
    fu, meta = {}, {}
    for mode, label in MODE_LABELS.items():
        for loc in ["GLO", *sorted(COUNTRY_RATE_LOCS)]:
            hit = [a for a in db if a["name"] == label and a["location"] == loc]
            if hit:
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


def build_transport_table(rates: dict, seadistance_csv: str, countries: Sequence[str],
                          iso2_to_iso3: dict) -> pd.DataFrame:
    """Per-country-pair transport cost in **USD/kg**.

    ``iso2_to_iso3`` maps each ISO2 code in ``countries`` to the ISO3 code used
    in the distance CSV. It decides which pairs are built: the CSV is filtered
    to pairs whose both ends are in the map.

    Route model: ``short == 1`` (neighbours) -> road only over ``roaddistance``;
    otherwise three legs, origin capital -> origin port (``capitalport1``), sea
    (``seadistance``), destination port -> destination capital (``capitalport2``).
    Land legs are priced by :data:`RAIL_THRESHOLD_KM`; the first two legs use
    origin-keyed rates, the last leg destination-keyed.  Built per tonne, then
    divided by 1000 to match the per-kg emission table.  Same-country = 0.
    """
    def land_rate(dist_km, iso2):
        mode = "lorry" if dist_km <= RAIL_THRESHOLD_KM else "train"
        return rates[(mode, iso2 if iso2 in COUNTRY_RATE_LOCS else "GLO")]

    def sea_rate(iso2):
        return rates[("sea", iso2 if iso2 in COUNTRY_RATE_LOCS else "GLO")]

    def num(x):
        return 0.0 if pd.isna(x) else float(x)

    ISO3_TO_ISO2 = {v: k for k, v in iso2_to_iso3.items()}
    sea_df = pd.read_csv(seadistance_csv, encoding="utf-8-sig")
    sea_df = sea_df[sea_df["isoA"].isin(ISO3_TO_ISO2) & sea_df["isoB"].isin(ISO3_TO_ISO2)].copy()

    def pair_cost(r):
        o, d = ISO3_TO_ISO2[r["isoA"]], ISO3_TO_ISO2[r["isoB"]]
        if o == d:
            return 0.0
        if int(num(r["short"])) == 1:
            road = num(r["roaddistance"])
            return road * land_rate(road, o)
        cp1, seadist, cp2 = num(r["capitalport1"]), num(r["seadistance"]), num(r["capitalport2"])
        return cp1 * land_rate(cp1, o) + seadist * sea_rate(o) + cp2 * land_rate(cp2, d)

    recs = []
    for _, r in sea_df.iterrows():
        o, d = ISO3_TO_ISO2[r["isoA"]], ISO3_TO_ISO2[r["isoB"]]
        recs.append({"helper": f"{o}x{d}", "from_country": o, "to_country": d,
                     "transport_cost": pair_cost(r) / 1000.0, "same_country": o == d})
    have = {(x["from_country"], x["to_country"]) for x in recs}
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
    """
    have_keys = {"country", "process_base"} <= set(cost_results.columns)
    cr = cost_results.copy() if have_keys else parse_names(cost_results)

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
    df[score_col] = np.where(
        df["same_country"],
        df["scale"] * df["process_cost"],
        df["scale"] * (df["process_cost"] + df["transport_cost"]))
    if verbose:
        print(f"[edges] {len(df)} rows; NaN scale={df['scale'].isna().sum()}, "
              f"NaN {score_col}={df[score_col].isna().sum()}")
    return df
