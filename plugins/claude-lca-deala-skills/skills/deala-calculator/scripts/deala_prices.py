"""deala's price inputs: a private copy of its data files, electricity bands,
and the cost year.

Three things a study needs before deala can price anything, each of which has
gone wrong silently before:

1. **Its own copy of deala's data files.** To add a price deala does not ship,
   never edit the files inside ``site-packages``: results would then depend on
   a hand-edited install no other machine has. :func:`mirror_deala_files`
   copies deala's ``files/`` tree into the project, :func:`add_price_rows`
   patches the copy, and deala is pointed at it through
   ``repository_main_path``.
2. **The right electricity band.** Eurostat prices industrial electricity by
   annual consumption band, and a small plant pays more per kWh than a large
   one. :func:`pick_electricity` resolves the band from the plant's own annual
   use and records how it resolved.
3. **An explicit cost year.** :func:`import_price_databases` has no default for
   it: the year every price is projected to is the user's choice.

Only :func:`import_price_databases` and :func:`electricity_per_kg` need
Brightway; the rest runs anywhere.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Iterable, Sequence

MIRROR_MARKER = ".deala_mirror"

#: Fields every row of deala's material table carries. A row missing one is
#: rejected before it is written, rather than failing inside deala later.
MATERIAL_FIELDS = ("Code", "Costs per unit [USD/unit]", "REMIND Region", "Sector",
                   "Type", "Identifier", "ISO-3166-1 ALPHA-2", "Base Year", "Years")
ELASTICITY_KEY = ("Sector", "Type", "ISO-3166-1 ALPHA-2")


# --------------------------------------------------------------------------
# 1. a private copy of deala's data files
# --------------------------------------------------------------------------

def deala_package_files() -> Path:
    """The ``files/`` directory inside the installed deala package."""
    import deala
    return Path(deala.__file__).resolve().parent / "files"


def mirror_deala_files(dest, source=None) -> Path:
    """Copy deala's ``files/`` tree to ``dest/files`` and return ``dest``.

    Pass the RETURNED path to deala as ``repository_main_path``: deala joins it
    with ``files`` itself, so it must be the PARENT of ``files/``. Handing deala
    ``dest/files`` instead fails much later, inside deala.

    Rebuilt from scratch on every call, so a patch from an earlier run can
    never survive into this one. ``dest`` must be empty, absent, or a mirror
    this function made before (it leaves a marker file); anything else is
    refused rather than deleted. ``source`` defaults to the installed
    package's ``files/``, which is only ever read.
    """
    dest = Path(dest).resolve()
    source = Path(source).resolve() if source is not None else deala_package_files()
    if dest == source.parent or source in dest.parents or dest in source.parents:
        raise ValueError(f"refusing to mirror into or around the source itself: {dest}")
    if "site-packages" in dest.parts:
        raise ValueError(f"refusing to write inside site-packages: {dest}")
    if dest.exists():
        if not (dest / MIRROR_MARKER).is_file() and any(dest.iterdir()):
            raise ValueError(f"{dest} exists, is not empty and is not a deala mirror; "
                             "choose another folder")
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    shutil.copytree(source, dest / "files")
    (dest / MIRROR_MARKER).write_text(f"copied from {source}\n", encoding="utf-8")
    # deala reads the folder as both "files" and "Files"; that resolves only
    # on a case-insensitive filesystem, so keep the lowercase name.
    for sub in ("GDP", "DEALA_activities"):
        if not (dest / "files" / sub).is_dir():
            raise ValueError(f"mirror has no files/{sub}: is {source} deala's files/ folder?")
    return dest


def _load(path: Path) -> list:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list) or not data:
        raise ValueError(f"{path}: expected a non-empty JSON list")
    return data


def _write_ascii(path: Path, rows: list) -> None:
    # ensure_ascii=True is load-bearing: deala opens its JSON with no
    # encoding= argument, so it decodes with the machine's locale. Escaped
    # ASCII reads the same under every locale; UTF-8 does not.
    path.write_text(json.dumps(rows, indent=4, ensure_ascii=True), encoding="utf-8")
    path.read_bytes().decode("ascii")


def add_price_rows(mirror, rows: Sequence[dict],
                   table: str = "DEALA_activities/material_beer.json",
                   elasticity_rows: Sequence[dict] | None = None) -> dict:
    """Add price rows to a MIRROR's table, replacing earlier copies of them.

    ``mirror`` is the path :func:`mirror_deala_files` returned. Every row needs
    the fields in :data:`MATERIAL_FIELDS`, copied in shape from the table's own
    rows. Any existing row with the same ``Code`` is removed first, so a
    re-run replaces rather than duplicates.

    ``elasticity_rows`` go into ``GDP/elasticity.json``, replacing any row with
    the same ``(Sector, Type, ISO)``. Give every new material one: deala matches
    an elasticity on those three fields and never resets the value between
    datasets, so a row that matches nothing silently inherits the exponent of
    whichever dataset matched last. For a price with its own Base Year equal to
    the cost year the exponent has no effect; for any other it does.

    Refuses to write anywhere but a mirror. Returns counts.
    """
    mirror = Path(mirror)
    if not (mirror / MIRROR_MARKER).is_file():
        raise ValueError(f"{mirror} is not a mirror made by mirror_deala_files; "
                         "never patch deala's installed files")
    path = mirror / "files" / table
    current = _load(path)
    missing = [f for f in MATERIAL_FIELDS if f not in current[0]]
    if missing:
        raise ValueError(f"{table} has changed shape upstream: its rows lack {missing}")
    for r in rows:
        gaps = [f for f in MATERIAL_FIELDS if f not in r]
        if gaps:
            raise ValueError(f"row {r.get('Code', '?')!r} lacks {gaps}")
    codes = [r["Code"] for r in rows]
    if len(set(codes)) != len(codes):
        raise ValueError("duplicate Code among the new rows")
    kept = [m for m in current if m.get("Code") not in set(codes)]
    _write_ascii(path, kept + list(rows))
    out = {"replaced": len(current) - len(kept), "added": len(rows), "total": len(kept) + len(rows)}

    if elasticity_rows:
        epath = mirror / "files" / "GDP" / "elasticity.json"
        elast = _load(epath)
        keys = {tuple(e[k] for k in ELASTICITY_KEY) for e in elasticity_rows}
        kept_e = [e for e in elast if tuple(e.get(k) for k in ELASTICITY_KEY) not in keys]
        _write_ascii(epath, kept_e + list(elasticity_rows))
        out["elasticity_added"] = len(elasticity_rows)
    return out


def missing_gdp_scenarios(mirror, scenarios: Iterable[str]) -> list:
    """Scenarios with no GDP workbook in the mirror.

    deala matches a workbook to a scenario when the file stem is a substring of
    the scenario key. A pip-installed deala does not ship one for every
    scenario, and a missing one fails much later as a bare ``KeyError`` on the
    scenario name. Add the workbook to the mirror's ``files/GDP``.
    """
    stems = {p.stem for p in (Path(mirror) / "files" / "GDP").glob("*.xlsx")}
    return [s for s in scenarios if not any(st in s for st in stems)]


# --------------------------------------------------------------------------
# 2. electricity: the Eurostat consumption band
# --------------------------------------------------------------------------

#: Eurostat's seven non-household electricity bands: lower bound in MWh/yr,
#: band code, Eurostat nrg_cons code, and DEALA's label suffix.
EUROSTAT_BANDS = [
    (0,      "IA", "MWH_LT20",        "less than 20 MWh"),
    (20,     "IB", "MWH20-499",       "20-499 MWh"),
    (500,    "IC", "MWH500-1999",     "500-1999 MWh"),
    (2000,   "ID", "MWH2000-19999",   "2000-19999 MWh"),
    (20000,  "IE", "MWH20000-69999",  "20000-69999 MWh"),
    (70000,  "IF", "MWH70000-149999", "70000-149999 MWh"),
    (150000, "IG", "MWH_GE150000",    "more than 150000 MWh"),
]
BAND_CODES = [b[1] for b in EUROSTAT_BANDS]


def annual_mwh(kwh_per_kg: float, capacity_t_per_h: float, hours_per_year: float) -> float:
    """A plant's annual electricity use in MWh/yr.

    kWh/kg × t/h × 1000 kg/t × h/yr ÷ 1000 kWh/MWh. Capacity and operating
    hours are the user's inputs, per plant: ask for them, don't assume.
    """
    for name, v in (("kwh_per_kg", kwh_per_kg), ("capacity_t_per_h", capacity_t_per_h),
                    ("hours_per_year", hours_per_year)):
        if v < 0:
            raise ValueError(f"{name} is negative: {v}")
    return kwh_per_kg * capacity_t_per_h * hours_per_year


def band_for_consumption(mwh: float) -> str:
    """The Eurostat band code (``'IA'``..``'IG'``) for an annual use in MWh."""
    if mwh < 0:
        raise ValueError(f"negative consumption {mwh}")
    chosen = EUROSTAT_BANDS[0]
    for row in EUROSTAT_BANDS:
        if mwh >= row[0]:
            chosen = row
    return chosen[1]


def electricity_label(band: str) -> str:
    """DEALA's activity name for a band, e.g. ``'electricity - Non-household, 500-1999 MWh'``."""
    for _, code, _, label in EUROSTAT_BANDS:
        if code == band:
            return f"electricity - Non-household, {label}"
    raise KeyError(f"unknown band {band!r}; expected one of {BAND_CODES}")


