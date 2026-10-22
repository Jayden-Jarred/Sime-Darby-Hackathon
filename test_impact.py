"""
test_impact.py - checks for the maths, the data rules, the pages and the API.

Run:   python test_impact.py      (prints "All checks passed." and the T2S totals)

Anything that saves data runs on a temporary copy of data/, so the real files
never change. Run it after editing impact.py, dashboard.py or the data.
"""

import generate_dummy_data
import impact
import tagger

tagger._client = lambda: None           # offline: no calls to Claude even if ANTHROPIC_API_KEY is set (a stand-in is used below)
generate_dummy_data.ensure_database()   # a fresh clone builds data/right_fit.db first
data = impact.load_data()
F = data["fittings"]

# keep saves nothing
k = impact.impact_of(F, "T2S", "KIT-CAB", "keep")
assert k["carbon_avoided_kg"] == 0 and k["sdp_saving_rm"] == 0

# opt-out: carbon = weight x factor, SDP saving = install - credit
# (expected values come from the fittings table, so new figures don't break the checks)
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

# reuse rate, as the proposal defines it: fittings rehomed out of every reusable fitting owners removed
rp = data["ripouts"]
for unit in ("T2S", "C3R"):
    s = impact.reuse_summary(data, unit)
    removed = rp[(rp.unit_type == unit) & (rp.removed == 1) & ~rp.fitting_id.isin(impact.NOT_REUSABLE)]
    assert s["removed"] == len(removed) and s["collected"] <= s["listed"] <= s["removed"], (unit, s)
    assert s["reuse_rate"] == s["collected"] / s["removed"], (unit, s)
page = client.get("/dashboard?unit=T2S").data.decode()
r = impact.reuse_summary(data, "T2S")
assert f"{r['collected']} of the {r['removed']} reusable fittings owners removed" in page

# the dashboard works out each distinct choice once, with the same results as one by one
import pandas as pd
real_impact_of, calls = impact.impact_of, []
impact.impact_of = lambda *a, **k: calls.append(a[1:5]) or real_impact_of(*a, **k)
try:
    fast = impact.choice_impacts(data, "T2S")
finally:
    impact.impact_of = real_impact_of
ct = data["choices"][data["choices"].unit_type == "T2S"]
assert len(calls) == len(set(zip(ct.unit_type, ct.fitting_id, ct.choice, ct.upgrade_id))) < len(ct) / 5, len(calls)
rates = impact.ripout_rates(data, "T2S")
one_by_one = pd.DataFrame([real_impact_of(F, u, f, ch, up or None, data["upgrades"], rates.get((u, f)))
                           for u, f, ch, up in zip(ct.unit_type, ct.fitting_id, ct.choice, ct.upgrade_id)])
num = ["carbon_avoided_kg", "material_avoided_kg", "sdp_saving_rm", "upgrade_revenue_rm", "buyer_saving_rm"]
assert len(fast) == len(ct) and (fast[num] == one_by_one[num]).all().all()
assert (fast.fitting_id.tolist() == ct.fitting_id.tolist())                 # same order as the choices

# the What-if explains why tiles count there but not in the Advisor, with this home type's real figures
for unit, name, kg in (("T2S", "ground-floor tiles", "1,800"), ("C3R", "living-room tiles", "715")):
    page = client.get(f"/simulate?unit={unit}").data.decode()
    rate = impact.ripout_rates(data, unit)[(unit, "TIL-FLR")]
    assert "Why tiles count here but not in the Advisor" in page and f"{kg} kg per home" in page, unit
    assert f"{rate * 100:.0f}% of owners rip out the {name}" in page and f"{round(impact.OFFER_THRESHOLD * 100)}%" in page, unit

# AI tagging names each fitting the way this home type's data does (not the tagger's generic names)
for unit, name in (("T2S", "Ground-floor tiles"), ("C3R", "Living-room tiles")):
    tags = client.post("/api/tag", json={"unit": unit, "note": "hack all the floor tiles, retile"}).json["tags"]
    assert [t["name"] for t in tags if t["fitting_id"] == "TIL-FLR"] == [name], (unit, tags)

