"""
buyer.py - the buyer screens' own API, as a Flask Blueprint (Member 2).

app.py plugs it in next to dashboard.py's:

    from buyer import buyer_bp
    app.register_blueprint(buyer_bp)

The maths and the matching stay with their owners: distances come from
match_map, the nearest offer from neighbour_match, carbon from
impact.rehomed_carbon_kg, names and homes from community.
"""

from flask import Blueprint, jsonify, request

import community
import impact
import match_map
import neighbour_match
from dashboard import bad_request

buyer_bp = Blueprint("buyer", __name__)


def nearby(data, unit_type, buyer, fitting_ids):
    """
    For each fitting: the nearest offer waiting on Neighbour Match, how many are
    waiting, whether `buyer` already has an open request for it, and the one
    already reserved for them (or collected), if any. The nearest offer is
    neighbour_match.nearest_offer, the one request_item gives, so asking gets this offer.
    Raises ValueError for someone who isn't a buyer of this home type, or a
    fitting that can't be rehomed.
    """
    if impact.parse_person(buyer) != (unit_type, "buyer") or buyer not in neighbour_match.people(data, unit_type):
        raise ValueError(f"No buyer {buyer} in {unit_type} homes")
    fits = impact.unit_fittings(data, unit_type)
    m, req = data["matches"], data["requests"]
    found = []
    for fid in fitting_ids:
        if fid not in fits.index or fid in impact.NOT_REUSABLE:
            raise ValueError(f"Not a fitting a neighbour can give in {unit_type} homes: {fid}")
        best = neighbour_match.nearest_offer(data, unit_type, fid, buyer)
        nearest = None
        if best is not None:
            km = match_map.distance_km(best.from_owner, buyer, unit_type)
            giver = community.person(best.from_owner)
            nearest = {"listing_id": best.listing_id, "from_owner": best.from_owner, "name": giver["name"],
                       "home": giver["home"], "distance_km": km, "condition": best.condition, "note": best.note,
                       "carbon_saved_kg": impact.rehomed_carbon_kg(fits.loc[fid], km)}
        asking = ((req.requester == buyer) & (req.fitting_id == fid) & (req.status == "open")).any()
        taken = m[(m.unit_type == unit_type) & (m.fitting_id == fid) & (m.to_owner == buyer) & (m.status != "unmatched")]
        reserved = None
        if not taken.empty:
            t = taken.iloc[0]
            reserved = {"listing_id": t.listing_id, "name": community.person(t.from_owner)["name"],
                        "status": t.status, "distance_km": float(t.distance_km)}
        found.append({"fitting_id": fid, "name": fits.name[fid],
                      "available": len(neighbour_match.waiting_offers(data, unit_type, fid, buyer)),
                      "nearest": nearest, "asking": bool(asking), "reserved": reserved})
    return found


@buyer_bp.route("/api/buyer/nearby")
def api_nearby():
    """After Confirm on the Advisor: who nearby is giving away what the buyer opted out of."""
    unit = request.args.get("unit", "")
    buyer = request.args.get("buyer", "")
    fittings = [fid for fid in request.args.get("fittings", "").split(",") if fid]
    if unit not in impact.UNIT_TYPES:
        return jsonify({"error": f"Unknown unit type {unit}"}), 400
    try:
        return jsonify({"unit": unit, "buyer": buyer, "fittings": nearby(impact.load_data(), unit, buyer, fittings)})
    except ValueError as e:
        return bad_request(e)