def _electricity_act(db, country: str, band: str):
    label = electricity_label(band)
    hits = [a for a in db if a["name"] == label and a["location"] == country]
    if len(hits) > 1:
        raise ValueError(f'{len(hits)} activities named "{label}" at {country}; expected at most one')
    return hits[0] if hits else None


def pick_electricity(db, country: str, mwh: float):
    """The DEALA electricity activity for a plant using ``mwh`` a year in ``country``.

    Tries, in order, and records which one it used:

    1. ``band``: the country's own row in the band ``mwh`` falls in;
    2. ``nearest band XX``: the country's row in the nearest band that has
       one, searching one band down, then one up, then two down, ...;
    3. ``GLO``: the GLO row in the computed band.

    Raises if none exists. A fallback is not an error: it is a fact about
    DEALA's price table that the reader is entitled to see, so keep the
    returned record (a table of them is the electricity provenance).
    Returns ``(activity, record)``.
    """
    band = band_for_consumption(mwh)
    chosen, how = _electricity_act(db, country, band), "band"
    if chosen is None:
        i = BAND_CODES.index(band)
        for step in range(1, len(BAND_CODES)):
            for j in (i - step, i + step):
                if 0 <= j < len(BAND_CODES):
                    alt = _electricity_act(db, country, BAND_CODES[j])
                    if alt is not None:
                        chosen, how = alt, f"nearest band {BAND_CODES[j]}"
                        break
            if chosen is not None:
                break
    if chosen is None:
        chosen, how = _electricity_act(db, "GLO", band), "GLO"
    if chosen is None:
        raise ValueError(f"no electricity price for {country} in band {band}, "
                         "in any other band, or at GLO")
    record = {"country": country, "mwh_per_yr": mwh, "band": band, "resolution": how,
              "deala_activity": chosen["name"], "deala_location": chosen["location"]}
    return chosen, record


