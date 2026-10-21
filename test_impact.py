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
# a wardrobe with no room is ONE item: the two guesses are marked pick-one, so a report saves just one
assert {x["pick_one"] for x in tagger.tag("wardrobe removed")["tags"]} == {"wardrobe"}
assert all(x["pick_one"] is None for x in tagger.tag("master bedroom wardrobe removed")["tags"])
assert all(x["pick_one"] is None for x in tagger.tag("wardrobe removed", fitting_ids={"WRD-MST"})["tags"])

# the working behind a choice, and carbon only where enough owners remove the fitting
rates = impact.ripout_rates(data, "T2S")
hi = impact.impact_of(F, "T2S", "KIT-CAB", "opt_out", ripout_rate=rates[("T2S", "KIT-CAB")])
assert hi["carbon_counted"] and abs(hi["carbon_avoided_kg"] - cab["weight_kg"] * cab["carbon_factor"]) < 1e-9
assert hi["ripout_skipped_rm"] == cab["removal_cost_rm"] and len(hi["working"]) == 3
assert f"{cab['weight_kg']:g} kg × {cab['carbon_factor']:g}" in hi["working"][0], hi["working"]
lo = impact.impact_of(F, "T2S", "TIL-FLR", "upgrade", None, U, ripout_rate=impact.OFFER_THRESHOLD - 0.01)
assert not lo["carbon_counted"] and lo["carbon_avoided_kg"] == 0 == lo["material_avoided_kg"], lo
assert lo["upgrade_revenue_rm"] > 0 and "not counted" in lo["working"][0]   # the money still counts
rare = [f for (u, f), r in rates.items() if r < impact.OFFER_THRESHOLD]
imp = impact.choice_impacts(data, "T2S")
assert rare and imp[imp.fitting_id.isin(rare)].carbon_avoided_kg.sum() == 0
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

# Neighbour Match (on a copy of the data): list, ask, match the nearest, collect
import neighbour_match as nm
tmp = Path(tempfile.mkdtemp()); shutil.copytree(impact.DATA_DIR, tmp / "data"); D = tmp / "data"
d0 = impact.load_data(D)
m0, r0 = d0["matches"], d0["requests"]
for unit in ("T2S", "C3R"):   # never a waiting listing and an open request for the same fitting
    waiting = set(m0.fitting_id[(m0.unit_type == unit) & (m0.status == "unmatched")])
    asked = set(r0.fitting_id[(r0.unit_type == unit) & (r0.status == "open")])
    assert not waiting & asked, (unit, waiting & asked)
done = m0[m0.status == "collected"].iloc[0]   # stored distances are the map's distances
assert done.distance_km == match_map.distance_km(done.from_owner, done.to_owner, done.unit_type)

hints = nm.suggestions(d0, "T2S")
owner, fid = hints["can_list"][0]                 # instant matches are suggested first
assert fid in hints["open_asks"]
l = nm.list_item("T2S", owner, fid, D)            # an owner lists what a neighbour asked for
asks = r0[(r0.unit_type == "T2S") & (r0.fitting_id == fid) & (r0.status == "open")]
nearest = min(asks.itertuples(), key=lambda r: (match_map.distance_km(owner, r.requester, "T2S"), r.request_id))
assert l["status"] == "matched" and l["to_owner"] == nearest.requester, l
r1 = impact.load_data(D)["requests"]
assert r1.set_index("request_id").loc[nearest.request_id, "listing_id"] == l["listing_id"]
before = impact.reuse_summary(impact.load_data(D), "T2S")
picked = nm.collect(l["listing_id"], D)           # picked up: now its carbon counts
after = impact.reuse_summary(impact.load_data(D), "T2S")
assert picked["status"] == "collected" and after["collected"] == before["collected"] + 1
assert abs(after["carbon_saved_kg"] - before["carbon_saved_kg"] - picked["carbon_saved_kg"]) < 0.1

wfid = hints["waiting"][0]                        # a neighbour asks for something that's waiting
asker = next(b for b in hints["buyers"]
             if not ((r0.requester == b) & (r0.fitting_id == wfid) & (r0.status == "open")).any())
