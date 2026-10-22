"""
buyer.py - the buyer screens' own API, as a Flask Blueprint (Member 2).

app.py plugs it in next to dashboard.py's:

    from buyer import buyer_bp
    app.register_blueprint(buyer_bp)

The maths and the matching stay with their owners: distances come from
match_map, carbon from impact.reuse_carbon_kg, names and homes from community.
"""

from flask import Blueprint, jsonify, request

import community
import impact
import match_map
import neighbour_match
from generate_dummy_data import UNIT_TYPES

buyer_bp = Blueprint("buyer", __name__)


def nearby(data, unit_type, buyer, fitting_ids):
    """
    For each fitting: the nearest offer waiting on Neighbour Match, how many are
    waiting, whether `buyer` already has an open request for it, and the one
    already reserved for them (or collected), if any. "Nearest" is
    the rule neighbour_match.request_item matches by (same home type and fitting,
    nearest home, then the lowest listing id), so asking gets this offer.
    Raises ValueError for someone who isn't a buyer of this home type, or a
    fitting that can't be rehomed.
    """
    if not buyer.startswith(f"{unit_type}-B") or buyer not in neighbour_match.people(data, unit_type):
        raise ValueError(f"No buyer {buyer} in {unit_type} homes")
    f = data["fittings"]
    fits = f[f.unit_type == unit_type].set_index("fitting_id")
    m, req = data["matches"], data["requests"]
    found = []
    for fid in fitting_ids:
        if fid not in fits.index or fid in impact.NOT_REUSABLE:
            raise ValueError(f"Not a fitting a neighbour can give in {unit_type} homes: {fid}")
        waiting = m[(m.unit_type == unit_type) & (m.fitting_id == fid)
                    & (m.status == "unmatched") & (m.from_owner != buyer)]
        nearest = None
        if not waiting.empty:
            best = min(waiting.itertuples(),
                       key=lambda r: (match_map.distance_km(r.from_owner, buyer, unit_type), r.listing_id))
            km = match_map.distance_km(best.from_owner, buyer, unit_type)
            giver = community.person(best.from_owner)
            nearest = {"listing_id": best.listing_id, "from_owner": best.from_owner, "name": giver["name"],
                       "home": giver["home"], "distance_km": km, "condition": best.condition, "note": best.note,
                       "carbon_saved_kg": round(float(impact.reuse_carbon_kg(
                           float(fits.weight_kg[fid]), float(fits.carbon_factor[fid]), km)), 1)}
        asking = ((req.requester == buyer) & (req.fitting_id == fid) & (req.status == "open")).any()
        taken = m[(m.unit_type == unit_type) & (m.fitting_id == fid) & (m.to_owner == buyer) & (m.status != "unmatched")]
        reserved = None
        if not taken.empty:
            t = taken.iloc[0]
            reserved = {"listing_id": t.listing_id, "name": community.person(t.from_owner)["name"],
                        "status": t.status, "distance_km": float(t.distance_km)}
        found.append({"fitting_id": fid, "name": fits.name[fid], "available": len(waiting),
                      "nearest": nearest, "asking": bool(asking), "reserved": reserved})
    return found


@buyer_bp.route("/api/buyer/nearby")
def api_nearby():
    """After Confirm on the Advisor: who nearby is giving away what the buyer opted out of."""
    unit = request.args.get("unit", "")
    buyer = request.args.get("buyer", "")
    fittings = [fid for fid in request.args.get("fittings", "").split(",") if fid]
    if unit not in UNIT_TYPES:
        return jsonify({"error": f"Unknown unit type {unit}"}), 400
    try:
        return jsonify({"unit": unit, "buyer": buyer, "fittings": nearby(impact.load_data(), unit, buyer, fittings)})
    except ValueError as e:
        return jsonify({"error": e.args[0] if e.args else str(e)}), 400
