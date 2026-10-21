"""
Generate the SIMULATED data for the Right-Fit Homes demo.

The owners, buyers, rip-out rates and Neighbour Match listings are made up.
The fittings' weights, carbon factors and prices are realistic estimates from
the public sources listed above FITTINGS, with the working beside each row.
Re-run any time:

    python generate_dummy_data.py

It writes seven CSV files into data/. Column meanings are in README.md.
The random seed is fixed, so the same data comes out every run: that is
what the dashboard's "Reset demo data" button (POST /api/reset-demo) does.
Only the Neighbour Match dates move: they count back from the hour you run
it, so the community feed always looks recent in a demo.
To refresh only the fittings and upgrade options (keeping rip-out reports
and buyer choices added through the app):

    python -c "import generate_dummy_data as g; g.write_fittings(); g.write_upgrades()"
"""

import csv
import random
from datetime import datetime, timedelta
from pathlib import Path

import impact
import neighbour_match

SEED = 42
DATA = Path(__file__).parent / "data"
DATA.mkdir(exist_ok=True)

UNIT_TYPES = {
    "T2S": "Double-storey terrace 20' x 70'",
    "C3R": "3-room condominium",
}

# ---- Where the fitting numbers come from (README.md lists these too) ---------
# [1] ICE Database v4, Circular Ecology (2024), cradle to gate, as listed on
#     Climatiq (the ICE spreadsheet itself needs a free sign-up at
#     https://circularecology.com). kg CO2e per kg:
#       particle board 0.664 (excluding stored carbon)   ceramic tile 0.796
#       sanitary ceramic 1.93   glass 1.437   aluminium (world average) 13.06
#     e.g. https://www.climatiq.io/data/emission-factor/ca3be708-df0d-47a2-9e51-43cf139ebfd8 (tile)
#          https://www.climatiq.io/data/emission-factor/218eace7-6add-4bcf-b571-b464ac924dfd (sanitary)
# [2] No open ICE or EPD factor for acrylic solid surface, so a stand-in: DuPont
#     quartz worktop EPD (UL Environment, 2017), 42.4 kg CO2e/m2 at 61 kg/m2
#     = 0.70 kg CO2e/kg. Acrylic is likely higher, so this undercounts (on purpose:
#     we'd rather understate carbon).
#     https://materials.oneclicklca.com/en/material/quartz-countertop/66475d82e18244544f8d7be7
# [3] recommend.my, "Types of kitchen cabinet materials in Malaysia", 29 Sep 2024:
#     melamine (chipboard) from RM220/ft run wall, RM280/ft run base cabinets.
#     https://recommend.my/blog/?p=9822
# [4] recommend.my, "A Basic Guide on Solid Surface Countertops", 29 Sep 2024:
#     solid surface RM135-245/ft run. https://recommend.my/blog/?p=8605
# [5] recommend.my, "11 Custom Made Melamine Wardrobes for under RM4000",
#     29 Sep 2024: 2400 x 600 x 2700 mm melamine wardrobe from RM3,840.
#     https://recommend.my/blog/?p=18334
# [6] Qanvast, "How Much Does It Cost To Renovate In Malaysia?", 8 Dec 2025:
#     tiles RM15-24/sqft installed, hacking RM3-6/sqft, pendant light from RM80,
#     toilet bowl RM250-400, sink and tap RM150-300.
#     https://qanvast.com/my/articles/how-much-does-it-cost-to-renovate-in-malaysia-928
# SDP's prices use the LOW end of each range: SDP buys in bulk, so likely pays less.
# Tile hacking is a removal cost the owner pays, with no bulk discount, so it
# uses RM4/sqft, inside the RM3-6 range [6].
# Weights are our estimates: 18 mm particleboard at ~650 kg/m3 (11.7 kg/m2,
# so a 600 mm base unit ~22 kg, a wall unit ~18 kg); 9 mm porcelain tile
# ~21 kg/m2; 12 mm solid surface at ~1,700 kg/m3 + 10% for edges; a toilet
# ~30 kg, a basin ~15 kg, a pendant ~2.5 kg. Removal costs are our
# assumptions (labour + a disposal trip) except tiles, from the hacking rate [6].
CREDIT_SHARE = 0.70   # assumption: SDP gives a buyer who opts out 70% of the install cost it saves
MARGIN_SHARE = 0.20   # assumption: SDP's margin on the default upgrade = 20% of the standard item's install cost

