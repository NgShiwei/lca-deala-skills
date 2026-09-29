"""deala_prices, offline: the mirror, price rows, bands, the cost-year contract.

A fake deala files/ tree stands in for the installed package; nothing here
needs deala or Brightway.
"""
import inspect
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins" / "claude-lca-deala-skills"
                       / "skills" / "deala-calculator" / "scripts"))
import deala_prices as dp  # noqa: E402

ROW = {"Code": "SHIPPED_1", "Costs per unit [USD/unit]": 1.0, "REMIND Region": "EUR",
       "Sector": "Material", "Type": "Widget", "Identifier": "consumables and supplies",
       "ISO-3166-1 ALPHA-2": "AA", "Base Year": 2020, "Years": 0}


@pytest.fixture
def source(tmp_path):
    files = tmp_path / "pkg" / "files"
    (files / "DEALA_activities").mkdir(parents=True)
    (files / "GDP").mkdir()
    (files / "DEALA_activities" / "material_beer.json").write_text(json.dumps([ROW]))
    (files / "GDP" / "elasticity.json").write_text(json.dumps(
        [{"Sector": "Material", "Type": "Widget", "ISO-3166-1 ALPHA-2": "AA", "Medium": 0.55}]))
    (files / "GDP" / "gdp_deflator.json").write_text("[1]")
    (files / "GDP" / "remind_SSP2.xlsx").write_bytes(b"")
    return files


@pytest.fixture
def mirror(tmp_path, source):
    return dp.mirror_deala_files(tmp_path / "mirror", source=source)


def new_row(code="NEW_AA", name="Türkiye widget", price=2.0):
    return dict(ROW, Code=code, Type=name, **{"Costs per unit [USD/unit]": price})


def test_mirror_returns_parent_of_files(mirror, source):
    assert (mirror / "files" / "GDP").is_dir()
    assert mirror.name == "mirror"            # repository_main_path, NOT .../files
    assert json.loads((source / "DEALA_activities" / "material_beer.json").read_text()) == [ROW]


def test_mirror_is_rebuilt_from_scratch(mirror, source):
    (mirror / "files" / "stale.txt").write_text("from an old run")
    again = dp.mirror_deala_files(mirror, source=source)
    assert not (again / "files" / "stale.txt").exists()


def test_mirror_refuses_foreign_or_installed_folders(tmp_path, source):
    foreign = tmp_path / "mine"
    foreign.mkdir()
    (foreign / "notes.txt").write_text("keep me")
    with pytest.raises(ValueError, match="not a deala mirror"):
        dp.mirror_deala_files(foreign, source=source)
    assert (foreign / "notes.txt").exists()
    with pytest.raises(ValueError, match="site-packages"):
        dp.mirror_deala_files(tmp_path / "site-packages" / "x", source=source)
    with pytest.raises(ValueError, match="source itself"):
        dp.mirror_deala_files(source / "inside", source=source)


def test_add_price_rows_is_idempotent_and_ascii(mirror):
    for _ in range(2):
        out = dp.add_price_rows(mirror, [new_row()])
    assert out == {"replaced": 1, "added": 1, "total": 2}
    raw = (mirror / "files" / "DEALA_activities" / "material_beer.json").read_bytes()
    raw.decode("ascii")                       # escaped, locale-proof
    assert [r["Code"] for r in json.loads(raw)] == ["SHIPPED_1", "NEW_AA"]


def test_add_price_rows_refuses_incomplete_rows_and_non_mirrors(mirror, source):
    bad = dict(new_row())
    del bad["REMIND Region"]
    with pytest.raises(ValueError, match="REMIND Region"):
        dp.add_price_rows(mirror, [bad])
    with pytest.raises(ValueError, match="never patch deala's installed files"):
        dp.add_price_rows(source.parent, [new_row()])


def test_elasticity_rows_replace_by_sector_type_iso(mirror):
    e = {"Sector": "Material", "Type": "Widget", "ISO-3166-1 ALPHA-2": "AA", "Medium": 0.0}
    dp.add_price_rows(mirror, [new_row()], elasticity_rows=[e])
    dp.add_price_rows(mirror, [new_row()], elasticity_rows=[e])
    rows = json.loads((mirror / "files" / "GDP" / "elasticity.json").read_text())
    assert rows == [e]


def test_gdp_scenarios_and_fingerprint(mirror):
    assert dp.missing_gdp_scenarios(mirror, ["remind_SSP2-NPi", "image_SSP1"]) == ["image_SSP1"]
    kw = dict(cost_year=2023, base_year=2023, scenarios=["remind_SSP2-NPi"])
    before = dp.price_fingerprint(mirror, **kw)
    assert dp.price_fingerprint(mirror, **dict(kw, cost_year=2040)) != before
    dp.add_price_rows(mirror, [new_row(price=3.0)])
    assert dp.price_fingerprint(mirror, **kw) != before


def test_cost_year_and_base_year_have_no_default():
    params = inspect.signature(dp.import_price_databases).parameters
    for name in ("cost_year", "base_year"):
        assert params[name].default is inspect.Parameter.empty
        assert params[name].kind is inspect.Parameter.KEYWORD_ONLY


# --- electricity bands --------------------------------------------------------

@pytest.mark.parametrize("mwh,band", [(0, "IA"), (19.9, "IA"), (20, "IB"), (499, "IB"),
                                      (500, "IC"), (1999.9, "IC"), (2000, "ID"),
                                      (69999, "IE"), (70000, "IF"), (1e6, "IG")])
def test_band_boundaries(mwh, band):
    assert dp.band_for_consumption(mwh) == band


def test_annual_mwh_is_capacity_times_hours():
    # 0.25 kWh/kg x 2 t/h x 8000 h/yr = 4000 MWh/yr
    assert dp.annual_mwh(0.25, 2, 8000) == pytest.approx(4000)
    with pytest.raises(ValueError):
        dp.annual_mwh(-1, 2, 8000)


def act(band, loc):
    return {"name": dp.electricity_label(band), "location": loc}


DB = [act("IC", "AA"), act("IE", "BB"), act("IB", "BB"), act("IC", "GLO")]


def test_pick_electricity_resolution_order():
    a, rec = dp.pick_electricity(DB, "AA", 1000)          # IC, own row
    assert (rec["band"], rec["resolution"], a["location"]) == ("IC", "band", "AA")
    a, rec = dp.pick_electricity(DB, "BB", 1000)          # IC missing: IB is one down
    assert rec["resolution"] == "nearest band IB" and a is DB[2]
    a, rec = dp.pick_electricity(DB, "CC", 1000)          # no rows at all: GLO
    assert rec["resolution"] == "GLO" and a is DB[3]
    with pytest.raises(ValueError, match="no electricity price"):
        dp.pick_electricity(DB, "CC", 50000)              # IE: no CC, no GLO IE
