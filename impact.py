"""
impact.py - the Right-Fit Homes impact calculations (Member 4).

Everything the other screens show comes from here:
  - UNIT_TYPES, parse_person()   the home types; what a person id (T2S-O001) says
  - load_data(), get_fitting(), get_upgrade(), unit_fittings()   read the database, look up rows
  - locked, next_id()    saves take turns; the next id to hand out
  - impact_of()          cost and carbon of ONE buyer choice (for the Advisor screen)
  - save_buyer_choices() save a buyer's Advisor choices to the choices table (new or signed-in buyer)
  - add_ripout_report()  save an owner's tagged report to the ripouts table (new or signed-in owner)
  - ripout_index()       share of owners who removed each fitting
  - advice(), advice_for(), design_feedback()   "stop installing X in unit type B" advice
  - saved_choices()      a buyer's saved choices, to fill in the Advisor again
  - simulate()           the What-if projection for a whole launch
  - reuse_carbon_kg(), rehomed_carbon_kg(), reuse_summary()   Neighbour Match carbon and results
  - choice_impacts(), impact_by_fitting()   every buyer choice, and per fitting
  - upgrade_mix()        which upgrade options buyers pick, per fitting
  - dashboard_totals()   the KPI cards on the SDP dashboard

All inputs come from the SQLite database data/right_fit.db (db.py; README.md lists the tables).
All figures are SIMULATED: made-up homes and owners, with realistic fitting
figures from public sources (see generate_dummy_data.py and README.md).
"""

import functools
import re
import threading

import pandas as pd

import db

DATA_DIR = db.DATA_DIR

# The house designs (the unit_types table is built from this).
UNIT_TYPES = {
    "T2S": "Double-storey terrace 20' x 70'",
    "C3R": "3-room condominium",
}

# A person id: home type, O (homeowner) or B (buyer moving in), number. T2S-O001, C3R-B025.
PERSON_ID = re.compile(r"([A-Z0-9]+)-([OB])(\d+)")
ROLES = {"O": "owner", "B": "buyer"}


def parse_person(person_id):
    """What an id says: T2S-O001 -> ("T2S", "owner"), T2S-B025 -> ("T2S", "buyer"); anything else -> (None, None)."""
    m = PERSON_ID.fullmatch(person_id) if isinstance(person_id, str) else None
    return (m[1], ROLES[m[2]]) if m else (None, None)

# ---- Assumptions (shown on the dashboard so judges can see them) ----------
STOP_THRESHOLD = 0.50    # rip-out rate at or above this -> "Stop installing"
OFFER_THRESHOLD = 0.30   # at or above this -> "Offer as opt-out"
TRANSPORT_KGCO2E_PER_KM = 0.25   # assumption: small van, per km, one way
CHOICES = ("keep", "opt_out", "upgrade")


# ---- Loading and saving ----------------------------------------------------
# A save reads the data, decides (the next id, the nearest neighbour) and then
# writes. Each write is one database transaction, but two saves deciding at the
# same moment could still pick the same id, so every read and save takes this
# lock in turn. One lock is enough: the app runs as one process. Re-entrant,
# because a reset replays saves while holding it.
DATA_LOCK = threading.RLock()


def locked(fn):
    """Decorator: run `fn` while holding DATA_LOCK."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        with DATA_LOCK:
            return fn(*args, **kwargs)
    return wrapper


def next_id(ids, prefix):
    """The next id after the highest one with this prefix: T2S-B101 after T2S-B100, L1000 after L999."""
    nums = [int(i[len(prefix):]) for i in ids
            if isinstance(i, str) and i.startswith(prefix) and i[len(prefix):].isdigit()]
    return f"{prefix}{max(nums, default=0) + 1:03d}"


MATCH_TEXT = ["to_owner", "condition", "note", "posted_at", "matched_at", "collected_at"]


@locked
def load_data(data_dir=DATA_DIR):
    """Every table of the database as a DataFrame: fittings, upgrades, people, ripouts, choices, matches, requests, messages."""
    if not db.exists(data_dir):
        raise ValueError(f"No database in {data_dir}: run python generate_dummy_data.py (or just start the app)")
    data = db.read_tables(data_dir)
    # Empty text is NULL in the database; the pages and maths expect "" for these.
    for table, cols in (("choices", ["upgrade_id"]), ("requests", ["listing_id", "note"]), ("matches", MATCH_TEXT)):
        for col in cols:
            data[table][col] = data[table][col].fillna("").astype(str)
    return data   # matches.distance_km stays a number: NaN until matched


def get_fitting(fittings, unit_type, fitting_id):
    """Return one fitting's row as a dict, or raise KeyError."""
    row = fittings[(fittings.unit_type == unit_type) & (fittings.fitting_id == fitting_id)]
    if row.empty:
        raise KeyError(f"No fitting {fitting_id} for unit type {unit_type}")
    return row.iloc[0].to_dict()


