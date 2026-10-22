"""
tagger.py - turn messy renovation notes into standard fittings (Member 3).

    tag("hak semua kabinet dapur, tukar quartz top", unit_type="T2S")
    -> {"tags": [{"fitting_id": "KIT-CAB", "confidence": 0.9, ...},
                 {"fitting_id": "KIT-TOP", "confidence": 0.85, ...}],
        "spans": [...], "removal_word": True, "engine": "ai"}

Two ways to read a note, with the same inputs and outputs:

- AI: Claude reads the note through the Anthropic API. On when the `anthropic`
  package is installed and ANTHROPIC_API_KEY is set. TAGGER_MODEL picks the
  model (default claude-opus-5-5).
- KEYWORDS: English, Malay and Manglish word lists plus a few rules (e.g. a
  wardrobe in the "master" room vs the "small room"). Runs offline. It is the
  backup: used when AI is off, and whenever Claude can't be reached or its
  answer can't be read (the result then says why in "ai_error").

python tagger.py checks the keyword rules; python tagger.py --ai checks Claude
on the same test notes.
"""

import functools
import json
import logging
import os
import re

try:
    import anthropic
except ImportError:   # optional: without it the keyword rules do all the tagging
    anthropic = None

log = logging.getLogger(__name__)

# ---- word lists (lower-case; \b = word boundary) ------------------------
WORD_LISTS = {   # name -> regex of the words that mean it
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
WORD_RX = {k: re.compile(v) for k, v in WORD_LISTS.items()}

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


def _one_guess_left(tags):
    """A pick-one group with a single tag left has nothing to pick between."""
    if sum(t["pick_one"] == "wardrobe" for t in tags) < 2:
        for t in tags:
            t["pick_one"] = None


def keyword_tag(note, unit_type=None, fitting_ids=None):
    """The keyword rules: same inputs and outputs as tag(). unit_type isn't used here."""
    text = (note or "").lower()
    hits = {k: _spans(rx, text) for k, rx in WORD_RX.items()}
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
                         "reason": reason[fid] + ("" if removal else " (no removal word)"),
                         "pick_one": "wardrobe" if reason[fid] == "wardrobe, room not stated" else None})
    _one_guess_left(tags)
    tags.sort(key=lambda t: -t["confidence"])
    keep = {t["fitting_id"] for t in tags}
    spans = sorted({(s["start"], s["end"], s["fitting_id"]) for s in spans if s["fitting_id"] in keep})
    if removal:
        spans += [(s, e, "action") for s, e in hits["action"]]
    return {
        "tags": tags,
        "spans": [{"start": s, "end": e, "fitting_id": f} for s, e, f in sorted(spans)],
        "removal_word": removal,
        "engine": "keywords",
    }


# ---- AI: Claude reads the note -------------------------------------------
MODEL = os.environ.get("TAGGER_MODEL", "claude-opus-5-5")
# Models that take "fallbacks": if Claude's safety checks decline a note, the API
# retries it on another model instead of refusing.
SERVER_FALLBACK = ("claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5")
HOME = {"T2S": "double-storey terrace house", "C3R": "3-room condo"}
HINTS = {   # what each fitting covers. Never add words from HELD_OUT: it would stop being a fair test
    "KIT-CAB": "the kitchen cabinets, upper and lower",
    "KIT-TOP": "the kitchen worktop or countertop",
    "WRD-MST": "the built-in wardrobe in the master bedroom",
    "WRD-BR2": "the built-in wardrobe in the second, smaller bedroom",
    "LGT-DEC": "the decorative light fittings",
    "TIL-FLR": "the floor tiles, also when new flooring replaces or covers them",
    "SAN-BTH": "the basins and toilets",
}
SYSTEM = """You read renovation notes written by Malaysian homeowners and say which of the \
developer's standard fittings they removed or replaced after moving in. Notes are short and \
messy: English, Malay or Manglish, with typos and slang.

Tag a fitting only when the note says it was removed, replaced, changed or redone, or clearly \
implies it (redoing the whole kitchen means the cabinets and the worktop). Tag nothing when \
the note is about something else, such as painting or grilles.

For each tag:
- confidence: 0 to 1, how sure you are that the note means this fitting.
- reason: a few plain words on why, e.g. "kitchen cabinets hacked out".
- evidence: the words in the note that name this fitting, copied exactly as written.
- room_not_stated: true only for a wardrobe when the note doesn't say which bedroom. Then tag \
every wardrobe on the list, each with room_not_stated true and confidence under 0.6.

removed: true when the note says something was removed, replaced, changed or redone.
removal_words: the words in the note that say so, copied exactly as written."""


