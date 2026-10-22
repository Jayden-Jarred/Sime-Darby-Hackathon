"""
match_map.py - where every home sits on the Neighbour Match township map.

The map is a simple site plan in an SVG coordinate space (1000 x 620,
200 units = 1 km). Each owner or buyer gets a fixed home from their id
number, no two the same: a terrace slot for T2S ("No. 14, Jalan Harmoni 3"),
a flat in one of six towers for C3R ("Tower B, #12-03"). Distances between
two homes are measured on this map, so the drawn routes and the distance_km
stored in the matches table always agree. The township and its addresses are
fictional.

It also builds what the map draws: listings() gives every offer with its route
and impact, and asks() gives the open requests and where the asker lives.
"""

import hashlib
import math

import impact

PX_PER_KM = 200
TERRACE_ROWS = [92 + 44 * i for i in range(11)]           # y of each terrace row
CROSS_STREETS = [(226, 246), (402, 422), (578, 598)]      # x gaps in the rows
TOWERS = [(790, 130), (880, 130), (790, 250), (880, 250), (790, 370), (880, 370)]
TOWER_CENTRE = 15                                         # towers are 30 x 30


def _hash(s):
    return int(hashlib.md5(s.encode()).hexdigest(), 16)


def _terrace_slots():
    slots = []
    for y in TERRACE_ROWS:
        for x in range(80, 700, 9):
            if not any(a <= x <= b for a, b in CROSS_STREETS):
                slots.append((x, y))
    return slots


SLOTS = _terrace_slots()
STRIDE = 263          # a prime that shares no factor with len(SLOTS): spreads homes across the map
BUYER_OFFSET = len(SLOTS) // 2


def home_number(person):
    """
    A person's home index: owner T2S-O001 -> 0, buyer T2S-B001 -> BUYER_OFFSET.
    Unique while the id number is at most BUYER_OFFSET (341 for T2S); any
    other id falls back to a hash, so it still gets a home.
    """
    m = impact.PERSON_ID.fullmatch(person or "")
    if not m or not 0 < int(m[3]) <= BUYER_OFFSET:
        return _hash(person or "")
    return int(m[3]) - 1 + (BUYER_OFFSET if m[2] == "B" else 0)


def _terrace_slot(person):
    return (home_number(person) * STRIDE) % len(SLOTS)


def position(person, unit_type):
    """Map position (x, y) of an owner's or buyer's home."""
    if unit_type == "C3R":
        x, y = TOWERS[home_number(person) % len(TOWERS)]
        return x + TOWER_CENTRE, y + TOWER_CENTRE
    return SLOTS[_terrace_slot(person)]


def address(person, unit_type):
    """A fictional address: "No. 14, Jalan Harmoni 3" or "Tower B, #12-03"."""
    n = home_number(person)
    if unit_type == "C3R":
        rest = n // len(TOWERS)
        return f"Tower {'ABCDEF'[n % len(TOWERS)]}, #{2 + rest % 30:02d}-{1 + rest // 30:02d}"
    x, y = SLOTS[_terrace_slot(person)]
    house = sum(1 for sx, sy in SLOTS if sy == y and sx < x) + 1
    return f"No. {house}, Jalan Harmoni {TERRACE_ROWS.index(y) + 1}"


def distance_km(a, b, unit_type):
    """Map distance between two homes, in km. At least 0.1 (another flat in the same tower)."""
    return max(0.1, round(math.dist(position(a, unit_type), position(b, unit_type)) / PX_PER_KM, 1))


def listings(data, unit_type):
    """Every listing for this unit type, with map positions and its impact."""
    m = data["matches"][data["matches"].unit_type == unit_type]
    f = impact.unit_fittings(data, unit_type)
    out = []
    for r in m.to_dict("records"):
        fit = f.loc[r["fitting_id"]]
        src = position(r["from_owner"], unit_type)
        has_to = isinstance(r["to_owner"], str) and r["to_owner"]
        km = float(r["distance_km"]) if has_to else None
        dst = position(r["to_owner"], unit_type) if has_to else None
        if dst == src:   # same tower: nudge so the route is visible
            dst = (src[0] + 12, src[1])
        out.append({
            "id": r["listing_id"], "fitting_id": r["fitting_id"], "name": fit["name"],
            "from_owner": r["from_owner"], "to_owner": r["to_owner"] if has_to else None,
            "status": r["status"], "km": km,
            "from": [round(src[0], 1), round(src[1], 1)],
            "to": [round(dst[0], 1), round(dst[1], 1)] if dst else None,
            "weight_kg": float(fit.weight_kg),
            "carbon_saved_kg": impact.rehomed_carbon_kg(fit, km) if r["status"] == "collected" else 0.0,
        })
    order = {"collected": 0, "matched": 1, "unmatched": 2}
    out.sort(key=lambda x: (order[x["status"]], x["km"] or 99))
    return out


def asks(data, unit_type):
    """Open requests (neighbours asking for a fitting), with where they live."""
    req = data["requests"]
    req = req[(req.unit_type == unit_type) & (req.status == "open")]
    names = impact.unit_fittings(data, unit_type).name
    return [{"id": r.request_id, "requester": r.requester, "fitting_id": r.fitting_id,
             "name": names[r.fitting_id], "at": list(position(r.requester, unit_type))}
            for r in req.itertuples()]


def map_layout(unit_type):
    """Static features for drawing the township: every terrace house (slots), the streets and the towers."""
    return {
        "rows": TERRACE_ROWS, "cross": CROSS_STREETS, "towers": TOWERS, "slots": SLOTS,
        "active": "towers" if unit_type == "C3R" else "terrace",
    }