def unit_fittings(data, unit_type):
    """This home type's rows of the fittings table, indexed by fitting_id (empty for an unknown type)."""
    f = data["fittings"]
    return f[f.unit_type == unit_type].set_index("fitting_id", drop=False)


def get_upgrade(upgrades, unit_type, fitting_id, upgrade_id=None):
    """One upgrade option as a dict: `upgrade_id`, or the fitting's first (default) option. Raises KeyError."""
    rows = upgrades[(upgrades.unit_type == unit_type) & (upgrades.fitting_id == fitting_id)]
    if upgrade_id:
        rows = rows[rows.upgrade_id == upgrade_id]
    if rows.empty:
        raise KeyError(f"No upgrade {upgrade_id} for {fitting_id}" if upgrade_id
                       else f"No upgrade options for {fitting_id}")
    return rows.iloc[0].to_dict()


# ---- One choice -----------------------------------------------------------
def impact_of(fittings, unit_type, fitting_id, choice, upgrade_id=None, upgrades=None,
              ripout_rate=None):
    """
    Cost and carbon of ONE buyer choice for ONE fitting.

    keep     -> nothing saved.
    opt_out  -> the fitting is never made or installed.
                SDP saves the install cost minus the credit it gives the buyer.
                The buyer gets the credit and avoids paying to rip it out.
    upgrade  -> SDP installs the buyer's preferred version instead of the
                standard one the buyer would have torn out. The standard
                item is never made, SDP earns the upgrade margin, and the
                buyer avoids the rip-out cost.
                With `upgrades` (the upgrades table), the margin and name
                come from the option `upgrade_id` (default: the first one).
                Without it, the margin is the fitting's upgrade_margin_rm.

    Carbon counted = embodied carbon of the standard item that is no longer
    made (weight_kg x carbon_factor), and only when the buyer would otherwise
    have ripped it out. We take that as true when at least OFFER_THRESHOLD of
    owners remove the fitting (`ripout_rate`, from ripout_index). Below that,
    the choice still saves money but counts no carbon or material
    (`carbon_counted` False). With no `ripout_rate`, carbon is counted.

    `working` = the sums behind the numbers, as short lines for the screen.
    """
    if choice not in CHOICES:
        raise ValueError(f"choice must be one of {CHOICES}, got {choice!r}")

    f = get_fitting(fittings, unit_type, fitting_id)
    allowed = {
        "opt_out": {"keep", "opt_out", "upgrade"},
        "upgrade_only": {"keep", "upgrade"},
        "fixed": {"keep"},
    }[f["eligibility"]]
    if choice not in allowed:
        raise ValueError(f"{f['name']} is '{f['eligibility']}', so '{choice}' is not allowed")

    result = {
        "unit_type": unit_type,
        "fitting_id": fitting_id,
        "name": f["name"],
        "choice": choice,
        "material_avoided_kg": 0.0,
        "carbon_avoided_kg": 0.0,
        "sdp_saving_rm": 0.0,
        "buyer_saving_rm": 0.0,
        "buyer_credit_rm": 0.0,   # part of buyer_saving_rm paid as a credit
        "ripout_skipped_rm": 0.0, # part of buyer_saving_rm: the rip-out they don't pay for
        "upgrade_revenue_rm": 0.0,
        "upgrade_id": None,       # which upgrade option (upgrade only)
        "upgrade_name": None,
        "carbon_counted": False,
        "working": [],
    }
    if choice == "keep":
        return result

    kg, factor = float(f["weight_kg"]), float(f["carbon_factor"])
    counted = ripout_rate is None or ripout_rate >= OFFER_THRESHOLD
    result["carbon_counted"] = counted
    if counted:
        result["material_avoided_kg"] = kg
        result["carbon_avoided_kg"] = kg * factor
    result["ripout_skipped_rm"] = float(f["removal_cost_rm"])

    if choice == "opt_out":
        result["sdp_saving_rm"] = float(f["install_cost_rm"] - f["credit_rm"])
        result["buyer_credit_rm"] = float(f["credit_rm"])
    else:  # upgrade
        result["upgrade_revenue_rm"] = float(f["upgrade_margin_rm"])
        if upgrades is not None:
            up = get_upgrade(upgrades, unit_type, fitting_id, upgrade_id)
            result["upgrade_revenue_rm"] = float(up["margin_rm"])
            result["upgrade_id"], result["upgrade_name"] = up["upgrade_id"], up["name"]
    result["buyer_saving_rm"] = result["buyer_credit_rm"] + result["ripout_skipped_rm"]
    result["working"] = _working(result, f, kg, factor, ripout_rate)
    return result


