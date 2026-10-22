"""
test_buyer.py - checks for the buyer screens on the Advisor page (/advisor) (Member 2).

Run:   python test_buyer.py      (prints "All buyer checks passed.")

Reads pages and the buyer API; the one save (asking a neighbour) runs on a
temporary copy of data/, so the real files never change. The live sums, the
loading state and the "Find one from a neighbour" panel run in the browser:
check those by clicking through /advisor. The maths is checked in test_impact.py.
"""

import re
import shutil
import tempfile
from pathlib import Path

import buyer
import community
import impact
import neighbour_match
from app import app

web = app.test_client()
data = impact.load_data()
F = data["fittings"]
TAGS = {"opt_out": "Can opt out", "upgrade_only": "Upgrade only"}
placeholders = []

for unit in ("T2S", "C3R"):
    res = web.get(f"/advisor?unit={unit}")
    assert res.status_code == 200, (unit, res.status_code)
    page = res.data.decode()
    fits = F[F.unit_type == unit]
    rates = dict(zip(*[impact.ripout_index(data, unit)[k] for k in ("fitting_id", "rate")]))

    # rip-out chart: every fitting once, most removed first, bar width = share removed, no advice colours
    chart = page.split('class="ripout-bars"')[1].split("</ol>")[0]
    rows = re.findall(r'data-fid="([^"]+)".*?width: (\d+)%', chart, re.S)
    assert sorted(fid for fid, _ in rows) == sorted(fits.fitting_id), (unit, rows)
    assert [rates[fid] for fid, _ in rows] == sorted(rates.values(), reverse=True), (unit, rows)
    for fid, width in rows:
        assert width == "{:.0f}".format(rates[fid] * 100), (unit, fid, width)
    assert "--advice" not in chart, unit

    # each card: its group tag, and only the options its group allows; fixed fittings get no card
    for f in fits.itertuples():
        card = re.search(rf'<fieldset class="choice" data-fid="{f.fitting_id}">(.*?)</legend>', page, re.S)
        options = set(re.findall(rf'name="c-{f.fitting_id}" value="(\w+)"', page))
        if f.eligibility == "fixed":
            assert card is None and not options, (unit, f.fitting_id)
            continue
        assert card and f'<span class="group-tag">{TAGS[f.eligibility]}</span>' in card.group(1), (unit, f.fitting_id)
        allowed = {"keep", "opt_out", "upgrade"} if f.eligibility == "opt_out" else {"keep", "upgrade"}
        assert options == allowed, (unit, f.fitting_id, options)

    # always installed: the fixed fittings plus wiring and plumbing, with nothing to choose
    fixed = page.split('id="fixed-title"')[1].split("</section>")[0]
    for name in [*fits.name[fits.eligibility == "fixed"], "Essential wiring", "Essential plumbing"]:
        assert f"<li>{name}</li>" in fixed, (unit, name)
    assert "<input" not in fixed, unit

    # not sure yet: each item tagged "To be confirmed with SDP", with nothing to choose
    tbc = page.split('id="tbc-title"')[1].split("</section>")[0]
    assert "<input" not in tbc, unit
    items = re.findall(r"<li>(.*?)<span", tbc)
    assert tbc.count("To be confirmed with SDP</span>") == len(items), (unit, items)
    placeholders += [i for i in items if "Placeholder" in i and i not in placeholders]

    # the impact summary: both savings, the agreed label, and a line for the sum behind each total
    assert "back in your pocket" in page and "Installation saved, after credits" in page, unit
    assert "SDP margin on upgrades" in page and ">Margin on upgrades<" not in page, unit
    for total in ("total", "credit", "ripout", "material", "carbon", "sdp", "margin"):
        assert f'id="calc-{total}"' in page, (unit, total)

# the hand-off after Confirm opens Neighbour Match as the buyer, on the Ask tab:
# &as= for a buyer who isn't signed in, the plain page for one who is
first_buyer = min(data["choices"].buyer_id[data["choices"].unit_type == "T2S"])
page = web.get(f"/match?unit=T2S&as={first_buyer}").data.decode()
assert community.person(first_buyer)["name"] in page, first_buyer
assert 'id="tab-ask" aria-controls="ask-form" aria-selected="true"' in page, first_buyer
web.post("/signin", data={"who": first_buyer})
page = web.get("/match?unit=T2S").data.decode()
assert "Signed in as" in page and community.person(first_buyer)["name"] in page, first_buyer
web.post("/signout")

# /api/buyer/nearby: the nearest offer shown is the one "Ask for one" gets matched to
m, req = data["matches"], data["requests"]
waiting = m[(m.unit_type == "T2S") & (m.status == "unmatched")]
assert not waiting.empty, "the demo data should have offers waiting on Neighbour Match"
fid = waiting.fitting_id.mode()[0]   # the fitting with the most offers waiting
buyers = sorted(set(data["choices"].buyer_id[data["choices"].unit_type == "T2S"]))
asker = next(b for b in buyers if not ((req.requester == b) & (req.fitting_id == fid) & (req.status == "open")).any())
res = web.get(f"/api/buyer/nearby?unit=T2S&buyer={asker}&fittings={fid}")
assert res.status_code == 200, res.json
got = res.json["fittings"][0]
assert got["available"] == (waiting.fitting_id == fid).sum() and got["nearest"] and not got["asking"], got
tmp = Path(tempfile.mkdtemp())
try:
    shutil.copytree(impact.DATA_DIR, tmp / "data")
    _, listing = neighbour_match.request_item("T2S", asker, fid, data_dir=tmp / "data")
    assert listing and listing["listing_id"] == got["nearest"]["listing_id"], (listing, got)
    assert listing["distance_km"] == got["nearest"]["distance_km"], (listing, got)
    # once matched, that offer shows as reserved for them, so the panel doesn't offer them another
    again = buyer.nearby(impact.load_data(tmp / "data"), "T2S", asker, [fid])[0]
    assert again["reserved"]["listing_id"] == listing["listing_id"] and again["reserved"]["status"] == "matched", again
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# a buyer with an open request is told they're already asking (posting again would be refused)
open_asks = req[(req.unit_type == "T2S") & (req.status == "open") & req.requester.str.startswith("T2S-B")]
if not open_asks.empty:
    r = open_asks.iloc[0]
    assert web.get(f"/api/buyer/nearby?unit=T2S&buyer={r.requester}&fittings={r.fitting_id}").json["fittings"][0]["asking"]

# bad input is a 400 with a reason: unknown home type, an owner (not a buyer), tiles (can't be rehomed),
# an unknown fitting, a buyer from the other home type
owner = min(data["ripouts"].owner_id[data["ripouts"].unit_type == "T2S"])
for query in (f"unit=XYZ&buyer={asker}&fittings={fid}", f"unit=T2S&buyer={owner}&fittings={fid}",
              f"unit=T2S&buyer={asker}&fittings=TIL-FLR", f"unit=T2S&buyer={asker}&fittings=NOPE",
              f"unit=C3R&buyer={asker}&fittings={fid}"):
    res = web.get(f"/api/buyer/nearby?{query}")
    assert res.status_code == 400 and res.json["error"], (query, res.status_code)

if placeholders:
    print(f"Reminder: replace the placeholders in the 'Not sure yet' list before the demo "
          f"(to_confirm in templates/advisor.html): {', '.join(placeholders)}")
print("All buyer checks passed.")