# saving under a person (on a copy of the data): a buyer who confirms again, an owner who reports again
tmp = Path(tempfile.mkdtemp()); shutil.copytree(impact.DATA_DIR, tmp / "data"); D = tmp / "data"
c0 = impact.load_data(D)["choices"]
buyer = "T2S-B025"
assert impact.save_buyer_choices("T2S", {"KIT-CAB": "opt_out", "TIL-FLR": "upgrade"}, D, buyer_id=buyer) == buyer
c1 = impact.load_data(D)["choices"]
mine = c1[c1.buyer_id == buyer].set_index("fitting_id")
assert c1.buyer_id.nunique() == c0.buyer_id.nunique() and len(mine) == len(c0[c0.buyer_id == buyer])
assert mine.choice["KIT-CAB"] == "opt_out" and mine.choice["TIL-FLR"] == "upgrade" and mine.choice["KIT-TOP"] == "keep"
others = lambda c: c[c.buyer_id != buyer].sort_values(["buyer_id", "fitting_id"]).reset_index(drop=True)
assert others(c1).equals(others(c0))                                   # nobody else's choices changed
r0 = impact.load_data(D)["ripouts"]
owner = r0[(r0.unit_type == "T2S") & (r0.fitting_id == "KIT-CAB") & (r0.removed == 0)].owner_id.iloc[0]
rate0 = impact.ripout_rates(impact.load_data(D), "T2S")[("T2S", "KIT-CAB")]
assert impact.add_ripout_report("T2S", ["KIT-CAB"], "hak kabinet", D, owner_id=owner) == owner
impact.add_ripout_report("T2S", ["KIT-CAB"], "hak kabinet lagi", D, owner_id=owner)   # the same report twice
r1 = impact.load_data(D)["ripouts"]
d1 = impact.load_data(D)
owners = r0[r0.unit_type == "T2S"].owner_id.nunique()
assert r1.owner_id.nunique() == r0.owner_id.nunique()                 # still the same owners
assert abs(impact.ripout_rates(d1, "T2S")[("T2S", "KIT-CAB")] - rate0 - 1 / owners) < 1e-9   # counted once
row = r1[(r1.owner_id == owner) & (r1.fitting_id == "KIT-CAB")].iloc[0]
assert row.removed == 1 and row.note == "hak kabinet lagi"
keep = lambda r: r[~((r.owner_id == owner) & (r.fitting_id == "KIT-CAB"))].reset_index(drop=True)
assert keep(r1).fillna("").equals(keep(r0).fillna(""))                # nothing else changed
for refused in (lambda: impact.save_buyer_choices("T2S", {}, D, buyer_id="C3R-B001"),   # another home type
                lambda: impact.save_buyer_choices("T2S", {}, D, buyer_id="T2S-O001"),   # not a buyer
                lambda: impact.add_ripout_report("T2S", ["KIT-CAB"], "", D, owner_id="T2S-B001")):
    try:
        refused()
        raise AssertionError("should be refused")
    except ValueError:
        pass
shutil.rmtree(tmp)

# the Advisor and AI tagging save under the person signed in (save functions stubbed: no real data is written)
import community
saved_for = {}
real_save, real_report = impact.save_buyer_choices, impact.add_ripout_report
impact.save_buyer_choices = lambda unit, picks, upgrade_picks=None, buyer_id=None: saved_for.update(buyer=buyer_id) or buyer_id or "T2S-B999"
impact.add_ripout_report = lambda unit, fids, note, owner_id=None: saved_for.update(owner=owner_id) or owner_id or "T2S-O999"
try:
    web = real_app.test_client()
    for who, unit, expect_buyer, expect_owner in (("T2S-B025", "T2S", "T2S-B025", None), ("T2S-B025", "C3R", None, None),
                                                  ("T2S-O001", "T2S", None, "T2S-O001"), ("sdp", "T2S", None, None)):
        web.post("/signin", data={"who": who})
        res = web.post("/api/choices", json={"unit": unit, "choices": {}})
        assert saved_for["buyer"] == expect_buyer and res.json["name"] == (community.person(who)["name"] if expect_buyer else None), (who, unit)
        res = web.post("/api/report", json={"unit": unit, "note": "x", "fittings": ["KIT-CAB"]})
        assert saved_for["owner"] == expect_owner, (who, unit, saved_for)
    web.post("/signout")
    web.post("/api/choices", json={"unit": "T2S", "choices": {}})
    assert saved_for["buyer"] is None                                    # not signed in: a new buyer
finally:
    impact.save_buyer_choices, impact.add_ripout_report = real_save, real_report
c = data["choices"]                                                      # a signed-in buyer's choices are filled in
fid = c[(c.buyer_id == "T2S-B025") & (c.choice != "keep")]
web.post("/signin", data={"who": "T2S-B025"})
page = web.get("/advisor?unit=T2S").data.decode()
assert "Saving for <b>" + community.person("T2S-B025")["name"] in page
for f, ch in zip(fid.fitting_id, fid.choice):
    assert f'name="c-{f}" value="{ch}" checked' in page, (f, ch)
