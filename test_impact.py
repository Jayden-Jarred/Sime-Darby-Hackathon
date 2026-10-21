"""
test_impact.py - checks for the maths, the data rules, the pages and the API.

Run:   python test_impact.py      (prints "All checks passed." and the T2S totals)

Anything that saves data runs on a temporary copy of data/, so the real files
never change. Run it after editing impact.py, dashboard.py or the data.
"""

import impact

data = impact.load_data()
F = data["fittings"]

# keep saves nothing
k = impact.impact_of(F, "T2S", "KIT-CAB", "keep")
assert k["carbon_avoided_kg"] == 0 and k["sdp_saving_rm"] == 0

# opt-out: carbon = weight x factor, SDP saving = install - credit
# (expected values come from fittings.csv, so new figures don't break the checks)
cab = impact.get_fitting(F, "T2S", "KIT-CAB")
o = impact.impact_of(F, "T2S", "KIT-CAB", "opt_out")
assert abs(o["carbon_avoided_kg"] - cab["weight_kg"] * cab["carbon_factor"]) < 1e-9, o
assert o["sdp_saving_rm"] == cab["install_cost_rm"] - cab["credit_rm"], o
assert o["buyer_saving_rm"] == cab["credit_rm"] + cab["removal_cost_rm"], o

# upgrade: revenue = margin, standard item's carbon avoided
u = impact.impact_of(F, "T2S", "KIT-CAB", "upgrade")
assert u["upgrade_revenue_rm"] == cab["upgrade_margin_rm"] and u["sdp_saving_rm"] == 0, u

# the generator's sums: credit and margin follow its stated shares
import generate_dummy_data as gen
assert cab["credit_rm"] == round(cab["install_cost_rm"] * gen.CREDIT_SHARE, -1)
assert cab["upgrade_margin_rm"] == round(cab["install_cost_rm"] * gen.MARGIN_SHARE, -1)
assert len(F) == len(gen.FITTINGS) and set(F.carbon_factor) <= {f[6] for f in gen.FITTINGS}

# rules: tiles can't be opted out, toilets can't be changed
for fid, choice in (("TIL-FLR", "opt_out"), ("SAN-BTH", "upgrade"), ("KIT-CAB", "skip")):
    try:
        impact.impact_of(F, "T2S", fid, choice)
        raise AssertionError(f"{fid}/{choice} should be refused")
    except ValueError:
        pass

# advice thresholds
assert impact.advice_for(0.62, "opt_out").startswith("Stop")
assert impact.advice_for(0.35, "opt_out").startswith("Offer")
assert impact.advice_for(0.10, "opt_out").startswith("Keep")
assert impact.advice_for(0.90, "fixed").startswith("Keep")
assert impact.advice_for(0.35, "upgrade_only") == "Offer as upgrade"   # tiles can't be opted out

# rip-out index rates are between 0 and 1
idx = impact.ripout_index(data, "T2S")
assert idx.rate.between(0, 1).all()

# credit is reported separately for the Advisor summary
assert o["buyer_credit_rm"] == cab["credit_rm"] and u["buyer_credit_rm"] == 0

# upgrade options: the margin comes from the option picked; the first is the default
U = data["upgrades"]
top = U[(U.unit_type == "T2S") & (U.fitting_id == "KIT-TOP")].set_index("upgrade_id")
g = impact.impact_of(F, "T2S", "KIT-TOP", "upgrade", "GRANITE", U)
assert g["upgrade_name"] == "Granite top" and g["upgrade_revenue_rm"] == top.margin_rm["GRANITE"], g
d = impact.impact_of(F, "T2S", "KIT-TOP", "upgrade", None, U)
assert d["upgrade_id"] == top.index[0] and d["upgrade_revenue_rm"] == top.margin_rm.iloc[0], d
assert g["carbon_avoided_kg"] == d["carbon_avoided_kg"] > 0   # the standard top is never made either way
assert impact.impact_of(F, "T2S", "KIT-TOP", "keep", "GRANITE", U)["upgrade_id"] is None
# every option has a picture, and a finish in the 3D model (LOOKS in static/house3d.js)
import re
STATIC = impact.DATA_DIR.parent / "static"
assert all((STATIC / img).is_file() for img in U.image), U[[not (STATIC / i).is_file() for i in U.image]]
looks = (STATIC / "house3d.js").read_text(encoding="utf-8").split("export const LOOKS", 1)[1].split("};", 1)[0]
assert set(U.upgrade_id) <= set(re.findall(r"^\s+'?([A-Z][A-Z-]+)'?:", looks, re.M)), set(U.upgrade_id)
try:
    impact.impact_of(F, "T2S", "KIT-TOP", "upgrade", "MARBLE", U)
    raise AssertionError("an unknown upgrade should be refused")
