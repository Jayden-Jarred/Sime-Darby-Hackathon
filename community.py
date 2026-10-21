"""
community.py - the people and the feed on the Neighbour Match page.

  person(pid)                    a neighbour's name, initials, avatar colour, home and role
  everyone(data, unit)           every neighbour in a home type, for the "Browsing as" picker
  feed(data, unit, you)          every offer and request as a post, latest activity first,
                                 with its messages and what `you` can do on it
  you_card(data, unit, you)      your profile: what you gave and got, badges, what you can offer
  leaderboard(data, unit)        top givers by carbon saved
  activity(data, unit)           the latest happenings, for the sidebar
  stats(data, unit)              how many neighbours are taking part

The neighbours are simulated: names are made up from the id (no two the same
in a home type) and homes come from match_map's fictional township. The
actions themselves (list, ask, claim, comment, collect) are neighbour_match.py.
"""

from datetime import datetime

import pandas as pd

import impact
import match_map
import neighbour_match

FIRST_NAMES = ["Aisyah", "Wei Ming", "Priya", "Farid", "Mei Ling", "Arjun", "Nurul", "Jun Hao", "Kavitha", "Daniel",
               "Siti", "Hui Min", "Ravi", "Sarah", "Hafiz", "Xin Yi", "Deepa", "Jason", "Amir", "Li Ting",
               "Suresh", "Melissa", "Zulaikha", "Kok Leong", "Anitha", "Adam", "Irfan", "Jia Hui", "Vikram", "Rachel",
               "Aina", "Chee Keong", "Nadia", "Marcus", "Faizal", "Kah Wai", "Yasmin", "Hannah", "Harith", "Shalini"]
INITIALS = "ABCDFGHJKLMNOPRSTWYZ"   # 20: with 40 first names, unique for the first 800 homes of a type
AVATAR_COLOURS = ["#2f6b4f", "#b4532f", "#7a5c00", "#4f6597", "#87496f", "#2f7078"]
# Badges: (name, what earns it). Earned from the listings, so they update as people give and take.
BADGES = [("Giver", "gave a fitting to a neighbour"),
          ("Super neighbour", "gave 3 or more fittings"),
          ("Second life", "took in a neighbour's fitting")]
STAMP = "%Y-%m-%d %H:%M"


def _unit_of(pid):
    return pid.split("-")[0] if isinstance(pid, str) and "-" in pid else ""