req, l2 = nm.request_item("T2S", asker, wfid, D)
assert req["status"] == "matched" and l2["to_owner"] == asker and l2["listing_id"] == req["listing_id"]
kept = impact.load_data(D)["ripouts"]
never_removed = kept[(kept.unit_type == "T2S") & (kept.removed == 0) & (kept.fitting_id == "KIT-CAB")].owner_id.iloc[0]
for refused in (lambda: nm.list_item("T2S", owner, fid, D),               # listed twice
                lambda: nm.list_item("T2S", owner, "TIL-FLR", D),         # tiles can't be rehomed
                lambda: nm.list_item("T2S", "T2S-O999", "KIT-CAB", D),     # nobody by that id
                lambda: nm.list_item("T2S", never_removed, "KIT-CAB", D),  # didn't report removing it
                lambda: nm.collect(l["listing_id"], D),                   # already collected
                lambda: nm.collect("L999", D)):
    try:
        refused()
        raise AssertionError("should be refused")
    except ValueError:
        pass

# the community: "I'd like this" takes one offer, "I have one" answers one request
d1 = impact.load_data(D)
m1, r1 = d1["matches"], d1["requests"]
offer = m1[(m1.unit_type == "T2S") & (m1.status == "unmatched")].iloc[0]
taker = next(b for b in nm.people(d1, "T2S") if b != offer.from_owner and b.startswith("T2S-B"))
req, got = nm.claim(offer.listing_id, taker, D)
assert got["status"] == "matched" and got["to_owner"] == taker and req["status"] == "matched"
assert got["distance_km"] == match_map.distance_km(offer.from_owner, taker, "T2S")
assert impact.load_data(D)["requests"].set_index("request_id").loc[req["request_id"], "listing_id"] == offer.listing_id
open_req = r1[(r1.unit_type == "T2S") & (r1.status == "open")].iloc[0]
rr = d1["ripouts"]
giver = next(o for o in rr.owner_id[(rr.fitting_id == open_req.fitting_id) & (rr.removed == 1) & (rr.unit_type == "T2S")]
             if not ((m1.from_owner == o) & (m1.fitting_id == open_req.fitting_id)).any())
answer = nm.list_item("T2S", giver, open_req.fitting_id, D, condition="Like new", note="  Spare one  ",
                      request_id=open_req.request_id)
assert answer["to_owner"] == open_req.requester and answer["note"] == "Spare one" and answer["condition"] == "Like new"
# comments and thank-yous: who may write what
before_msgs = len(impact.load_data(D)["messages"])
msg = nm.comment(answer["listing_id"], taker, "Is it still there?", D)
assert msg["kind"] == "comment" and len(impact.load_data(D)["messages"]) == before_msgs + 1
done = nm.collect(answer["listing_id"], D, by=open_req.requester, thanks="Thank you!")
thanks = impact.load_data(D)["messages"].iloc[-1]
assert done["status"] == "collected" and thanks.kind == "thanks" and thanks.author == open_req.requester
c3r_person = next(iter(nm.people(d1, "C3R")))
for refused in (lambda: nm.claim(offer.listing_id, taker, D),                        # already taken
                lambda: nm.claim(got["listing_id"], offer.from_owner, D),            # not waiting any more
                lambda: nm.comment(offer.listing_id, taker, "   ", D),               # empty message
                lambda: nm.comment(offer.listing_id, taker, "x" * (nm.MAX_TEXT + 1), D),
                lambda: nm.comment(offer.listing_id, c3r_person, "hi", D),           # not in this home type
                lambda: nm.comment("L999", taker, "hi", D),
                lambda: nm.collect(got["listing_id"], D, by=c3r_person),             # not the giver or taker
                lambda: nm.collect(got["listing_id"], D, by=offer.from_owner, thanks="hi"),   # only the taker thanks
                lambda: nm.list_item("T2S", giver, open_req.fitting_id, D, request_id="R999"),
                lambda: nm.request_item("T2S", taker, "KIT-CAB", D, note=123)):
    try:
        refused()
        raise AssertionError("should be refused")
    except ValueError:
        pass