def electricity_per_kg(act) -> float:
    """kWh of electricity per unit of a Brightway activity's own output.

    Sums EVERY electricity input: banding a plant by one of several
    electricity flows would size it wrong.
    """
    prod = sum(e["amount"] for e in act.production()) or 1.0
    kwh = sum(e["amount"] for e in act.technosphere()
              if "electricity" in e.input["name"].lower())
    return kwh / prod


# --------------------------------------------------------------------------
# 3. the cost year, and building deala's price databases
# --------------------------------------------------------------------------

def price_fingerprint(repository_main_path, *, cost_year: int, base_year: int,
                      scenarios: Sequence[str]) -> str:
    """A hash of everything deala reads to compute a price.

    The price databases are a cache of the mirror. Guarding their rebuild with
    "if the database exists, skip" means a corrected price in the mirror has no
    effect at all: the run scores the old one and reports a plausible number.
    Rebuild whenever this fingerprint changes.
    """
    files = Path(repository_main_path) / "files"
    h = hashlib.sha256()
    for p in (sorted((files / "DEALA_activities").glob("*.json"))
              + [files / "GDP" / "elasticity.json", files / "GDP" / "gdp_deflator.json"]):
        if p.is_file():
            h.update(p.name.encode())
            h.update(p.read_bytes())
    h.update(f"{base_year}|{cost_year}|{sorted(scenarios)}".encode())
    return h.hexdigest()[:16]