def _working(r, f, kg, factor, ripout_rate):
    """The sums behind one choice, in words, so the screen can show its working."""
    rm = lambda v: f"RM{v:,.0f}"
    if r["carbon_counted"]:
        carbon = f"Carbon: {kg:g} kg × {factor:g} kg CO₂e per kg = {r['carbon_avoided_kg']:,.0f} kg CO₂e never made"
    else:
        carbon = (f"Carbon: not counted. Only {ripout_rate:.0%} of owners remove this, below the "
                  f"{OFFER_THRESHOLD:.0%} we need to say it would have been ripped out")
    if r["choice"] == "opt_out":
        you = (f"You: {rm(r['buyer_credit_rm'])} credit + {rm(r['ripout_skipped_rm'])} rip-out you skip "
               f"= {rm(r['buyer_saving_rm'])}")
        sdp = (f"SDP: {rm(f['install_cost_rm'])} installation skipped − {rm(r['buyer_credit_rm'])} credit "
               f"= {rm(r['sdp_saving_rm'])} saved")
    else:
        you = f"You: {rm(r['ripout_skipped_rm'])} rip-out you skip (SDP quotes the upgrade price)"
        sdp = f"SDP: {rm(r['upgrade_revenue_rm'])} margin on the {r['upgrade_name'] or 'upgrade'}"
    return [carbon, you, sdp]


@locked
def save_buyer_choices(unit_type, picks, data_dir=DATA_DIR, upgrade_picks=None, buyer_id=None):
    """
    Save one buyer's Advisor choices to the choices table, so the SDP dashboard
    includes them. `picks` maps fitting_id -> choice; eligible fittings not in
    `picks` are saved as "keep". Fixed fittings may be sent as "keep" (they
    always are) but aren't saved. `upgrade_picks` maps fitting_id -> upgrade_id
    for upgrades (default: the first option).
    `buyer_id` (the signed-in buyer, e.g. T2S-B025) replaces that buyer's
    earlier choices, so a buyer who confirms again is still one buyer. Without
    it, the choices are saved as a new buyer. Returns the buyer_id.
    Raises ValueError for an unknown fitting, a choice that isn't allowed or a
    buyer_id from another home type, KeyError for an unknown upgrade option.
    """
    _check_person_id(buyer_id, unit_type, "buyer")
    upgrade_picks = upgrade_picks or {}
    data = load_data(data_dir)
    fittings = data["fittings"]
    fits = unit_fittings(data, unit_type)
    if fits.empty:
        raise ValueError(f"Unknown unit type {unit_type}")
    unknown = set(picks) - set(fits.fitting_id)
    if unknown:
        raise ValueError(f"Not a fitting for {unit_type}: {', '.join(sorted(unknown))}")
    # Every option named must exist for its fitting, even one the buyer isn't upgrading.
    for fid, uid in upgrade_picks.items():
        if not isinstance(uid, str):
            raise ValueError(f"Upgrade option for {fid} must be an upgrade_id")
        get_upgrade(data["upgrades"], unit_type, fid, uid)   # KeyError if unknown

    rows = []
    for fid, eligibility in zip(fits.fitting_id, fits.eligibility):
        imp = impact_of(fittings, unit_type, fid, picks.get(fid, "keep"),
                        upgrade_picks.get(fid), data["upgrades"])  # validates the choice
        if eligibility != "fixed":   # always installed, so not a choice to save
            rows.append((fid, imp["choice"], imp["upgrade_id"] or ""))

    if buyer_id is None:
        buyer_id = next_id(data["people"].person_id, f"{unit_type}-B")
    with db.transaction(data_dir) as con:   # all of this buyer's choices are saved, or none
        db.ensure_person(con, buyer_id, unit_type, "buyer")
        db.delete(con, "choices", {"buyer_id": buyer_id})   # confirming again replaces them
        db.insert_many(con, "choices", ["buyer_id", "unit_type", "fitting_id", "choice", "upgrade_id"],
                       [(buyer_id, unit_type, fid, ch, up) for fid, ch, up in rows])
    return buyer_id