web.post("/signin", data={"who": "T2S-O001"})
assert f"Adds to <b>{community.person('T2S-O001')['name']}</b>" in web.get("/tagger?unit=T2S").data.decode()
web.post("/signout")
assert "Saves as a new buyer" in web.get("/advisor?unit=T2S").data.decode()

# AI tagging with a stand-in for Claude's API (no network, no key): what is sent, how the answer
# is used, and the keyword rules taking over when there's no usable answer
import json
import logging
from types import SimpleNamespace as NS
logging.getLogger("tagger").setLevel(logging.ERROR)   # the fallbacks below are on purpose
asked = []


def claude_says(answer, stop="end_turn"):
    def create(**request):
        asked.append(request)
        text = answer if isinstance(answer, str) else json.dumps(answer)
        return NS(stop_reason=stop, content=[NS(type="thinking", thinking=""), NS(type="text", text=text)])
    tagger._ask_claude.cache_clear()
    tagger._client = lambda: NS(beta=NS(messages=NS(create=create)))


def said(fid, conf, evidence, room_not_stated=False):
    return {"fitting_id": fid, "confidence": conf, "reason": "r", "evidence": evidence, "room_not_stated": room_not_stated}


try:
    note = "Contractor HACKED the almari in bilik utama, tukar quartz top"
    claude_says({"tags": [said("WRD-MST", 0.92, ["almari", "bilik utama"]), said("KIT-TOP", 0.8, ["quartz top", "granite"]),
                          said("LGT-DEC", 0.2, ["lampu"])], "removed": True, "removal_words": ["hacked", "tukar"]})
    r = tagger.tag(note, "T2S", {"WRD-MST", "KIT-TOP", "LGT-DEC"})
    assert r["engine"] == "ai" and [(t["fitting_id"], t["confidence"]) for t in r["tags"]] == [("WRD-MST", 0.92), ("KIT-TOP", 0.8)], r
    # highlights: found in the note by the app (any case), so words that aren't there ("granite") mark nothing
    assert {(note[s["start"]:s["end"]], s["fitting_id"]) for s in r["spans"]} == {
        ("almari", "WRD-MST"), ("bilik utama", "WRD-MST"), ("quartz top", "KIT-TOP"), ("HACKED", "action"), ("tukar", "action")}
    sent = asked[-1]
    assert sent["model"] == tagger.MODEL and sent["system"] == tagger.SYSTEM and f"<note>\n{note}\n</note>" in sent["messages"][0]["content"]
    assert sent["output_config"]["format"]["schema"]["properties"]["tags"]["items"]["properties"]["fitting_id"]["enum"] == ["KIT-TOP", "LGT-DEC", "WRD-MST"]
    tagger.tag(note, "T2S", {"WRD-MST", "KIT-TOP", "LGT-DEC"})
    assert len(asked) == 1                    # the same note again comes from the cache, not another call
    claude_says({"tags": [said("WRD-BR2", 0.9, ["kids room"])], "removed": True, "removal_words": []})
    assert tagger.tag("kids room wardrobe out", "C3R", {"WRD-MST", "KIT-CAB"})["tags"] == []   # not a fitting this home has
    # a wardrobe with no room: two guesses for one item are a pick-one, unless only one is left
    claude_says({"tags": [said("WRD-MST", 0.5, ["wardrobe"], True), said("WRD-BR2", 0.45, ["wardrobe"], True)],
                 "removed": True, "removal_words": ["removed"]})
    assert {t["pick_one"] for t in tagger.tag("wardrobe removed", "T2S")["tags"]} == {"wardrobe"}
    assert [t["pick_one"] for t in tagger.tag("wardrobe removed", "T2S", {"WRD-MST"})["tags"]] == [None]
    for answer, stop, why in (("", "refusal", "Claude declined to read this note"),
                              ('{"tags": [', "max_tokens", "Claude's answer was cut off (max_tokens)"),
                              ("not json", "end_turn", "Claude's answer couldn't be read"),
                              ({"tags": [{"fitting_id": "KIT-CAB"}]}, "end_turn", "Claude's answer couldn't be read")):
        claude_says(answer, stop)
        r = tagger.tag("hak semua kabinet dapur", "T2S")
        assert r["engine"] == "keywords" and r["ai_error"] == why, (stop, r)
        assert r["tags"] == tagger.keyword_tag("hak semua kabinet dapur")["tags"]
    # the page: only the typed note goes to Claude; the accuracy and the table stay on the keyword rules
    claude_says({"tags": [said("TIL-FLR", 0.9, ["floor tiles"])], "removed": True, "removal_words": ["hack"]})
    res = web.post("/api/tag", json={"unit": "T2S", "note": "hack all the floor tiles"}).json
    assert res["engine"] == "ai" and [t["name"] for t in res["tags"]] == ["Ground-floor tiles"], res
    n = len(asked)
    page = web.get("/tagger?unit=T2S").data.decode()
    assert len(asked) == n and f"read by Claude (<code>{tagger.MODEL}</code>)" in page and "How accurate is the backup?" in page
