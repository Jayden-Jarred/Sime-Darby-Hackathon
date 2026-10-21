"""
tagger.py - turn messy renovation notes into standard fittings (Member 3).

    tag("hak semua kabinet dapur, tukar quartz top", unit_type="T2S")
    -> {"tags": [{"fitting_id": "KIT-CAB", "confidence": 0.9, ...},
                 {"fitting_id": "KIT-TOP", "confidence": 0.85, ...}],
        "spans": [...], "removal_word": True}

This is a KEYWORD tagger: English, Malay and Manglish word lists plus a few
rules (e.g. a wardrobe in the "master" room vs the "small room"). It runs
offline and is the fallback for the demo.

MEMBER 3: to use an AI model instead, replace the body of `tag()` - keep the
same inputs and outputs and every page keeps working. Keep this keyword
version as the fallback for when there's no internet.
"""

import re

# ---- word lists (lower-case; \b = word boundary) ------------------------
P = {
    "cabinet": r"\b(?:cabinets?|kabinet|cupboards?|almari dapur|(?:upper|lower|base|wall) (?:cabinets?|units?))\b",
    "kitchen": r"\b(?:kitchen|dapur)\b",
    "full_kitchen": r"\b(?:full|whole|entire|redo(?: the)?|semua) kitchen\b|\bkitchen (?:semua|baru)\b|\bredo (?:the )?(?:full |whole )?kitchen\b",
    "top": r"\b(?:kitchen ?top|work ?tops?|counter ?tops?|table ?top|quartz|granite|solid surface)\b",
    "wardrobe": r"\b(?:wardrobes?|almari(?! dapur)(?: baju)?|built[- ]?ins?|closets?)\b",
    "master": r"\b(?:master(?: bed)?(?:room)?|bilik utama)\b",
    "room2": r"\b(?:bedroom ?2|room ?2|2nd (?:bed)?room|second (?:bed)?room|small (?:bed)?room|kids? room|guest room|bilik kecil|bilik 2|bilik anak)\b",
    "light": r"\b(?:lights?|lighting|lampu|downlights?|led|chandeliers?|pendants?|ceiling lights?)\b",
    "tile": r"\b(?:tiles?|tiling|retile|re-tile|jubin|homogeneous|vinyl|parquet)\b",
    "floor": r"\b(?:floor(?:ing)?|lantai)\b",
    "sanitary": r"\b(?:toilet(?: bowl)?|wc|mangkuk tandas|tandas|basins?|wash ?basin|sinki)\b",
    "action": r"\b(?:hack(?:ed)?|hak|remove[ds]?|removed|buang|tukar|change[ds]?|replace[ds]?|ganti|tear|torn|rip(?:ped)?|"
              r"dismantle[ds]?|redo(?:ne)?|swap(?:ped)?|install new|new|baru|gone)\b",
}
RX = {k: re.compile(v) for k, v in P.items()}

NAMES = {
    "KIT-CAB": "Kitchen cabinets", "KIT-TOP": "Kitchen top", "WRD-MST": "Master bedroom wardrobe",
    "WRD-BR2": "Bedroom 2 wardrobe", "LGT-DEC": "Decorative light fittings",
    "TIL-FLR": "Floor tiles", "SAN-BTH": "Basins and toilets",
}
THRESHOLD = 0.4

# Test notes with the right answer. None = the note is not about a tracked
# fitting (should get no tags).
#
# TUNING_NOTES: written separately from the demo data, but the word lists
# were then extended until they all pass (e.g. "bilik utama", "jubin",
# "mangkuk tandas"), so they are NOT a fair test.
TUNING_NOTES = [
    ("contractor tear down the whole kitchen cabinet set", "KIT-CAB"),
    ("hak semua kabinet dapur, buat baru", "KIT-CAB"),
    ("the stuff in the kitchen all gone, contractor redo", "KIT-CAB"),
    ("swap the countertop for quartz", "KIT-TOP"),
    ("granite top replaced", "KIT-TOP"),
    ("buang almari bilik utama", "WRD-MST"),
    ("master bedroom built-in redone", "WRD-MST"),
    ("kids room wardrobe change to open shelf", "WRD-BR2"),
    ("almari bilik kecil tukar", "WRD-BR2"),
    ("replace all the ceiling lights with LED", "LGT-DEC"),
    ("tukar lampu ruang tamu", "LGT-DEC"),
    ("hack downstairs flooring, put vinyl", "TIL-FLR"),
    ("jubin lantai tukar semua", "TIL-FLR"),
    ("change mangkuk tandas", "SAN-BTH"),
    ("new wash basin in common bathroom", "SAN-BTH"),
    ("repaint living room walls", None),
    ("install grille and awning only", None),
]

# HELD_OUT: the honest number. The word lists were never tuned to these.
# If you change the rules to fix a miss here, move that note to TUNING_NOTES,
# and add new held-out notes from someone who hasn't seen the word lists.
HELD_OUT = [
    ("get rid of the cheap pantry units", "KIT-CAB"),
    ("lights all changed to warm white", "LGT-DEC"),
    ("redo bathroom, new sink and toilet", "SAN-BTH"),
    ("install new curtain rails", None),
    ("tore out old floor tiles in kitchen", "TIL-FLR"),
    ("change all the doors of the kitchen cupboards", "KIT-CAB"),
    ("ripped out the robe in main bedroom", "WRD-MST"),
    ("buang semua lampu siling", "LGT-DEC"),
]