# One row per fitting per unit type.
# eligibility: opt_out = buyer can keep / opt out / upgrade
#              upgrade_only = buyer can keep / upgrade (e.g. tiles)
#              fixed = always installed (needed for handover)
# credit_rm and upgrade_margin_rm are worked out from the shares above (fitting_rows()).
FITTINGS = [
    # unit, id,       name,                         eligibility,   material,         kg,    factor, install, removal
    # 10 base units x 22 kg + 6 wall units x 18 kg; 20 ft base x RM280 + 12 ft wall x RM220 [3]
    ("T2S", "KIT-CAB", "Kitchen cabinets",           "opt_out",      "Particleboard",   330,  0.664,  8240,  500),
    # 20 ft x 0.6 m of 12 mm solid surface; 20 ft x RM135 [4]; factor [2]
    ("T2S", "KIT-TOP", "Kitchen top",                "opt_out",      "Solid surface",    82,  0.70,   2700,  200),
    # 2.4 m full-height, ~19 m2 of board; RM3,840 [5]
    ("T2S", "WRD-MST", "Master bedroom wardrobe",    "opt_out",      "Particleboard",   225,  0.664,  3840,  300),
    # 1.8 m, ~14.6 m2 of board; RM3,840 x 1.8 / 2.4 [5]
    ("T2S", "WRD-BR2", "Bedroom 2 wardrobe",         "opt_out",      "Particleboard",   170,  0.664,  2880,  250),
    # 6 pendants x 2.5 kg; factor = half aluminium, half glass [1]; 6 x RM80 [6]
    ("T2S", "LGT-DEC", "Decorative light fittings",  "opt_out",      "Aluminium and glass", 15, 7.25,  480,  120),
    # 86 m2 ground floor (926 sqft) x 21 kg/m2; factor [1]; 926 sqft x RM15 installed, hacking 926 x RM4 [6]
    ("T2S", "TIL-FLR", "Ground-floor tiles",         "upgrade_only", "Ceramic tile",   1800,  0.796, 13890, 3700),
    # 3 bathrooms: 3 x (30 + 15 kg); factor [1]; 3 x RM250 toilet + 3 x RM150 basin [6]
    ("T2S", "SAN-BTH", "Basins and toilets",         "fixed",        "Vitreous china",  135,  1.93,   1200,  300),
    # 8 base units x 22 kg + 5 wall units x 18 kg; 16 ft base x RM280 + 9 ft wall x RM220 [3]
    ("C3R", "KIT-CAB", "Kitchen cabinets",           "opt_out",      "Particleboard",   265,  0.664,  6460,  400),
    # 16 ft x 0.6 m of 12 mm solid surface; 16 ft x RM135 [4]; factor [2]
    ("C3R", "KIT-TOP", "Kitchen top",                "opt_out",      "Solid surface",    66,  0.70,   2160,  150),
    # the same 2.4 m full-height wardrobe as T2S: ~19 m2 of board; RM3,840 [5]
    ("C3R", "WRD-MST", "Master bedroom wardrobe",    "opt_out",      "Particleboard",   225,  0.664,  3840,  300),
    # 4 pendants x 2.5 kg; factor as T2S [1]; 4 x RM80 [6]
    ("C3R", "LGT-DEC", "Decorative light fittings",  "opt_out",      "Aluminium and glass", 10, 7.25,  320,   80),
    # 34 m2 living/dining/kitchen (366 sqft) x 21 kg/m2; factor [1]; 366 x RM15, hacking 366 x RM4 [6]
    ("C3R", "TIL-FLR", "Living-room tiles",          "upgrade_only", "Ceramic tile",    715,  0.796,  5490, 1460),
    # 2 bathrooms: 2 x (30 + 15 kg); factor [1]; 2 x RM250 + 2 x RM150 [6]
    ("C3R", "SAN-BTH", "Basins and toilets",         "fixed",        "Vitreous china",   90,  1.93,    800,  200),
]