def import_price_databases(deala_io_instance, *, cost_year: int, base_year: int,
                           repository_main_path, scenarios: Sequence[str] = ("remind_SSP2-NPi",),
                           price_calculation: str = "real", method_calc_r: str = "reg",
                           allow_delete: Sequence[str] = ()) -> dict:
    """Build deala's priced activity databases from a mirror, if they are stale.

    ``cost_year`` and ``base_year`` have NO default. Ask the user for both:

    * ``base_year`` is the currency year: prices come out in USD of that year.
    * ``cost_year`` is the cost horizon: the year every price is projected to.
      deala projects each dataset from ITS OWN Base Year, by the ratio
      GDP[region][cost_year] / GDP[region][dataset Base Year] raised to an
      elasticity. So setting ``cost_year`` equal to ``base_year`` is a no-op
      only for datasets whose Base Year is that year; older datasets are still
      projected forward across the gap. Say so when reporting costs.

    Before calling deala this refuses to go on if the project holds a database
    whose name contains "DEALA" and is not one of the price databases being
    rebuilt: ``import_DEALA_activities`` deletes every such database. Pass its
    name in ``allow_delete`` only if the user has agreed to lose it.

    Rebuilds only when :func:`price_fingerprint` changed. Returns
    ``{database: activity count}``.
    """
    import bw2data as bd

    if not isinstance(cost_year, int) or not isinstance(base_year, int):
        raise TypeError("cost_year and base_year must be integers chosen by the user")
    path = Path(repository_main_path)
    if not (path / MIRROR_MARKER).is_file():
        raise ValueError(f"{path} is not a mirror from mirror_deala_files "
                         "(pass the folder that CONTAINS files/)")
    missing = missing_gdp_scenarios(path, scenarios)
    if missing:
        raise ValueError(f"no GDP workbook in {path / 'files' / 'GDP'} for {missing}")

    dict_scenarios = {s: cost_year for s in scenarios}
    targets = ["DEALA_activities_" + s for s in scenarios]
    doomed = [db for db in bd.databases if "DEALA" in db and db not in targets
              and db not in allow_delete]
    if doomed:
        raise ValueError(f"deala would delete these databases: {doomed}. Rename them "
                         "(e.g. Costed_<db>) or pass allow_delete after asking the user.")

    fp = price_fingerprint(path, cost_year=cost_year, base_year=base_year, scenarios=scenarios)
    stale = [db for db in targets if db not in bd.databases
             or bd.databases[db].get("price_fingerprint") != fp]
    if stale:
        for db in targets:                 # never mix two price vintages
            if db in bd.databases:
                del bd.databases[db]
        deala_io_instance.import_DEALA_activities(
            base_year, dict_scenarios, str(path),
            price_calculation=price_calculation, method_calc_r=method_calc_r)
        deala_io_instance.create_default_DEALA_activities("DEALA_activities_", dict_scenarios)
        for db in targets:
            meta = dict(bd.databases[db])
            meta["price_fingerprint"] = fp
            bd.databases[db] = meta
        bd.databases.flush()
    return {db: len(bd.Database(db)) for db in targets}
