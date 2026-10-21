"""
neighbour_match.py - the Neighbour Match workflow (Member 3).

  list_item(unit, owner, fitting)          an owner offers a fitting they removed
  request_item(unit, requester, fitting)   a neighbour asks for one
  claim(listing_id, requester)             a neighbour takes one particular offer ("I'd like this")
  comment(post_id, author, text)           a message under an offer or a request
  collect(listing_id)                      the neighbour picked it up (with an optional thank-you)

Matching is instant and simple: same home type, same fitting, nearest home
first (distances on match_map's township map). A listing nobody has asked for
waits ("unmatched"); a request with nothing listed stays "open"; whichever
arrives second completes the match. A neighbour can also answer one post
directly: claim() takes that offer, and list_item(request_id=...) answers
that request. A listing's carbon counts only once it is collected
(impact.reuse_carbon_kg, in impact.reuse_summary).

Listings are data/matches.csv  (status: unmatched -> matched -> collected).
Requests are data/requests.csv (status: open -> matched, with the listing_id).
Messages are data/messages.csv (post_id is a listing or request id; kind
"comment", or "thanks" when posted with collect()).
Tiles and toilets/basins can't be listed (impact.NOT_REUSABLE).
"""

from datetime import datetime
from pathlib import Path

import pandas as pd

import impact
import match_map
from impact import DATA_DIR

CONDITIONS = ("Like new", "Good", "Fair")
MAX_TEXT = 280   # characters in a note, a message or a thank-you


def _next_id(ids, prefix):
    """L041 after L040 (R... for requests, M... for messages)."""
    nums = [int(i[len(prefix):]) for i in ids if isinstance(i, str) and i.startswith(prefix)]
    return f"{prefix}{max(nums, default=0) + 1:03d}"


def _stamp(now):
    """The time saved on a post: `now` if given (the generator passes simulated times), else the clock."""
    return now or datetime.now().strftime("%Y-%m-%d %H:%M")


def _text(value, what, required=False):
    """A note or message, trimmed. Raises ValueError if it isn't text, is too long, or is missing."""
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ValueError(f"The {what} must be text")
    value = " ".join(value.split())
    if required and not value:
        raise ValueError(f"Write a {what} first")
    if len(value) > MAX_TEXT:
        raise ValueError(f"Keep the {what} under {MAX_TEXT} characters")
    return value


def people(data, unit_type):
    """Everyone in this home type's community: owners (rip-out reports) and new buyers (Advisor choices)."""
    r, c = data["ripouts"], data["choices"]
    return set(r.owner_id[r.unit_type == unit_type]) | set(c.buyer_id[c.unit_type == unit_type])


def _check(data, unit_type, person, fitting_id):
    """The fitting can be rehomed, and the person lives in this home type. Raises ValueError."""
    f = data["fittings"]
    unit_fittings = f[f.unit_type == unit_type].set_index("fitting_id")
    if unit_fittings.empty:
        raise ValueError(f"Unknown unit type {unit_type}")
    if fitting_id not in unit_fittings.index:
        raise ValueError(f"Not a fitting for {unit_type}: {fitting_id}")
    if fitting_id in impact.NOT_REUSABLE:
        raise ValueError(f"{unit_fittings.name[fitting_id]} can't be rehomed: hacked-out tiles break, "
                         "and toilets and basins aren't reused for hygiene reasons")
    if person not in people(data, unit_type):
        raise ValueError(f"No owner or buyer {person} in {unit_type} homes")


def _describe(listing, data):
    """A listing as the API returns it: its fields, the fitting's name, km and carbon saved."""
    f = impact.get_fitting(data["fittings"], listing["unit_type"], listing["fitting_id"])
    km = listing["distance_km"]
    km = None if km in ("", None) or pd.isna(km) else float(km)
    collected = listing["status"] == "collected"
    saved = impact.reuse_carbon_kg(float(f["weight_kg"]), float(f["carbon_factor"]), km) if collected else 0.0
    return {"listing_id": listing["listing_id"], "unit_type": listing["unit_type"],
            "fitting_id": listing["fitting_id"], "name": f["name"], "from_owner": listing["from_owner"],
            "to_owner": listing["to_owner"] or None, "distance_km": km, "status": listing["status"],
            "condition": listing["condition"], "note": listing["note"], "posted_at": listing["posted_at"],
            "carbon_saved_kg": round(saved, 1)}


def _save(df, name, data_dir):
    df.to_csv(Path(data_dir) / name, index=False)