except KeyError:
    pass

# upgrade mix: every option listed, counts match the upgrade choices, shares sum to 1 per fitting
for unit in ("T2S", "C3R"):
    mix = impact.upgrade_mix(data, unit)
    imp = impact.choice_impacts(data, unit)
    assert len(mix) == len(U[U.unit_type == unit]), unit                       # options nobody picked stay in
    assert mix.picks.sum() == (imp.choice == "upgrade").sum(), unit
    assert abs(mix.margin_earned_rm.sum() - imp.upgrade_revenue_rm.sum()) < 1e-6, unit   # ties to upgrade income
    shares = mix[mix.fitting_upgrades > 0].groupby("fitting_id").share.sum()
    assert ((shares - 1).abs() < 1e-9).all(), shares
    assert mix.share.between(0, 1).all()
# one hand-made case: 2 granite, 1 quartz, 1 upgrade saved without an option (= the default, quartz)
import pandas as pd
few = dict(data, choices=pd.DataFrame(
    [(f"T2S-B{i:03d}", "T2S", "KIT-TOP", "upgrade", up) for i, up in enumerate(["GRANITE", "GRANITE", "QUARTZ", ""])],
    columns=data["choices"].columns))
fm = impact.upgrade_mix(few, "T2S").set_index(["fitting_id", "upgrade_id"])
assert fm.picks["KIT-TOP", "QUARTZ"] == 2 and fm.picks["KIT-TOP", "GRANITE"] == 2 and fm.picks["KIT-TOP", "SINTERED"] == 0
assert fm.share["KIT-TOP", "GRANITE"] == 0.5 and fm.margin_earned_rm["KIT-TOP", "QUARTZ"] == 2 * top.margin_rm["QUARTZ"]
assert (fm.drop(index="KIT-TOP", level="fitting_id").share == 0).all()                           # no upgrades: share 0, not 0/0
assert impact.upgrade_mix(dict(data, choices=data["choices"].iloc[:0]), "C3R").picks.sum() == 0

# saving a buyer's choices appends one row per choosable fitting (on a copy of the data)
import shutil, tempfile
from pathlib import Path


def next_id(ids, prefix):
    """The id the app should hand out next, e.g. T2S-B101 after T2S-B100 (works on demo-used data too)."""
    return f"{prefix}{max((int(i[len(prefix):]) for i in ids if i.startswith(prefix)), default=0) + 1:03d}"


tmp = Path(tempfile.mkdtemp())
shutil.copytree(impact.DATA_DIR, tmp / "data")
before = impact.load_data(tmp / "data")["choices"]
bid = impact.save_buyer_choices("T2S", {"KIT-CAB": "opt_out", "TIL-FLR": "upgrade"}, tmp / "data")
after = impact.load_data(tmp / "data")["choices"]
assert len(after) == len(before) + 6, (len(before), len(after))          # 6 choosable T2S fittings
assert bid == next_id(before.buyer_id, "T2S-B"), bid
saved = after[after.buyer_id == bid].set_index("fitting_id").choice
assert saved["KIT-CAB"] == "opt_out" and saved["TIL-FLR"] == "upgrade" and saved["WRD-MST"] == "keep"
up_saved = after[after.buyer_id == bid].set_index("fitting_id").upgrade_id
assert up_saved["TIL-FLR"] == "HOMOGENEOUS" and up_saved["KIT-CAB"] == ""   # default option; none for opt-out
bid3 = impact.save_buyer_choices("T2S", {"KIT-TOP": "upgrade"}, tmp / "data", upgrade_picks={"KIT-TOP": "SINTERED"})
saved3 = impact.load_data(tmp / "data")["choices"].query("buyer_id == @bid3").set_index("fitting_id")
assert saved3.upgrade_id["KIT-TOP"] == "SINTERED", saved3
# an unknown option is refused even when the fitting isn't being upgraded, or isn't a fitting
rows_now = len(impact.load_data(tmp / "data")["choices"])
for picks, ups in (({"KIT-TOP": "upgrade"}, {"KIT-TOP": "MARBLE"}),
                   ({"KIT-CAB": "opt_out"}, {"KIT-CAB": "MARBLE"}),
                   ({}, {"NOPE": "X"}),
                   ({}, {"SAN-BTH": "QUARTZ"}),        # fixed fitting: no options at all
                   ({}, {"KIT-TOP": ["QUARTZ"]})):     # not an upgrade_id
    try:
        impact.save_buyer_choices("T2S", picks, tmp / "data", upgrade_picks=ups)
        raise AssertionError(f"{ups} should be refused")
    except (KeyError, ValueError):
        pass