def fitting_rows():
    """FITTINGS plus credit_rm and upgrade_margin_rm, as written to fittings.csv."""
    rows = []
    for unit, fid, name, elig, material, kg, factor, install, removal in FITTINGS:
        credit = round(install * CREDIT_SHARE, -1) if elig == "opt_out" else 0
        margin = round(install * MARGIN_SHARE, -1) if elig != "fixed" else 0
        rows.append((unit, fid, name, elig, material, kg, factor, install, removal, int(credit), int(margin)))
    return rows


# What a buyer can upgrade each fitting to: (upgrade_id, name, description,
# SDP margin as a multiple of the fitting's upgrade_margin_rm). The first
# option is the default and matches upgrade_margin_rm. The multiples are
# assumptions: a pricier option (aluminium, sintered stone) earns SDP more.
# Each option's picture is static/upgrades/<upgrade_id in lower case>.svg
# (drawn illustrations); point the image column at a real photo to swap one.
UPGRADES = {
    "KIT-CAB": [("PLYWOOD", "Plywood cabinets", "Moisture-resistant plywood, soft-close doors", 1.0),
                ("ALUMINIUM", "Aluminium cabinets", "Waterproof and termite-proof", 1.3)],
    "KIT-TOP": [("QUARTZ", "Quartz top", "20 mm quartz with an undermount sink", 1.0),
                ("GRANITE", "Granite top", "Polished natural granite", 0.8),
                ("SINTERED", "Sintered stone top", "Heat- and scratch-proof, slim edge", 1.5)],
    "WRD-MST": [("SLIDING", "Full-height sliding wardrobe", "Floor to ceiling, mirrored sliding doors", 1.0),
                ("WALK-IN", "Open walk-in system", "Open shelves, drawers and hanging rails", 1.2)],
    "WRD-BR2": [("SLIDING", "Full-height sliding wardrobe", "Floor to ceiling, mirrored sliding doors", 1.0),
                ("STUDY", "Wardrobe with study desk", "Smaller wardrobe plus a built-in desk", 1.1)],
    "LGT-DEC": [("LED-WARM", "Warm-white LED downlights", "Recessed and energy-saving", 1.0),
                ("SMART", "Smart dimmable lights", "Dim from the app or the switch", 1.6)],
    "TIL-FLR": [("HOMOGENEOUS", "Large homogeneous tiles", "600 x 1200 mm polished porcelain", 1.0),
                ("VINYL", "SPC vinyl plank", "Wood look, waterproof, warmer underfoot", 0.9)],
}

# Simulated share of owners who rip each fitting out after handover.
RIPOUT_RATE = {
    ("T2S", "KIT-CAB"): 0.62, ("T2S", "KIT-TOP"): 0.55, ("T2S", "WRD-MST"): 0.46,
    ("T2S", "WRD-BR2"): 0.31, ("T2S", "LGT-DEC"): 0.40, ("T2S", "TIL-FLR"): 0.22,
    ("T2S", "SAN-BTH"): 0.08,
    ("C3R", "KIT-CAB"): 0.38, ("C3R", "KIT-TOP"): 0.35, ("C3R", "WRD-MST"): 0.52,
    ("C3R", "LGT-DEC"): 0.27, ("C3R", "TIL-FLR"): 0.12, ("C3R", "SAN-BTH"): 0.05,
}