def _add_message(data, data_dir, post_id, author, kind, text, now):
    msgs = data["messages"]
    msg = {"message_id": _next_id(msgs.message_id, "M"), "post_id": post_id, "author": author,
           "kind": kind, "text": text, "posted_at": _stamp(now)}
    _save(pd.concat([msgs, pd.DataFrame([msg])], ignore_index=True), "messages.csv", data_dir)
    return msg


def list_item(unit_type, owner, fitting_id, data_dir=DATA_DIR, *, condition="Good", note="",
              request_id=None, now=None):
    """
    An owner lists a fitting they removed. Matched at once to the nearest neighbour
    with an open request for it (or to request `request_id`, when the owner is
    answering that post), else it waits. Returns the listing (see _describe).
    """
    data = impact.load_data(data_dir)
    _check(data, unit_type, owner, fitting_id)
    if condition not in CONDITIONS:
        raise ValueError(f"Condition must be one of: {', '.join(CONDITIONS)}")
    note = _text(note, "note")
    r = data["ripouts"]
    if not ((r.owner_id == owner) & (r.fitting_id == fitting_id) & (r.removed == 1)).any():
        raise ValueError(f"{owner} hasn't reported removing this fitting (add a rip-out report first)")
    m, req = data["matches"], data["requests"]
    if ((m.from_owner == owner) & (m.fitting_id == fitting_id)).any():
        raise ValueError(f"{owner} has already listed this fitting")
    stamp = _stamp(now)
    listing = {"listing_id": _next_id(m.listing_id, "L"), "from_owner": owner, "unit_type": unit_type,
               "fitting_id": fitting_id, "to_owner": "", "distance_km": "", "status": "unmatched",
               "condition": condition, "note": note, "posted_at": stamp, "matched_at": "", "collected_at": ""}
    wanted = req[(req.unit_type == unit_type) & (req.fitting_id == fitting_id)
                 & (req.status == "open") & (req.requester != owner)]
    if request_id is not None:
        wanted = wanted[wanted.request_id == request_id]
        if wanted.empty:
            raise ValueError(f"{request_id} isn't an open request for this fitting from a neighbour")
    if not wanted.empty:
        best = min(wanted.itertuples(),
                   key=lambda r: (match_map.distance_km(owner, r.requester, unit_type), r.request_id))
        listing.update(to_owner=best.requester, status="matched", matched_at=stamp,
                       distance_km=match_map.distance_km(owner, best.requester, unit_type))
        req.loc[req.request_id == best.request_id, ["status", "listing_id"]] = ["matched", listing["listing_id"]]
        _save(req, "requests.csv", data_dir)
    _save(pd.concat([m, pd.DataFrame([listing])], ignore_index=True), "matches.csv", data_dir)
    return _describe(listing, data)


def request_item(unit_type, requester, fitting_id, data_dir=DATA_DIR, *, note="", now=None):
    """
    A neighbour asks for a fitting. Matched at once to the nearest waiting listing,
    else the request stays open. Returns (request, listing or None).
    """
    data = impact.load_data(data_dir)
    _check(data, unit_type, requester, fitting_id)
    note = _text(note, "note")
    m, req = data["matches"], data["requests"]
    if ((req.requester == requester) & (req.fitting_id == fitting_id) & (req.status == "open")).any():
        raise ValueError(f"{requester} is already asking for this fitting")
    stamp = _stamp(now)
    request = {"request_id": _next_id(req.request_id, "R"), "requester": requester, "unit_type": unit_type,
               "fitting_id": fitting_id, "status": "open", "listing_id": "", "note": note, "posted_at": stamp}
    waiting = m[(m.unit_type == unit_type) & (m.fitting_id == fitting_id)
                & (m.status == "unmatched") & (m.from_owner != requester)]
    listing = None
    if not waiting.empty:
        best = min(waiting.itertuples(),
                   key=lambda r: (match_map.distance_km(r.from_owner, requester, unit_type), r.listing_id))
        listing = _match(m, best.listing_id, requester, stamp, data_dir, data)
        request.update(status="matched", listing_id=best.listing_id)
    _save(pd.concat([req, pd.DataFrame([request])], ignore_index=True), "requests.csv", data_dir)
    return request, listing


def _match(m, listing_id, requester, stamp, data_dir, data):
    """Give waiting listing `listing_id` to `requester`; saves matches.csv and returns the listing."""
    row = m[m.listing_id == listing_id].iloc[0]
    km = match_map.distance_km(row.from_owner, requester, row.unit_type)
    m.loc[m.listing_id == listing_id, ["to_owner", "distance_km", "status", "matched_at"]] = \
        [requester, km, "matched", stamp]
    _save(m, "matches.csv", data_dir)
    return _describe(m[m.listing_id == listing_id].iloc[0].to_dict(), data)