assert len(impact.load_data(tmp / "data")["choices"]) == rows_now   # nothing saved by a refused call
for bad in ({"TIL-FLR": "opt_out"}, {"SAN-BTH": "upgrade"}, {"NOPE": "keep"}):
    try:
        impact.save_buyer_choices("T2S", bad, tmp / "data")
        raise AssertionError(f"{bad} should be refused")
    except ValueError:
        pass
# an explicit "keep" for a fixed fitting is fine, but only choosable fittings are saved
bid2 = impact.save_buyer_choices("T2S", {"SAN-BTH": "keep"}, tmp / "data")
saved2 = impact.load_data(tmp / "data")["choices"].query("buyer_id == @bid2")
assert len(saved2) == 6 and "SAN-BTH" not in set(saved2.fitting_id), saved2
shutil.rmtree(tmp)

# simulator: waste balances, more uptake never means more waste, payback is sane
sim = impact.simulate(data, "T2S", homes=500)
tt = sim["totals"]
assert abs(tt["prevented_kg"] + tt["reused_kg"] + tt["wasted_kg"] - tt["baseline_kg"]) < 1e-6
low = impact.simulate(data, "T2S", homes=500, uptake=0.2)["totals"]
assert low["wasted_kg"] >= tt["wasted_kg"] and low["prevented_kg"] <= tt["prevented_kg"]
none = impact.simulate(data, "T2S", homes=500, uptake=0, match_rate=0)["totals"]
assert abs(none["wasted_kg"] - none["baseline_kg"]) < 1e-6 and none["payback_homes"] is None
assert all(f["rehomed"] == 0 for f in sim["fittings"] if f["fitting_id"] in impact.NOT_REUSABLE)

# tagger: English, Malay, ambiguous wardrobe, nothing to tag
import tagger
assert [x["fitting_id"] for x in tagger.tag("hak semua kabinet dapur, tukar quartz top")["tags"]] == ["KIT-CAB", "KIT-TOP"]
assert tagger.tag("almari bilik kecil tukar")["tags"][0]["fitting_id"] == "WRD-BR2"
assert tagger.tag("repaint the walls")["tags"] == []
assert {x["fitting_id"] for x in tagger.tag("wardrobe removed")["tags"]} == {"WRD-MST", "WRD-BR2"}
assert tagger.tag("bedroom 2 wardrobe out", fitting_ids={"WRD-MST"})["tags"] == []
# the honest test set never overlaps the tuning notes or the page's examples
import dashboard
held = {n for n, _ in tagger.HELD_OUT}
assert not held & {n for n, _ in tagger.TUNING_NOTES}
assert not held & set(dashboard.EXAMPLE_NOTES)

# API errors: plain JSON messages, and unknown units are a 400, not a 404 page
from flask import Flask
api = Flask(__name__); api.register_blueprint(dashboard.dashboard_bp)
c = api.test_client()
res = c.get("/api/impact?unit=T2S&fitting=NOPE&choice=keep")
assert res.status_code == 400 and res.json["error"] == "No fitting NOPE for unit type T2S", res.json
res = c.get("/api/impact?unit=XYZ&fitting=KIT-CAB&choice=keep")
assert res.status_code == 400 and res.json["error"] == "Unknown unit type XYZ", res.data
assert c.get("/api/ripout-index?unit=XYZ").status_code == 400
assert c.get("/dashboard?unit=XYZ").status_code == 404   # pages still 404
res = c.get("/api/impact?unit=T2S&fitting=KIT-TOP&choice=upgrade&upgrade=QUARTZ")
assert res.status_code == 200 and res.json["upgrade_name"] == "Quartz top", res.json
res = c.get("/api/impact?unit=T2S&fitting=KIT-TOP&choice=upgrade&upgrade=MARBLE")
assert res.status_code == 400 and res.json["error"] == "No upgrade MARBLE for KIT-TOP", res.json