# Messy free-text notes, the kind owners actually write.
# Member 3's AI tagging should turn these back into the fitting_id.
NOTES = {
    "KIT-CAB": ["hacked out all kitchen cabinet, redo full kitchen",
                "kabinet dapur tukar baru", "changed kitchen cabinets to aluminium",
                "removed upper and lower cabinets, contractor install new"],
    "KIT-TOP": ["kitchen top change to quartz", "hacked out kitchen top",
                "replace worktop with granite", "tukar kitchen top"],
    "WRD-MST": ["master room wardrobe removed, built in new one",
                "change wardrobe in master bedroom", "almari master bilik buang"],
    "WRD-BR2": ["small room wardrobe remove", "bedroom 2 almari tukar",
                "removed wardrobe in 2nd room for study table"],
    "LGT-DEC": ["changed all lights to LED downlight", "lampu tukar semua",
                "remove ceiling lights install new"],
    "TIL-FLR": ["retile ground floor", "change floor tiles to vinyl",
                "hack floor tiles downstairs, new homogeneous tiles"],
    "SAN-BTH": ["changed toilet bowl", "replace basin in common bathroom"],
}

# Neighbour Match posts: what owners write when they offer a fitting, and what
# neighbours write when they ask. Simulated, in the same English/Malay mix.
OFFER_NOTES = {
    "KIT-CAB": ["Base and wall units, white melamine. All doors and hinges included. We went for an island kitchen.",
                "Kabinet dapur masih elok, cuma tukar konsep. Ambil sendiri ya.",
                "Two years old, no water damage under the sink. Free to a neighbour with the same layout!",
                "Taken down carefully and numbered, so it goes back up easily."],
    "KIT-TOP": ["Solid-surface top in one piece, with the sink cut-out. A few light scratches.",
                "We changed to granite. This top is still in good shape.",
                "Top kabinet dapur, warna putih. Perlu 2 orang untuk angkat."],
    "WRD-MST": ["Full-height master wardrobe, taken apart neatly. Shelves and rails included.",
                "Almari bilik utama, masih cantik. Kami pasang walk-in.",
                "Doors work fine, one handle missing. Fits the standard master bedroom wall."],
    "WRD-BR2": ["Bedroom 2 wardrobe, light oak finish. Used by our kid for a year.",
                "Turned bedroom 2 into a study, so this has to go. Good condition.",
                "Almari bilik kedua, tak pernah rosak. Free!"],
    "LGT-DEC": ["The standard pendant lights, bulbs included.",
                "Changed to downlights. All the pendants work, boxed up.",
                "Lampu hiasan, semua berfungsi. Ambil semua sekali."],
}
ASK_NOTES = {
    "KIT-CAB": ["Moving in next month and would love a ready kitchen.",
                "Looking for kitchen cabinets, happy to collect and refit myself."],
    "KIT-TOP": ["Looking for a worktop to go with second-hand cabinets.",
                "Need a top for our kitchen, any colour is fine."],
    "WRD-MST": ["Need a wardrobe for the master bedroom before we move in.",
                "Ada sesiapa nak bagi almari bilik utama? Boleh ambil sendiri."],
    "WRD-BR2": ["Looking for a wardrobe for our son's room.",
                "Need one for bedroom 2, the standard size."],
    "LGT-DEC": ["Any spare pendant lights? Two of ours broke in the move.",
                "Looking for the original pendants to match the rest of the house."],
}
CONDITION_WEIGHTS = {"Like new": 3, "Good": 5, "Fair": 2}
# (neighbour taking it, giver) before the pickup
PICKUP_CHAT = [("Is it still available? Can I collect this weekend?", "Yes! Saturday morning works, text me when you're here."),
               ("Thank you! What time is good for pickup?", "Any evening after 7pm. I'll leave it at the porch."),
               ("Boleh saya ambil hari Sabtu?", "Boleh, datang pukul 10 pagi ya."),
               ("Does it come with the screws and hinges?", "Yes, all in a bag taped to the back.")]
# (a neighbour asking about a waiting offer, the giver's answer)
QUESTIONS = [("Is it the white or the grey finish?", "White, same as the show unit."),
             ("Any damage on the doors?", "Just a small scratch on one door, hardly visible."),
             ("Still there? I might need one next month.", "Still here! Ask for it when you're ready.")]
REQUEST_REPLIES = ["I'm renovating in December, I'll post mine then!",
                   "Same here, following this one.",
                   "Ours comes out next month, will offer it here."]