shutil.rmtree(tmp)

# the seeded community follows the app's own timeline: posted, then matched, then collected
import community
d2 = impact.load_data()
m2, msgs = d2["matches"], d2["messages"]
assert (m2.matched_at[m2.status != "unmatched"] >= m2.posted_at[m2.status != "unmatched"]).all()
assert (m2.collected_at[m2.status == "collected"] > m2.matched_at[m2.status == "collected"]).all()
th = msgs[msgs.kind == "thanks"].merge(m2, left_on="post_id", right_on="listing_id")
assert len(th) and (th.author == th.to_owner).all() and (th.status == "collected").all()
for unit in ("T2S", "C3R"):
    folks = community.everyone(d2, unit)          # simulated neighbours: no two names or homes the same
    assert len({p["name"] for p in folks}) == len(folks) == len({p["home"] for p in folks}), unit
    posts = community.feed(d2, unit)
    offers = [p["id"] for p in posts if p["kind"] == "offer"]
    assert sorted(offers) == sorted(m2.listing_id[m2.unit_type == unit]), unit   # every offer once
    for p in posts:                              # a request shown as a post waited for its match
        if p["kind"] == "wanted" and p["listing_id"]:
            row = m2.set_index("listing_id").loc[p["listing_id"]]
            r = d2["requests"].set_index("request_id").loc[p["id"]]
            assert r.posted_at < row.matched_at, p["id"]
board = community.leaderboard(d2, "T2S")
assert [b["carbon_kg"] for b in board] == sorted((b["carbon_kg"] for b in board), reverse=True)

# the API answers a refused step with 400 and the reason (nothing is written)
api = Flask(__name__); api.register_blueprint(dashboard.dashboard_bp); client = api.test_client()
for url, body in (("/api/match/list", {"unit": "T2S", "owner": owner, "fitting": "TIL-FLR"}),
                  ("/api/match/list", {"unit": "T2S", "owner": owner, "fitting": "KIT-CAB", "condition": "Broken"}),
                  ("/api/match/request", {"unit": "XYZ", "requester": "x", "fitting": "KIT-CAB"}),
                  ("/api/match/claim", {"listing_id": "L999", "requester": "x"}),
                  ("/api/match/comment", {"post_id": "L001", "author": "nobody", "text": "hi"}),
                  ("/api/match/collect", {"listing_id": "L999"}), ("/api/match/list", [1])):
    res = client.post(url, json=body)
    assert res.status_code == 400 and res.json["error"], (url, res.status_code)
page = client.get("/match?unit=T2S").data.decode()
assert "Give something away" in page and "Top neighbours" in page and 'class="post offer' in page
default_you = nm.suggestions(d2, "T2S")["can_list"][0][0]
assert f'value="{default_you}" selected' in page          # browsing as an owner with something to give
assert client.get("/match?unit=T2S&as=T2S-B001").status_code == 200

# saves at the same moment take turns: nothing lost, no id handed out twice (on a copy of the data)
import threading
tmp = Path(tempfile.mkdtemp()); shutil.copytree(impact.DATA_DIR, tmp / "data"); D = tmp / "data"
d3 = impact.load_data(D)
post_id = d3["matches"].listing_id.iloc[0]
writer = next(p for p in nm.people(d3, d3["matches"].unit_type.iloc[0]) if "-B" in p)
msgs_before, buyers_before = len(d3["messages"]), set(d3["choices"].buyer_id)
jobs = [threading.Thread(target=nm.comment, args=(post_id, writer, f"at once {i}", D)) for i in range(20)]
jobs += [threading.Thread(target=impact.save_buyer_choices, args=("T2S", {"KIT-CAB": "opt_out"}, D)) for _ in range(10)]
[j.start() for j in jobs]; [j.join() for j in jobs]
d4 = impact.load_data(D)
assert len(d4["messages"]) == msgs_before + 20 and not d4["messages"].message_id.duplicated().any()
new_buyers = d4["choices"][~d4["choices"].buyer_id.isin(buyers_before)].groupby("buyer_id").size()
assert len(new_buyers) == 10 and (new_buyers == 6).all(), new_buyers
shutil.rmtree(tmp)
assert impact.next_id(["T2S-B998", "T2S-B999"], "T2S-B") == "T2S-B1000"   # ids keep counting past 999
assert impact.next_id(["T2S-B1000", "T2S-B999", "C3R-B5000", "T2S-Bx"], "T2S-B") == "T2S-B1001"