def _check_person_id(person_id, unit_type, role):
    """None (a new person), or a `role` ("buyer"/"owner") id of this home type. Raises ValueError otherwise."""
    if person_id is not None and parse_person(person_id) != (unit_type, role):
        letter = "B" if role == "buyer" else "O"
        raise ValueError(f"{person_id} isn't a {'homeowner' if role == 'owner' else role} id for this "
                         f"home type (expected {unit_type}-{letter}…)")


@locked
def add_ripout_report(unit_type, fitting_ids, note, data_dir=DATA_DIR, owner_id=None):
    """
    Save one owner's renovation report to the ripouts table. A new owner gets a row per
    fitting of the unit type: removed=1 for the tagged fittings, 0 for the rest.
    `owner_id` (the signed-in owner, e.g. T2S-O001) adds the tagged fittings to
    that owner's existing rows instead, so one owner never counts twice in the
    rip-out index. Returns the owner_id.
    """
    _check_person_id(owner_id, unit_type, "owner")
    data = load_data(data_dir)
    fits = list(unit_fittings(data, unit_type).fitting_id)
    if not fits:
        raise ValueError(f"Unknown unit type {unit_type}")
    if not all(isinstance(fid, str) for fid in fitting_ids):
        raise ValueError("fittings must be a list of fitting ids")
    unknown = set(fitting_ids) - set(fits)
    if unknown:
        raise ValueError(f"Not a fitting for {unit_type}: {', '.join(sorted(unknown))}")
    if not fitting_ids:
        raise ValueError("No fittings to record")
    rip = data["ripouts"]
    clean = " ".join(str(note or "").split())[:300]   # a missing note is blank, not "None"
    owner = owner_id or next_id(data["people"].person_id, f"{unit_type}-O")
    have = set(rip.fitting_id[rip.owner_id == owner])   # fittings this owner already has a row for
    with db.transaction(data_dir) as con:   # the whole report is saved, or none of it
        db.ensure_person(con, owner, unit_type, "owner")
        for fid in fitting_ids:
            if fid in have:
                db.update(con, "ripouts", {"removed": 1, "note": clean}, {"owner_id": owner, "fitting_id": fid})
        db.insert_many(con, "ripouts", ["owner_id", "unit_type", "fitting_id", "removed", "note"],
                       [(owner, unit_type, fid, int(fid in fitting_ids), clean if fid in fitting_ids else "")
                        for fid in fits if fid not in have])
    return owner


# ---- Rip-out index and design feedback ------------------------------------
def ripout_index(data, unit_type=None):
    """Share of owners who removed each fitting, per unit type."""
    r = data["ripouts"]
    if unit_type:
        r = r[r.unit_type == unit_type]
    idx = (r.groupby(["unit_type", "fitting_id"])
             .agg(owners=("owner_id", "nunique"), removed=("removed", "sum"))
             .reset_index())
    idx["rate"] = idx.removed / idx.owners
    names = data["fittings"][["unit_type", "fitting_id", "name", "eligibility"]]
    idx = idx.merge(names, on=["unit_type", "fitting_id"], how="left")
    return idx.sort_values("rate", ascending=False).reset_index(drop=True)