def claim(listing_id, requester, data_dir=DATA_DIR, *, now=None):
    """
    "I'd like this": a neighbour takes one waiting offer. Saved as a request that is
    matched straight away, so every match has a request behind it. Returns (request, listing).
    """
    data = impact.load_data(data_dir)
    m, req = data["matches"], data["requests"]
    row = m[m.listing_id == listing_id]
    if row.empty:
        raise ValueError(f"No listing {listing_id}")
    row = row.iloc[0]
    _check(data, row.unit_type, requester, row.fitting_id)
    if requester == row.from_owner:
        raise ValueError("That's your own listing")
    if row.status != "unmatched":
        raise ValueError(f"Listing {listing_id} is already {row.status}: it's going to another neighbour")
    stamp = _stamp(now)
    listing = _match(m, listing_id, requester, stamp, data_dir, data)
    request = {"request_id": _next_id(req.request_id, "R"), "requester": requester, "unit_type": row.unit_type,
               "fitting_id": row.fitting_id, "status": "matched", "listing_id": listing_id, "note": "",
               "posted_at": stamp}
    _save(pd.concat([req, pd.DataFrame([request])], ignore_index=True), "requests.csv", data_dir)
    return request, listing


def _post_unit(data, post_id):
    """The home type a listing (L...) or request (R...) belongs to. Raises ValueError."""
    for table, col in (("matches", "listing_id"), ("requests", "request_id")):
        rows = data[table][data[table][col] == post_id]
        if not rows.empty:
            return rows.unit_type.iloc[0]
    raise ValueError(f"No post {post_id}")


def comment(post_id, author, text, data_dir=DATA_DIR, *, now=None):
    """A message under an offer or a request, from anyone in that home type. Returns the message."""
    data = impact.load_data(data_dir)
    unit_type = _post_unit(data, post_id)
    if author not in people(data, unit_type):
        raise ValueError(f"No owner or buyer {author} in {unit_type} homes")
    return _add_message(data, data_dir, post_id, author, "comment", _text(text, "message", required=True), now)


def collect(listing_id, data_dir=DATA_DIR, *, by=None, thanks="", now=None):
    """
    The neighbour picked the fitting up: the listing is collected and its carbon counts.
    `by` (the giver or the neighbour who took it) is who pressed the button; the
    neighbour who took it can leave a thank-you note, shown under the offer.
    """
    data = impact.load_data(data_dir)
    m = data["matches"]
    row = m[m.listing_id == listing_id]
    if row.empty:
        raise ValueError(f"No listing {listing_id}")
    row = row.iloc[0]
    if row.status != "matched":
        raise ValueError(f"Listing {listing_id} is {row.status}: only a matched listing can be collected")
    if by is not None and by not in (row.from_owner, row.to_owner):
        raise ValueError("Only the giver or the neighbour taking it can mark it collected")
    thanks = _text(thanks, "thank-you note")
    if thanks and by != row.to_owner:
        raise ValueError("Only the neighbour who took it can leave a thank-you note")
    stamp = _stamp(now)
    m.loc[m.listing_id == listing_id, ["status", "collected_at"]] = ["collected", stamp]
    _save(m, "matches.csv", data_dir)
    if thanks:
        _add_message(data, data_dir, listing_id, by, "thanks", thanks, stamp)
    return _describe(m[m.listing_id == listing_id].iloc[0].to_dict(), data)


def suggestions(data, unit_type):
    """
    Who could list what (owners who reported removing a reusable fitting and
    haven't listed it), and who could ask (this type's buyers). Each list puts
    first the entries that would match straight away.
    """
    r, m, req = data["ripouts"], data["matches"], data["requests"]
    listed = set(zip(m.from_owner, m.fitting_id))
    open_asks = set(req.fitting_id[(req.unit_type == unit_type) & (req.status == "open")])
    waiting = set(m.fitting_id[(m.unit_type == unit_type) & (m.status == "unmatched")])
    removed = r[(r.unit_type == unit_type) & (r.removed == 1) & ~r.fitting_id.isin(impact.NOT_REUSABLE)]
    can_list = [(o, fid) for o, fid in zip(removed.owner_id, removed.fitting_id) if (o, fid) not in listed]
    can_list.sort(key=lambda p: p[1] not in open_asks)            # instant matches first
    c = data["choices"]
    buyers = sorted(set(c.buyer_id[c.unit_type == unit_type]))
    return {"can_list": can_list, "buyers": buyers, "open_asks": sorted(open_asks), "waiting": sorted(waiting)}