# requests from other websites, wrong types and oversized bodies are refused (nothing is written)
res = client.post("/api/reset-demo", data="x=1", content_type="application/x-www-form-urlencoded")
assert res.status_code == 400, res.status_code           # a plain form can't reset the demo data
res = client.post("/api/reset-demo", json={}, headers={"Origin": "https://evil.example"})
assert res.status_code == 403, res.status_code           # nor can another website's page
res = client.post("/api/match/comment", json={"post_id": "L001", "author": "x", "text": "hi"},
                  headers={"Origin": "http://localhost"})
assert res.status_code == 400                             # same site: reaches the route (refused there)
for url in ("/api/choices", "/api/tag", "/api/report", "/api/match/list", "/api/match/request"):
    res = client.post(url, json={"unit": ["T2S"], "choices": {}, "fittings": [], "owner": "x", "requester": "x",
                                 "fitting": "KIT-CAB"})
    assert res.status_code == 400 and res.json["error"], (url, res.status_code)
res = client.post("/api/match/comment", json={"post_id": "L001", "author": "x", "text": "x" * 100_000})
assert res.status_code == 413 and res.json["error"], res.status_code

# demo sign-in: "/" opens it, then the SDP dashboard is home; each role lands on its page
from app import app as real_app
web = real_app.test_client()
assert web.get("/").headers["Location"].endswith("/signin")
page = web.get("/signin").data.decode()
assert "Sign in as SDP staff" in page and 'name="who"' in page
res = web.post("/signin", data={"who": "sdp"})
assert res.status_code == 302 and res.headers["Location"].endswith("/dashboard")
assert web.get("/").headers["Location"].endswith("/dashboard")       # signed in: home is the SDP dashboard
assert "SDP staff" in web.get("/dashboard?unit=T2S").data.decode()   # shown in the top bar
owner = nm.suggestions(d2, "C3R")["can_list"][0][0]
res = web.post("/signin", data={"who": owner})
assert res.headers["Location"].endswith("/match?unit=C3R"), res.headers["Location"]   # homeowner -> Match
page = web.get("/match").data.decode()                                 # no ?unit=: their home type
assert "Signed in as" in page and f'value="{owner}" selected' in page and "3-room condominium" in page
assert web.post("/signin", data={"who": "T2S-B003"}).headers["Location"].endswith("/advisor?unit=T2S")  # buyer
for bad in ("nobody", "T2S-O999", "", "XYZ-O001"):                    # only real people (or SDP staff)
    assert web.post("/signin", data={"who": bad}).status_code == 400, bad
for target in ("https://evil.example", "//evil.example", "/\\evil.example"):   # never off to another site
    res = web.post("/signin", data={"who": "sdp", "next": target})
    assert res.headers["Location"].endswith("/dashboard"), (target, res.headers["Location"])
assert web.post("/signin", data={"who": "sdp", "next": "/match?unit=T2S"}).headers["Location"].endswith("/match?unit=T2S")
assert web.post("/signin", data={"who": "sdp"}, headers={"Origin": "https://evil.example"}).status_code == 403
web.post("/signout")
assert web.get("/").headers["Location"].endswith("/signin")

t = impact.dashboard_totals(data, "T2S")
print("All checks passed.")
print({k: (round(v) if isinstance(v, float) else v) for k, v in t.items() if k != "reuse"})
print("reuse:", {k: round(v, 2) if isinstance(v, float) else v for k, v in t["reuse"].items()})