def advice(rate, eligibility):
    """
    A rip-out rate as advice for SDP: (key, words). The key ("stop", "offer" or "keep")
    picks the colour and icon on every page, so rewording the advice never recolours it.
    """
    if eligibility == "fixed":
        return "keep", "Keep (required at handover)"
    if rate >= STOP_THRESHOLD:
        return "stop", "Stop installing as standard"
    if rate >= OFFER_THRESHOLD:
        # Upgrade-only items (e.g. tiles) can't be left out, only upgraded.
        return "offer", "Offer as upgrade" if eligibility == "upgrade_only" else "Offer as opt-out"
    return "keep", "Keep as standard"


def advice_for(rate, eligibility):
    """The advice's words alone (see advice())."""
    return advice(rate, eligibility)[1]


def design_feedback(data, unit_type=None):
    """Rip-out index plus one line of advice per fitting (advice) and its colour key (advice_key)."""
    idx = ripout_index(data, unit_type)
    keys, words = zip(*[advice(r, e) for r, e in zip(idx.rate, idx.eligibility)]) if len(idx) else ((), ())
    idx["advice_key"], idx["advice"] = list(keys), list(words)
    return idx


def saved_choices(data, buyer_id):
    """A buyer's saved choices, fitting_id -> {"choice", "upgrade_id"}, to fill in the Advisor again."""
    c = data["choices"]
    mine = c[c.buyer_id == buyer_id]
    return {fid: {"choice": ch, "upgrade_id": up} for fid, ch, up in zip(mine.fitting_id, mine.choice, mine.upgrade_id)}


# ---- What-if simulator ----------------------------------------------------
# Fittings that can't be rehomed once removed (hacked-out tiles break;
# toilets and basins aren't offered for hygiene reasons).
NOT_REUSABLE = {"TIL-FLR", "SAN-BTH"}
AVG_TRIP_KM = 2.0          # assumption: average Neighbour Match delivery, one way
SIM_DEFAULTS = {"homes": 100, "uptake": 0.8, "upgrade_share": 0.4,
                "credit_mult": 1.0, "match_rate": 0.5, "programme_cost": 80000}