def _schema(fids):
    return {
        "type": "object",
        "properties": {
            "tags": {"type": "array", "items": {
                "type": "object",
                "properties": {
                    "fitting_id": {"type": "string", "enum": list(fids)},
                    "confidence": {"type": "number"},
                    "reason": {"type": "string"},
                    "evidence": {"type": "array", "items": {"type": "string"}},
                    "room_not_stated": {"type": "boolean"},
                },
                "required": ["fitting_id", "confidence", "reason", "evidence", "room_not_stated"],
                "additionalProperties": False,
            }},
            "removed": {"type": "boolean"},
            "removal_words": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["tags", "removed", "removal_words"],
        "additionalProperties": False,
    }


@functools.lru_cache(maxsize=1)
def _client():
    """The Anthropic client, or None when AI tagging is off (no package or no key)."""
    if anthropic is None or not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    return anthropic.Anthropic(timeout=15.0, max_retries=1)


def ai_on():
    return _client() is not None


class NoAnswer(Exception):
    """Claude replied, but without a usable answer."""


@functools.lru_cache(maxsize=512)
def _ask_claude(note, unit_type, fids):
    """Claude's answer for one note, as a dict. Cached, because the page asks again as
    someone types and deletes, so don't change the dict it returns."""
    fittings = "\n".join(f"- {f} ({NAMES[f]}): {HINTS[f]}" for f in fids)
    extra = ({"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
             if MODEL.startswith(SERVER_FALLBACK) else {})
    response = _client().beta.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=SYSTEM,
        messages=[{"role": "user", "content":
                   f"Home type: {HOME.get(unit_type, 'not given')}\nFittings this home has:\n{fittings}\n\n"
                   f"<note>\n{note}\n</note>"}],
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": _schema(fids)}},
        **extra,
    )
    if response.stop_reason == "refusal":
        raise NoAnswer("Claude declined to read this note")
    if response.stop_reason != "end_turn":
        raise NoAnswer(f"Claude's answer was cut off ({response.stop_reason})")
    text = next((b.text for b in response.content if b.type == "text"), None)
    if text is None:
        raise NoAnswer("Claude's answer had no text")
    return json.loads(text)


def _find(note, words):
    """Where each quoted phrase is in the note (any case), as (start, end). Positions come
    from here, never from the model, so a phrase that isn't in the note marks nothing."""
    low = note.lower()
    phrases = {str(w).strip().lower() for w in words} - {""}
    return [(m.start(), m.end()) for w in phrases for m in re.finditer(re.escape(w), low)]


def _from_answer(note, answer, allowed):
    """Claude's answer -> the same shape as keyword_tag()."""
    tags, spans = {}, set()
    for t in answer["tags"]:
        fid, conf = t["fitting_id"], min(max(float(t["confidence"]), 0.0), 1.0)
        if fid not in allowed or fid in tags or conf < THRESHOLD:
            continue
        tags[fid] = {"fitting_id": fid, "name": NAMES[fid], "confidence": round(conf, 2),
                     "reason": str(t["reason"]).strip() or "named in the note",
                     "pick_one": "wardrobe" if t["room_not_stated"] and fid.startswith("WRD-") else None}
        spans |= {(s, e, fid) for s, e in _find(note, t["evidence"])}
    tags = sorted(tags.values(), key=lambda t: -t["confidence"])
    _one_guess_left(tags)
    removed = bool(answer["removed"])
    if removed:
        spans |= {(s, e, "action") for s, e in _find(note, answer["removal_words"])}
    return {"tags": tags, "spans": [{"start": s, "end": e, "fitting_id": f} for s, e, f in sorted(spans)],
            "removal_word": removed, "engine": "ai", "model": MODEL}


def tag(note, unit_type=None, fitting_ids=None):
    """
    Tag one note. Returns {"tags": [...], "spans": [...], "removal_word": bool, "engine": ...}.
    tags:  [{"fitting_id", "name", "confidence" (0-1), "reason", "pick_one"}], best first.
           pick_one: tags that share a value are alternatives for ONE item (a wardrobe,
           room not stated): a report should keep only one of them. None otherwise.
    spans: [{"start", "end", "fitting_id"}] - which words led to each tag,
           as positions in the original note (for highlighting)
    engine: "ai" (Claude read it; "model" says which) or "keywords". When Claude was
            asked but the keyword rules answered, "ai_error" says why.
    fitting_ids: limit tags to these (e.g. the fittings a unit type has).
    unit_type: tells Claude the home type (the keyword rules don't need it).
    """
    allowed = tuple(sorted(f for f in (NAMES if fitting_ids is None else fitting_ids) if f in NAMES))
    if not (note or "").strip() or not allowed or not ai_on():
        return keyword_tag(note, unit_type, fitting_ids)
    # The non-anthropic errors come first: the except lines are only looked at in order.
    try:
        return _from_answer(note, _ask_claude(note, unit_type, allowed), allowed)
    except NoAnswer as e:
        why, error = str(e), e
    except (ValueError, KeyError, TypeError) as e:   # an answer in the wrong shape
        why, error = "Claude's answer couldn't be read", e
    except anthropic.APIConnectionError as e:        # offline, or no answer in time
        why, error = "couldn't reach Claude", e
    except anthropic.RateLimitError as e:
        why, error = "Claude is busy right now", e
    except anthropic.APIStatusError as e:            # e.g. 401: the API key is wrong
        why, error = f"Claude's API returned an error ({e.status_code})", e
    log.warning("AI tagging fell back to the keyword rules: %s (%r)", why, error)
    result = keyword_tag(note, unit_type, fitting_ids)
    result["ai_error"] = why
    return result


def _score(notes, read=keyword_tag):
    correct, misses = 0, []
    for note, truth in notes:
        t = read(note)["tags"]
        got = t[0]["fitting_id"] if t else None
        if got == truth:
            correct += 1
        else:
            misses.append({"note": note, "expected": truth, "got": got})
    return {"n": len(notes), "correct": correct, "misses": misses}


def evaluate(ripouts=None, read=keyword_tag):
    """
    Accuracy of the top tag. read: the tagger to test, the keyword rules by default
    (free and instant, so the AI tagging page shows these). read=tag tests Claude.
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
            if (t := read(note)["tags"]) and t[0]["fitting_id"] == truth
        )
        out["sample"] = {"n": len(rows), "correct": correct}
    out["tuning"] = _score(TUNING_NOTES, read)
    out["held_out"] = _score(HELD_OUT, read)
    return out


def _claude_only(note):
    """tag(), but stop instead of quietly scoring the keyword rules if Claude can't answer."""
    r = tag(note)
    if r["engine"] != "ai":
        raise SystemExit(f"Stopped: {r.get('ai_error', 'AI tagging is off')}")
    return r


if __name__ == "__main__":
    import sys
    ai = "--ai" in sys.argv[1:]
    if ai:
        if not ai_on():
            raise SystemExit("AI tagging is off: pip install anthropic, then set ANTHROPIC_API_KEY.")
        print(f"Claude ({MODEL}) on the test notes ({len(TUNING_NOTES) + len(HELD_OUT)} API calls)")
        r = evaluate(read=_claude_only)
    else:
        from impact import load_data
        r = evaluate(load_data()["ripouts"])
        s = r["sample"]
        print(f"Sample notes: {s['correct']}/{s['n']} ({s['correct'] / s['n']:.0%}) - not a fair test")
    u, h = r["tuning"], r["held_out"]
    # only the keyword rules were tuned to TUNING_NOTES
    print(f"Tuning notes: {u['correct']}/{u['n']} ({u['correct'] / u['n']:.0%}){'' if ai else ' - not a fair test'}")
    print(f"Held-out notes: {h['correct']}/{h['n']} ({h['correct'] / h['n']:.0%})")
    for m in (u["misses"] if ai else []) + h["misses"]:
        print("  missed:", m)