def person(pid):
    """A neighbour as the page shows them. The home type comes from the id (T2S-O001)."""
    unit = _unit_of(pid)
    n = match_map.home_number(pid) + (17 if unit == "C3R" else 0)   # C3R gets a different name order
    first, initial = FIRST_NAMES[n % len(FIRST_NAMES)], INITIALS[(n // len(FIRST_NAMES) + n) % len(INITIALS)]
    owner = "-O" in pid
    return {"id": pid, "name": f"{first} {initial}.",
            "initials": (first[0] + initial).upper(),
            "colour": AVATAR_COLOURS[n % len(AVATAR_COLOURS)],
            "home": match_map.address(pid, unit),
            "role": "Homeowner" if owner else "Moving in"}


def everyone(data, unit_type):
    """Every owner and buyer in this home type, by name."""
    return sorted((person(p) for p in neighbour_match.people(data, unit_type)), key=lambda p: (p["name"], p["id"]))


def ago(stamp, now):
    """'5 min ago', '3 h ago', 'yesterday', '4 days ago', or the date."""
    if not stamp:
        return ""
    t = datetime.strptime(stamp, STAMP)
    s = (now - t).total_seconds()
    if s < 60:
        return "just now"
    if s < 3600:
        return f"{int(s // 60)} min ago"
    if s < 86400:
        return f"{int(s // 3600)} h ago"
    days = int(s // 86400)
    if days == 1:
        return "yesterday"
    return f"{days} days ago" if days < 7 else f"{t.day} {t:%b}"


def _km(v):
    return None if v in ("", None) or pd.isna(v) else float(v)


def _saved(fit, km):
    return round(float(impact.reuse_carbon_kg(float(fit.weight_kg), float(fit.carbon_factor), km)), 1)


def _threads(data, now):
    """post_id -> its messages, oldest first."""
    out = {}
    for r in data["messages"].sort_values(["posted_at", "message_id"]).to_dict("records"):
        out.setdefault(r["post_id"], []).append(
            {"author": person(r["author"]), "kind": r["kind"], "text": r["text"], "ago": ago(r["posted_at"], now)})
    return out


def _can_give(data, unit_type, you):
    """Reusable fittings `you` reported removing and haven't listed yet."""
    r, m = data["ripouts"], data["matches"]
    removed = r[(r.owner_id == you) & (r.removed == 1) & ~r.fitting_id.isin(impact.NOT_REUSABLE)]
    listed = set(m.fitting_id[m.from_owner == you])
    return [fid for fid in removed.fitting_id if fid not in listed]


def _waited(request, by_listing):
    """
    True for a request that was open for a while (still open, or matched later).
    A request matched the moment it was made (an ask that found a waiting offer,
    or "I'd like this") is told by its offer's post instead, so a match isn't shown twice.
    """
    return not request["listing_id"] or request["posted_at"] < by_listing.loc[request["listing_id"], "matched_at"]


def feed(data, unit_type, you=None, now=None):
    """
    Every offer (listing) and every request that waited for a match (_waited),
    as posts, latest activity first.
    """
    now = now or datetime.now()
    fits = data["fittings"][data["fittings"].unit_type == unit_type].set_index("fitting_id")
    m = data["matches"][data["matches"].unit_type == unit_type]
    req = data["requests"][data["requests"].unit_type == unit_type]
    threads = _threads(data, now)
    member = you in neighbour_match.people(data, unit_type)
    giveable = set(_can_give(data, unit_type, you)) if member else set()
    by_listing = m.set_index("listing_id")
    # what a neighbour wrote when their request matched an offer at once (it has no post of its own)
    ask_notes = {r["listing_id"]: r["note"] for r in req.to_dict("records")
                 if r["listing_id"] and r["note"] and not _waited(r, by_listing)}
    posts = []

    def km_from_you(pid):
        return match_map.distance_km(you, pid, unit_type) if member and pid != you else None

    for r in m.to_dict("records"):
        fit, km, status = fits.loc[r["fitting_id"]], _km(r["distance_km"]), r["status"]
        other = person(r["to_owner"]) if r["to_owner"] else None
        msgs = threads.get(r["listing_id"], [])
        posts.append({
            "id": r["listing_id"], "kind": "offer", "fitting_id": r["fitting_id"], "name": fit["name"],
            "weight_kg": float(fit.weight_kg), "author": person(r["from_owner"]),
            "ago": ago(r["posted_at"], now), "condition": r["condition"], "note": r["note"],
            "status": status, "other": other, "km": km, "km_from_you": km_from_you(r["from_owner"]),
            "carbon_saved_kg": _saved(fit, km) if status == "collected" else 0.0,
            "when": ago(r["collected_at"] or r["matched_at"], now),
            "ask_note": ask_notes.get(r["listing_id"], ""),
            "messages": msgs, "mine": r["from_owner"] == you or r["to_owner"] == you,
            "can": {"claim": member and status == "unmatched" and r["from_owner"] != you,
                    "collect": status == "matched" and you in (r["from_owner"], r["to_owner"]),
                    "thank": status == "matched" and you == r["to_owner"],
                    "comment": member},
            "active_at": max([r["posted_at"], r["matched_at"], r["collected_at"]]),
        })
    for r in req.to_dict("records"):
        if not _waited(r, by_listing):
            continue
        listing = by_listing.loc[r["listing_id"]] if r["listing_id"] else None
        status = "open" if listing is None else listing.status
        msgs = threads.get(r["request_id"], [])
        posts.append({
            "id": r["request_id"], "kind": "wanted", "fitting_id": r["fitting_id"],
            "name": fits.loc[r["fitting_id"], "name"], "author": person(r["requester"]),
            "ago": ago(r["posted_at"], now), "note": r["note"], "status": status,
            "other": person(listing.from_owner) if listing is not None else None,
            "listing_id": r["listing_id"] or None, "km_from_you": km_from_you(r["requester"]),
            "km": _km(listing.distance_km) if listing is not None else None,
            "messages": msgs, "mine": r["requester"] == you,
            "can": {"offer": member and status == "open" and r["requester"] != you and r["fitting_id"] in giveable,
                    "comment": member},
            "active_at": r["posted_at"] if listing is None else max(r["posted_at"], listing.matched_at,
                                                                   listing.collected_at),
        })
    last = data["messages"].groupby("post_id").posted_at.max().to_dict()
    for p in posts:
        p["active_at"] = max(p["active_at"], last.get(p["id"], ""))
    posts.sort(key=lambda p: (p["active_at"], p["id"]), reverse=True)
    return posts


def you_card(data, unit_type, you):
    """Your profile on the page: your giving and taking, badges, and what you could offer now."""
    fits = data["fittings"][data["fittings"].unit_type == unit_type].set_index("fitting_id")
    m = data["matches"][data["matches"].unit_type == unit_type]
    req = data["requests"][data["requests"].unit_type == unit_type]
    gave = m[(m.from_owner == you) & (m.status == "collected")]
    took = m[(m.to_owner == you) & (m.status == "collected")]
    carbon = sum(_saved(fits.loc[r.fitting_id], _km(r.distance_km)) for r in gave.itertuples())
    asked = set(req.fitting_id[(req.status == "open") & (req.requester != you)])
    earned = {"Giver": len(gave) >= 1, "Super neighbour": len(gave) >= 3, "Second life": len(took) >= 1}
    return {
        "person": person(you), "gave": len(gave), "took": len(took), "carbon_kg": carbon,
        "giving": int(((m.from_owner == you) & (m.status != "collected")).sum()),
        "asking": int(((req.requester == you) & (req.status == "open")).sum()),
        "badges": [{"name": n, "why": w, "earned": earned[n]} for n, w in BADGES],
        "can_give": sorted(({"id": fid, "name": fits.loc[fid, "name"], "asked": fid in asked}
                            for fid in _can_give(data, unit_type, you)), key=lambda g: not g["asked"]),
    }


def leaderboard(data, unit_type, top=5):
    """The neighbours who gave the most, by carbon saved (fittings collected)."""
    fits = data["fittings"][data["fittings"].unit_type == unit_type].set_index("fitting_id")
    m = data["matches"]
    done = m[(m.unit_type == unit_type) & (m.status == "collected")]
    board = {}
    for r in done.itertuples():
        b = board.setdefault(r.from_owner, {"person": person(r.from_owner), "gave": 0, "carbon_kg": 0.0})
        b["gave"] += 1
        b["carbon_kg"] += _saved(fits.loc[r.fitting_id], _km(r.distance_km))
    return sorted(board.values(), key=lambda b: (-b["carbon_kg"], b["person"]["name"]))[:top]


def activity(data, unit_type, now=None, top=8):
    """The latest offers, requests, matches and pick-ups, newest first."""
    now = now or datetime.now()
    names = data["fittings"][data["fittings"].unit_type == unit_type].set_index("fitting_id").name
    m = data["matches"][data["matches"].unit_type == unit_type]
    req = data["requests"][data["requests"].unit_type == unit_type]
    events = []
    for r in m.itertuples():
        thing = names[r.fitting_id].lower()
        events.append((r.posted_at, "offer", f"{person(r.from_owner)['name']} offered {thing}", r.listing_id))
        if r.matched_at:
            events.append((r.matched_at, "match", f"{thing.capitalize()} matched: {person(r.from_owner)['name']} "
                           f"to {person(r.to_owner)['name']}, {_km(r.distance_km):.1f} km", r.listing_id))
        if r.collected_at:
            events.append((r.collected_at, "collected",
                           f"{person(r.to_owner)['name']} collected {thing} from {person(r.from_owner)['name']}",
                           r.listing_id))
    by_listing = m.set_index("listing_id")
    for r in req.to_dict("records"):
        if _waited(r, by_listing):   # the requests that are posts in the feed
            events.append((r["posted_at"], "ask", f"{person(r['requester'])['name']} is looking for "
                           f"{names[r['fitting_id']].lower()}", r["request_id"]))
    events.sort(key=lambda e: e[0], reverse=True)
    return [{"kind": k, "text": t, "post": p, "ago": ago(s, now)} for s, k, t, p in events[:top]]


def stats(data, unit_type):
    """How many neighbours have posted, taken or written something."""
    m = data["matches"][data["matches"].unit_type == unit_type]
    req = data["requests"][data["requests"].unit_type == unit_type]
    msgs = data["messages"]
    ids = set(m.from_owner) | set(m.to_owner) | set(req.requester) | set(msgs.author)
    return {"neighbours": len({p for p in ids if _unit_of(p) == unit_type})}