def _spans(rx, text):
    return [(m.start(), m.end()) for m in rx.finditer(text)]


def tag(note, unit_type=None, fitting_ids=None):
    """
    Tag one note. Returns {"tags": [...], "spans": [...], "removal_word": bool}.
    tags:  [{"fitting_id", "name", "confidence" (0-1), "reason"}], best first
    spans: [{"start", "end", "fitting_id"}] - which words led to each tag,
           as positions in the original note (for highlighting)
    fitting_ids: limit tags to these (e.g. the fittings a unit type has).
    unit_type: not used by the keyword rules; part of the interface so an AI
               version of tag() can use it.
    """
    text = (note or "").lower()
    hits = {k: _spans(rx, text) for k, rx in RX.items()}
    score, reason, spans = {}, {}, []

    def add(fid, conf, why, keys):
        if conf > score.get(fid, 0):
            score[fid], reason[fid] = conf, why
        for k in keys:
            spans.extend({"start": s, "end": e, "fitting_id": fid} for s, e in hits[k])

    if hits["cabinet"]:
        add("KIT-CAB", 0.9 if hits["kitchen"] else 0.75, "mentions cabinets", ["cabinet", "kitchen"])
    if hits["full_kitchen"]:
        add("KIT-CAB", 0.7, "whole kitchen redone", ["full_kitchen"])
        add("KIT-TOP", 0.5, "whole kitchen redone", ["full_kitchen"])
    elif hits["kitchen"] and hits["action"] and not hits["top"] and not hits["cabinet"]:
        add("KIT-CAB", 0.55, "kitchen changed, item not named", ["kitchen"])
    if hits["top"]:
        add("KIT-TOP", 0.85, "mentions a worktop", ["top"])
    if hits["wardrobe"]:
        if hits["master"]:
            add("WRD-MST", 0.9, "wardrobe in the master bedroom", ["wardrobe", "master"])
        if hits["room2"]:
            add("WRD-BR2", 0.9, "wardrobe in a smaller bedroom", ["wardrobe", "room2"])
        if not hits["master"] and not hits["room2"]:
            add("WRD-MST", 0.5, "wardrobe, room not stated", ["wardrobe"])
            add("WRD-BR2", 0.45, "wardrobe, room not stated", ["wardrobe"])
    if hits["light"]:
        add("LGT-DEC", 0.85, "mentions lights", ["light"])
    if hits["tile"]:
        add("TIL-FLR", 0.85, "mentions tiles or flooring", ["tile", "floor"])
    elif hits["floor"] and hits["action"]:
        add("TIL-FLR", 0.6, "floor changed", ["floor"])
    if hits["sanitary"]:
        add("SAN-BTH", 0.85, "mentions toilet or basin", ["sanitary"])

    removal = bool(hits["action"])
    tags = []
    for fid, conf in score.items():
        if fitting_ids is not None and fid not in fitting_ids:
            continue
        if not removal:
            conf *= 0.75   # mentions the item but not that it was removed
        if conf >= THRESHOLD:
            tags.append({"fitting_id": fid, "name": NAMES[fid], "confidence": round(conf, 2),
                         "reason": reason[fid] + ("" if removal else " (no removal word)")})
    tags.sort(key=lambda t: -t["confidence"])
    keep = {t["fitting_id"] for t in tags}
    spans = sorted({(s["start"], s["end"], s["fitting_id"]) for s in spans if s["fitting_id"] in keep})
    if removal:
        spans += [(s, e, "action") for s, e in hits["action"]]
    return {
        "tags": tags,
        "spans": [{"start": s, "end": e, "fitting_id": f} for s, e, f in sorted(spans)],
        "removal_word": removal,
    }


def _score(notes):
    correct, misses = 0, []
    for note, truth in notes:
        t = tag(note)["tags"]
        got = t[0]["fitting_id"] if t else None
        if got == truth:
            correct += 1
        else:
            misses.append({"note": note, "expected": truth, "got": got})
    return {"n": len(notes), "correct": correct, "misses": misses}


def evaluate(ripouts=None):
    """
    Accuracy of the top tag.
    sample:   the demo's own notes (we wrote the word lists from these, so it
              will look near-perfect - NOT a fair test).
    tuning:   TUNING_NOTES - the rules were adjusted to pass these, NOT a fair test.
    held_out: HELD_OUT - notes the rules were never tuned to, the honest number.
    """
    out = {}
    if ripouts is not None:
        rows = ripouts[ripouts.note.notna() & (ripouts.note != "")]
        correct = sum(
            1 for note, truth in zip(rows.note, rows.fitting_id)
            if (t := tag(note)["tags"]) and t[0]["fitting_id"] == truth
        )
        out["sample"] = {"n": len(rows), "correct": correct}
    out["tuning"] = _score(TUNING_NOTES)
    out["held_out"] = _score(HELD_OUT)
    return out


if __name__ == "__main__":
    from impact import load_data
    r = evaluate(load_data()["ripouts"])
    s, u, h = r["sample"], r["tuning"], r["held_out"]
    print(f"Sample notes: {s['correct']}/{s['n']} ({s['correct'] / s['n']:.0%}) - not a fair test")
    print(f"Tuning notes: {u['correct']}/{u['n']} ({u['correct'] / u['n']:.0%}) - not a fair test")
    print(f"Held-out notes: {h['correct']}/{h['n']} ({h['correct'] / h['n']:.0%})")
    for m in h["misses"]:
        print("  missed:", m)