def simulate(data, unit_type, homes=SIM_DEFAULTS["homes"], uptake=SIM_DEFAULTS["uptake"],
             upgrade_share=SIM_DEFAULTS["upgrade_share"], credit_mult=SIM_DEFAULTS["credit_mult"],
             match_rate=SIM_DEFAULTS["match_rate"], programme_cost=SIM_DEFAULTS["programme_cost"]):
    """
    Project one launch of `homes` homes, using this unit type's rip-out rates.

    uptake         share of would-be rip-outs where the buyer acts before handover
    upgrade_share  of those buyers, the share who upgrade (the rest opt out)
    credit_mult    credit as a multiple of today's credit (1.0 = as in the fittings table)
    match_rate     share of still-removed reusable fittings rehomed by Neighbour Match
    programme_cost SDP's cost to run Right-Fit for this launch (assumption, RM)
    """
    idx = ripout_index(data, unit_type)[["fitting_id", "rate"]]
    f = unit_fittings(data, unit_type).reset_index(drop=True).merge(idx, on="fitting_id")
    rows = []
    for r in f.to_dict("records"):
        would = homes * r["rate"]
        choosers = 0.0 if r["eligibility"] == "fixed" else would * uptake
        up = choosers if r["eligibility"] == "upgrade_only" else choosers * upgrade_share
        opt = choosers - up
        credit = r["credit_rm"] * credit_mult
        still = would - choosers
        rehomed = 0.0 if r["fitting_id"] in NOT_REUSABLE else still * match_rate
        kg_co2 = r["weight_kg"] * r["carbon_factor"]
        rows.append({
            "fitting_id": r["fitting_id"], "name": r["name"], "rate": r["rate"],
            "would_remove": would, "opted_out": opt, "upgraded": up, "rehomed": rehomed,
            "prevented_kg": choosers * r["weight_kg"],
            "reused_kg": rehomed * r["weight_kg"],
            "wasted_kg": (still - rehomed) * r["weight_kg"],
            "baseline_kg": would * r["weight_kg"],
            "carbon_prevented_kg": choosers * kg_co2,
            "carbon_reused_kg": rehomed * reuse_carbon_kg(r["weight_kg"], r["carbon_factor"], AVG_TRIP_KM),
            "sdp_saving_rm": opt * (r["install_cost_rm"] - credit),
            "upgrade_revenue_rm": up * r["upgrade_margin_rm"],
            "buyer_saving_rm": opt * (credit + r["removal_cost_rm"]) + up * r["removal_cost_rm"],
        })
    df = pd.DataFrame(rows)
    t = {k: float(df[k].sum()) for k in df.columns if k.endswith(("_kg", "_rm")) or k in ("opted_out", "upgraded", "rehomed")}
    gross = t["sdp_saving_rm"] + t["upgrade_revenue_rm"]
    per_home = gross / homes if homes else 0.0
    t.update({
        "homes": homes,
        "carbon_total_kg": t["carbon_prevented_kg"] + t["carbon_reused_kg"],
        "programme_cost_rm": float(programme_cost),
        "sdp_net_rm": gross - programme_cost,
        "per_home_benefit_rm": per_home,
        "payback_homes": (int(-(-programme_cost // per_home)) if per_home > 0 else None),
        "waste_avoided_share": ((t["prevented_kg"] + t["reused_kg"]) / t["baseline_kg"]) if t["baseline_kg"] else 0.0,
    })
    per_fitting = df.sort_values("baseline_kg", ascending=False).round(1).to_dict("records")
    return {"totals": t, "fittings": per_fitting}


# ---- Neighbour Match ------------------------------------------------------
def reuse_carbon_kg(weight_kg, carbon_factor, distance_km):
    """
    Net carbon saved by rehoming one item: its embodied carbon (it isn't made
    new) minus the round trip to collect and deliver it. Works on single
    values or pandas columns. Used by the dashboard, the What-if and the map.
    """
    return weight_kg * carbon_factor - distance_km * 2 * TRANSPORT_KGCO2E_PER_KM


def rehomed_carbon_kg(fitting, distance_km):
    """reuse_carbon_kg for one fitting row (anything with weight_kg and carbon_factor), rounded to 0.1 kg.
    A distance of None counts no trip."""
    return round(float(reuse_carbon_kg(float(fitting["weight_kg"]), float(fitting["carbon_factor"]),
                                       distance_km or 0)), 1)


def reuse_summary(data, unit_type=None):
    """
    Neighbour Match results. reuse_rate is the proposal's KPI: the share of
    removed items rehomed, i.e. fittings collected by a neighbour out of every
    reusable fitting owners reported removing (listed on Neighbour Match or not).
    Carbon counts only collected fittings, minus their delivery trips.
    """
    m, r = data["matches"], data["ripouts"]
    if unit_type:
        m, r = m[m.unit_type == unit_type], r[r.unit_type == unit_type]
    removed = int(((r.removed == 1) & ~r.fitting_id.isin(NOT_REUSABLE)).sum())
    collected = m[m.status == "collected"].merge(
        data["fittings"], on=["unit_type", "fitting_id"], how="left")
    carbon_saved = reuse_carbon_kg(collected.weight_kg, collected.carbon_factor,
                                   collected.distance_km.astype(float)).sum()
    return {
        "removed": removed,
        "listed": len(m),
        "collected": len(collected),
        "reuse_rate": (len(collected) / removed) if removed else 0.0,
        "material_reused_kg": float(collected.weight_kg.sum()),
        "carbon_saved_kg": float(carbon_saved),
    }


# ---- Dashboard ------------------------------------------------------------
def ripout_rates(data, unit_type=None):
    """{(unit_type, fitting_id): rip-out rate}, for impact_of(ripout_rate=...)."""
    idx = ripout_index(data, unit_type)
    return dict(zip(zip(idx.unit_type, idx.fitting_id), idx.rate))


def choice_impacts(data, unit_type=None):
    """
    impact_of() applied to every buyer choice, as one table (carbon only for often-removed fittings).
    Each distinct (home type, fitting, choice, upgrade) is worked out once and shared by every
    buyer who made it, so the dashboard stays quick however many buyers confirm.
    """
    c = data["choices"]
    if unit_type:
        c = c[c.unit_type == unit_type]
    rates = ripout_rates(data, unit_type)
    worked = {}
    for key in set(zip(c.unit_type, c.fitting_id, c.choice, c.upgrade_id)):
        u, f, ch, up = key
        worked[key] = impact_of(data["fittings"], u, f, ch, up or None, data["upgrades"], rates.get((u, f)))
    return pd.DataFrame([worked[key] for key in zip(c.unit_type, c.fitting_id, c.choice, c.upgrade_id)])


def impact_by_fitting(data, unit_type=None):
    """Opt-outs, upgrades, carbon and money per fitting - for the table."""
    imp = choice_impacts(data, unit_type)
    if imp.empty:
        return imp
    grouped = imp.groupby(["fitting_id", "name"]).agg(
        opt_outs=("choice", lambda s: (s == "opt_out").sum()),
        upgrades=("choice", lambda s: (s == "upgrade").sum()),
        carbon_avoided_kg=("carbon_avoided_kg", "sum"),
        sdp_saving_rm=("sdp_saving_rm", "sum"),
        upgrade_revenue_rm=("upgrade_revenue_rm", "sum"),
    ).reset_index()
    return grouped.sort_values("carbon_avoided_kg", ascending=False).reset_index(drop=True)


def upgrade_mix(data, unit_type=None):
    """
    Which upgrade option buyers picked, per fitting - for planning next
    launch's specs. One row per option in the upgrades table (in that order), with
    picks, share of that fitting's upgrades (0-1) and the margin earned.
    Options nobody picked are kept with 0, so SDP can see what to drop.
    Upgrades saved without an option count as the default, as in impact_of().
    """
    keys = ["unit_type", "fitting_id", "upgrade_id"]
    mix = data["upgrades"]
    if unit_type:
        mix = mix[mix.unit_type == unit_type]
    mix = mix[keys + ["name", "margin_rm"]].rename(columns={"name": "upgrade_name"})
    imp = choice_impacts(data, unit_type)
    if imp.empty:
        mix = mix.assign(picks=0, margin_earned_rm=0.0)
    else:
        picked = imp[imp.choice == "upgrade"].groupby(keys).agg(
            picks=("choice", "size"), margin_earned_rm=("upgrade_revenue_rm", "sum")).reset_index()
        mix = mix.merge(picked, on=keys, how="left").fillna({"picks": 0, "margin_earned_rm": 0.0})
    mix["picks"] = mix.picks.astype(int)
    mix["fitting_upgrades"] = mix.groupby(["unit_type", "fitting_id"]).picks.transform("sum")
    # A fitting nobody upgraded has no mix yet: share 0, not 0/0.
    mix["share"] = (mix.picks / mix.fitting_upgrades.where(mix.fitting_upgrades > 0)).fillna(0.0)
    names = data["fittings"][["unit_type", "fitting_id", "name"]]
    mix = mix.merge(names, on=["unit_type", "fitting_id"], how="left")
    # Most-upgraded fittings first; options keep their upgrades-table order.
    mix["_order"] = range(len(mix))
    mix = mix.sort_values(["fitting_upgrades", "_order"], ascending=[False, True], kind="stable")
    return mix.drop(columns="_order").reset_index(drop=True)


def dashboard_totals(data, unit_type=None):
    """The numbers on the KPI cards."""
    imp = choice_impacts(data, unit_type)
    reuse = reuse_summary(data, unit_type)
    c = data["choices"]
    if unit_type:
        c = c[c.unit_type == unit_type]

    def total(col):
        return float(imp[col].sum()) if not imp.empty else 0.0

    return {
        "buyers": int(c.buyer_id.nunique()),
        "items_not_installed": int((imp.choice != "keep").sum()) if not imp.empty else 0,
        "material_avoided_kg": total("material_avoided_kg"),
        # Advisor choices plus Neighbour Match reuse (net of transport)
        "carbon_avoided_kg": total("carbon_avoided_kg") + reuse["carbon_saved_kg"],
        "sdp_saving_rm": total("sdp_saving_rm"),
        "upgrade_revenue_rm": total("upgrade_revenue_rm"),
        "buyer_saving_rm": total("buyer_saving_rm"),
        "reuse": reuse,
    }