# the dashboard shows the upgrade mix for both unit types, and it downloads as CSV
for unit in ("T2S", "C3R"):
    page = c.get(f"/dashboard?unit={unit}")
    assert page.status_code == 200 and b"Which upgrades buyers pick" in page.data and b"mix-seg o1" in page.data, unit
    res = c.get(f"/export/upgrade-mix.csv?unit={unit}")
    assert res.status_code == 200 and b"upgrade_id,upgrade_name,picks,share_pct" in res.data, unit

# CSV downloads start with their header row (no comment line); "simulated" is in the filename
res = c.get("/export/choices.csv?unit=T2S")
assert res.data.decode().splitlines()[0] == "buyer_id,unit_type,fitting_id,choice,upgrade_id", res.data[:80]
assert "simulated.csv" in res.headers["Content-Disposition"]

# reuse carbon: one formula, so the Neighbour Match page and the dashboard agree
import match_map
reuse = impact.reuse_summary(data, "T2S")
items = match_map.listings(data, "T2S")
assert abs(sum(i["carbon_saved_kg"] for i in items) - reuse["carbon_saved_kg"]) < 0.05 * len(items)
assert impact.reuse_carbon_kg(120, 0.7, 2) == 120 * 0.7 - 2 * 2 * impact.TRANSPORT_KGCO2E_PER_KM

# What-if: the server clamps to the same limits the sliders show; nan and inf fall back to the defaults
lo, hi, _ = dashboard.SIM_SLIDERS["homes"]
assert c.get("/api/simulate?unit=T2S&homes=99999").json["totals"]["homes"] == hi
assert f'id="homes" name="homes" min="{lo}" max="{hi}"'.encode() in c.get("/simulate?unit=T2S").data
res = c.get("/api/simulate?unit=T2S&homes=inf&uptake=nan&credit_mult=-inf")
default = c.get("/api/simulate?unit=T2S").json["totals"]
assert res.status_code == 200 and res.json["totals"] == default, res.status_code

# advice colours: set once in dashboard.py, on every page as CSS variables (the tagger page uses the badges too)
for path in ("/dashboard?unit=T2S", "/tagger?unit=T2S", "/advisor?unit=T2S", "/match?unit=T2S", "/simulate?unit=T2S"):
    page = c.get(path).data.decode()
    assert all(f"--advice-{k}: {v};" in page for k, v in dashboard.ADVICE_COLOUR.items()), path

# bad POST bodies are a 400, not a crash (each fails before anything is written)
for url, body in (("/api/choices", [1, 2]), ("/api/report", [1, 2]),
                  ("/api/report", {"unit": "T2S", "fittings": [["KIT-CAB"]], "note": "x"})):
    res = c.post(url, json=body)
    assert res.status_code == 400 and "error" in res.json, (url, body, res.status_code)
assert c.post("/api/tag", json={"unit": "T2S", "note": None}).json["tags"] == []

# adding a rip-out report (on a copy of the data); a missing note is saved blank, not "None"
tmp = Path(tempfile.mkdtemp()); shutil.copytree(impact.DATA_DIR, tmp / "data")
before = impact.load_data(tmp / "data")["ripouts"]
oid = impact.add_ripout_report("C3R", ["KIT-CAB"], "hak kabinet", tmp / "data")
rr = impact.load_data(tmp / "data")["ripouts"]
assert oid == next_id(before.owner_id, "C3R-O"), oid
assert rr[rr.owner_id == oid].removed.sum() == 1 and len(rr[rr.owner_id == oid]) == 6
oid2 = impact.add_ripout_report("C3R", ["KIT-CAB"], None, tmp / "data")
rr = impact.load_data(tmp / "data")["ripouts"]
assert "None" not in rr[rr.owner_id == oid2].note.fillna("").tolist(), rr[rr.owner_id == oid2]
shutil.rmtree(tmp)

t = impact.dashboard_totals(data, "T2S")
print("All checks passed.")
print({k: (round(v) if isinstance(v, float) else v) for k, v in t.items() if k != "reuse"})
print("reuse:", {k: round(v, 2) if isinstance(v, float) else v for k, v in t["reuse"].items()})