finally:
    tagger._client = lambda: None
    tagger._ask_claude.cache_clear()
assert "pip install anthropic" in web.get("/tagger?unit=T2S").data.decode()   # AI off: the page says how to turn it on

# the database: consistent, and it refuses rows that break the rules (on a copy of the data)
import sqlite3
import db
con = db.connect()
assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
assert con.execute("PRAGMA foreign_key_check").fetchall() == []         # every row points at something real
con.close()
assert set(data["people"].person_id) == set(data["ripouts"].owner_id) | set(data["choices"].buyer_id)
tmp = Path(tempfile.mkdtemp()); shutil.copytree(impact.DATA_DIR, tmp / "data"); D = tmp / "data"
bad_rows = [("choices", {"buyer_id": "T2S-B001", "unit_type": "T2S", "fitting_id": "KIT-CAB", "choice": "maybe"}),
            ("choices", {"buyer_id": "T2S-B999", "unit_type": "T2S", "fitting_id": "KIT-CAB", "choice": "keep"}),
            ("choices", {"buyer_id": "T2S-B001", "unit_type": "T2S", "fitting_id": "KIT-CAB", "choice": "keep"}),
            ("ripouts", {"owner_id": "T2S-O001", "unit_type": "T2S", "fitting_id": "XXX", "removed": 1}),
            ("ripouts", {"owner_id": "T2S-O001", "unit_type": "T2S", "fitting_id": "KIT-CAB", "removed": 2}),
            ("matches", {"listing_id": "L900", "from_owner": "T2S-O001", "unit_type": "T2S", "fitting_id": "KIT-TOP",
                         "status": "matched", "condition": "Good", "posted_at": "2026-10-22 09:00"})]
for table, row in bad_rows:   # a bad choice, an unknown buyer, a duplicate (T2S-B001 already chose for KIT-CAB),
    try:                      # an unknown fitting, a removed flag of 2, a match with nobody taking it
        with db.transaction(D) as c:
            db.insert(c, table, row)
        raise AssertionError(f"database accepted {table} {row}")
    except sqlite3.IntegrityError:
        pass
before = len(impact.load_data(D)["messages"])
try:                                   # a save that fails part-way leaves nothing behind
    with db.transaction(D) as c:
        db.insert(c, "messages", {"message_id": "M999", "post_id": "L001", "author": "T2S-B001",
                                  "kind": "comment", "text": "half-saved", "posted_at": "2026-10-22 09:00"})
        raise RuntimeError("something went wrong after the first insert")
except RuntimeError:
    pass
assert len(impact.load_data(D)["messages"]) == before
new_buyer = impact.save_buyer_choices("C3R", {"KIT-CAB": "opt_out"}, D)   # a new buyer becomes a person too
p = impact.load_data(D)["people"].set_index("person_id")
assert p.role[new_buyer] == "buyer" and p.unit_type[new_buyer] == "C3R"
import generate_dummy_data
real_dir, counts = generate_dummy_data.DATA, {t: len(df) for t, df in impact.load_data(D).items()}
generate_dummy_data.DATA = D           # refreshing the fitting figures keeps every report, choice and post
try:
    generate_dummy_data.write_fittings(); generate_dummy_data.write_upgrades()
finally:
    generate_dummy_data.DATA = real_dir
assert {t: len(df) for t, df in impact.load_data(D).items()} == counts
out = db.export_csv(D)                 # CSV copies of every table, for Excel
assert sorted(f.stem for f in out.glob("*.csv")) == sorted(db.TABLES)
assert open(out / "choices.csv", encoding="utf-8").readline().strip() == "buyer_id,unit_type,fitting_id,choice,upgrade_id"
shutil.rmtree(tmp)

t = impact.dashboard_totals(data, "T2S")
print("All checks passed.")
print({k: (round(v) if isinstance(v, float) else v) for k, v in t.items() if k != "reuse"})
print("reuse:", {k: round(v, 2) if isinstance(v, float) else v for k, v in t["reuse"].items()})