THANKS = ["Fits perfectly, thank you so much!", "Terima kasih! Dah pasang, macam baru.",
          "Saved us weeks of waiting for a carpenter. Thanks, neighbour!", "Installed it the same day. Thank you!"]
STAMP = "%Y-%m-%d %H:%M"


def write(name, header, rows):
    with open(DATA / name, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def write_upgrades():
    """upgrades.csv: one row per upgrade option per fitting per unit type.
    On its own (python -c "import generate_dummy_data as g; g.write_upgrades()")
    it refreshes the options without resetting the rest of the data."""
    upgrades = [(unit, fid, uid, name, desc, round(margin * mult / 10) * 10, f"upgrades/{uid.lower()}.svg")
                for unit, fid, *_, margin in fitting_rows()
                for uid, name, desc, mult in UPGRADES.get(fid, [])]
    write("upgrades.csv",
          ["unit_type", "fitting_id", "upgrade_id", "name", "description", "margin_rm", "image"], upgrades)
    return upgrades


def write_fittings():
    """fittings.csv. On its own (see the module docstring) it refreshes the
    numbers without resetting the rest of the data."""
    write("fittings.csv",
          ["unit_type", "fitting_id", "name", "eligibility", "material",
           "weight_kg", "carbon_factor", "install_cost_rm",
           "removal_cost_rm", "credit_rm", "upgrade_margin_rm"],
          fitting_rows())


@impact.locked   # a reset from the dashboard waits for any save in progress, and pages wait for it
def main():
    random.seed(SEED)   # every run, so a reset always gives the same demo data
    write_fittings()
    upgrades = write_upgrades()

    # ripouts.csv: one row per owner per fitting.
    ripouts = []
    for unit, owners in (("T2S", 150), ("C3R", 100)):
        unit_fittings = [f[1] for f in FITTINGS if f[0] == unit]
        for n in range(1, owners + 1):
            owner = f"{unit}-O{n:03d}"
            for fid in unit_fittings:
                removed = random.random() < RIPOUT_RATE[(unit, fid)]
                note = random.choice(NOTES[fid]) if removed else ""
                ripouts.append((owner, unit, fid, int(removed), note))
    write("ripouts.csv",
          ["owner_id", "unit_type", "fitting_id", "removed", "note"], ripouts)

    # choices.csv: what NEW buyers pick in the Fit-Out Advisor.
    # Assumption: buyers who would have ripped an item out mostly act on it.
    # Upgrade picks use their own random stream, so the rest of the data
    # comes out the same as before upgrade options existed.
    pick_upgrade = random.Random(7)
    choices = []
    for unit, buyers in (("T2S", 100), ("C3R", 60)):
        eligible = [f for f in FITTINGS if f[0] == unit and f[3] != "fixed"]
        for n in range(1, buyers + 1):
            buyer = f"{unit}-B{n:03d}"
            for f in eligible:
                fid, elig = f[1], f[3]
                upgrade_id = ""
                if random.random() < RIPOUT_RATE[(unit, fid)] * 0.8:
                    if elig == "upgrade_only" or random.random() < 0.4:
                        choice = "upgrade"
                        upgrade_id = pick_upgrade.choice(UPGRADES[fid])[0]
                    else:
                        choice = "opt_out"
                else:
                    choice = "keep"
                choices.append((buyer, unit, fid, choice, upgrade_id))
    write("choices.csv",
          ["buyer_id", "unit_type", "fitting_id", "choice", "upgrade_id"], choices)

    # matches.csv + requests.csv + messages.csv: Neighbour Match. Owners offer
    # reusable fittings they removed and buyers of the same home type ask for
    # them, in a random order over six weeks, and each goes through the app's own
    # functions (neighbour_match.py), so the starting data follows exactly the
    # rules the live app uses. Most matched fittings have been collected; some
    # posts have a chat, and some pick-ups a thank-you.
    write("matches.csv", ["listing_id", "from_owner", "unit_type", "fitting_id", "to_owner", "distance_km",
                          "status", "condition", "note", "posted_at", "matched_at", "collected_at"], [])
    write("requests.csv", ["request_id", "requester", "unit_type", "fitting_id", "status", "listing_id",
                           "note", "posted_at"], [])
    write("messages.csv", ["message_id", "post_id", "author", "kind", "text", "posted_at"], [])
    reusable_removed = [(o, u, f) for o, u, f, removed, _ in ripouts if removed and f not in impact.NOT_REUSABLE]
    events = [("list", *row) for row in random.sample(reusable_removed, 40)]
    for unit, buyers, asks in (("T2S", 100, 20), ("C3R", 60, 12)):
        reusable = [f[1] for f in FITTINGS if f[0] == unit and f[1] not in impact.NOT_REUSABLE]
        events += [("ask", f"{unit}-B{random.randint(1, buyers):03d}", unit, random.choice(reusable))
                   for _ in range(asks)]
    random.shuffle(events)
    end = datetime.now().replace(minute=0, second=0, microsecond=0) - timedelta(hours=2)
    step = timedelta(days=42) / len(events)

    def at(t):
        return t.strftime(STAMP)

    def talk(post, who, text, t):   # a message, if its time has come
        if t < end:
            neighbour_match.comment(post, who, text, now=at(t))

    matched = []
    for i, (kind, person, unit, fid) in enumerate(events):
        when = end - timedelta(days=42) + step * i + timedelta(minutes=random.randint(0, 240))
        if kind == "list":
            condition = random.choices(list(CONDITION_WEIGHTS), list(CONDITION_WEIGHTS.values()))[0]
            listing = neighbour_match.list_item(unit, person, fid, condition=condition,
                                                note=random.choice(OFFER_NOTES[fid]), now=at(when))
        else:
            try:
                listing = neighbour_match.request_item(unit, person, fid, note=random.choice(ASK_NOTES[fid]),
                                                       now=at(when))[1]
            except ValueError:   # this buyer already asked for one
                continue
        if listing and listing["status"] == "matched":
            matched.append((listing, when))
    for listing, when in matched:
        pickup = when + timedelta(hours=random.randint(12, 96))
        if random.random() < 0.6:
            ask, answer = random.choice(PICKUP_CHAT)
            talk(listing["listing_id"], listing["to_owner"], ask, when + timedelta(hours=2))
            talk(listing["listing_id"], listing["from_owner"], answer, when + timedelta(hours=5))
        if pickup < end and random.random() < 0.75:
            thanks = random.choice(THANKS) if random.random() < 0.7 else ""
            neighbour_match.collect(listing["listing_id"], by=listing["to_owner"], thanks=thanks, now=at(pickup))
    data = impact.load_data()
    m, req = data["matches"], data["requests"]
    for r in m[m.status == "unmatched"].itertuples():   # questions on offers still waiting
        if random.random() < 0.4:
            asker = f"{r.unit_type}-B{random.randint(1, 100 if r.unit_type == 'T2S' else 60):03d}"
            ask, answer = random.choice(QUESTIONS)
            posted = datetime.strptime(r.posted_at, STAMP)
            talk(r.listing_id, asker, ask, posted + timedelta(hours=random.randint(3, 30)))
            talk(r.listing_id, r.from_owner, answer, posted + timedelta(hours=random.randint(31, 40)))
    for r in req[req.status == "open"].itertuples():    # owners answering open requests
        if random.random() < 0.5:
            owner = f"{r.unit_type}-O{random.randint(1, 150 if r.unit_type == 'T2S' else 100):03d}"
            talk(r.request_id, owner, random.choice(REQUEST_REPLIES),
                 datetime.strptime(r.posted_at, STAMP) + timedelta(hours=random.randint(2, 48)))
    data = impact.load_data()

    print(f"Wrote {len(FITTINGS)} fittings, {len(upgrades)} upgrade options, {len(ripouts)} rip-out rows, "
          f"{len(choices)} choices, {len(data['matches'])} listings, {len(data['requests'])} requests, "
          f"{len(data['messages'])} messages to {DATA}/")


if __name__ == "__main__":
    main()
