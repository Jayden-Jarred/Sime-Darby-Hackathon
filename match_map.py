"""
match_map.py - lay out the Neighbour Match listings on a fictional township map.

The map is a simple site plan in an SVG coordinate space (1000 x 620,
200 units = 1 km). Each listing's two homes are placed so the drawn distance
roughly matches distance_km in matches.csv. Positions are illustrative,
not real addresses.
"""

import hashlib
import math

import impact

PX_PER_KM = 200
TERRACE_ROWS = [92 + 44 * i for i in range(11)]           # y of each terrace row
CROSS_STREETS = [(226, 246), (402, 422), (578, 598)]      # x gaps in the rows
TOWERS = [(790, 130), (880, 130), (790, 250), (880, 250), (790, 370), (880, 370)]


def _h(s):
    return int(hashlib.md5(s.encode()).hexdigest(), 16)


def _terrace_slots():
    slots = []
    for y in TERRACE_ROWS:
        for x in range(80, 700, 9):
            if not any(a <= x <= b for a, b in CROSS_STREETS):
                slots.append((x, y))
    return slots


SLOTS = _terrace_slots()


def _place(owner, unit_type):
    if unit_type == "C3R":
        x, y = TOWERS[_h(owner) % len(TOWERS)]
        return x + 15, y + 15
    return SLOTS[_h(owner) % len(SLOTS)]


def _nearest_at(origin, km, unit_type, seed):
    """The home whose distance from origin is closest to km (ties broken by seed)."""
    target = km * PX_PER_KM
    pool = [(x + 15, y + 15) for x, y in TOWERS] if unit_type == "C3R" else SLOTS
    best = min(pool, key=lambda p: (abs(math.dist(origin, p) - target), (_h(seed + str(p)) % 997)))
    if best == origin and unit_type == "C3R":   # same tower: offset so the path is visible
        best = (origin[0] + 0.01, origin[1])
    return best


def listings(data, unit_type):
    """Every listing for this unit type, with map positions and its impact."""
    m = data["matches"][data["matches"].unit_type == unit_type]
    f = data["fittings"][data["fittings"].unit_type == unit_type].set_index("fitting_id")
    out = []
    for r in m.to_dict("records"):
        fit = f.loc[r["fitting_id"]]
        src = _place(r["from_owner"], unit_type)
        has_to = isinstance(r["to_owner"], str) and r["to_owner"]
        km = float(r["distance_km"]) if has_to else None
        dst = _nearest_at(src, km, unit_type, r["listing_id"]) if has_to else None
        saved = impact.reuse_carbon_kg(float(fit.weight_kg), float(fit.carbon_factor), km or 0)
        out.append({
            "id": r["listing_id"], "fitting_id": r["fitting_id"], "name": fit["name"],
            "from_owner": r["from_owner"], "to_owner": r["to_owner"] if has_to else None,
            "status": r["status"], "km": km,
            "from": [round(src[0], 1), round(src[1], 1)],
            "to": [round(dst[0], 1), round(dst[1], 1)] if dst else None,
            "weight_kg": float(fit.weight_kg),
            "carbon_saved_kg": round(saved, 1) if r["status"] == "collected" else 0.0,
        })
    order = {"collected": 0, "matched": 1, "unmatched": 2}
    out.sort(key=lambda x: (order[x["status"]], x["km"] or 99))
    return out


def map_layout(unit_type):
    """Static features for drawing the township."""
    return {
        "rows": TERRACE_ROWS, "cross": CROSS_STREETS, "towers": TOWERS,
        "active": "towers" if unit_type == "C3R" else "terrace",
    }
