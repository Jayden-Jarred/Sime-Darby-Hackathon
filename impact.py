"""
impact.py - the Right-Fit Homes impact calculations (Member 4).

Everything the other screens show comes from here:
  - load_data(), get_fitting(), get_upgrade()   read the CSVs, look up one row
  - impact_of()          cost and carbon of ONE buyer choice (for the Advisor screen)
  - save_buyer_choices() append a buyer's Advisor choices to choices.csv
  - add_ripout_report()  append an owner's tagged report to ripouts.csv
  - ripout_index()       share of owners who removed each fitting
  - advice_for(), design_feedback()   "stop installing X in unit type B" advice
  - simulate()           the What-if projection for a whole launch
  - reuse_carbon_kg(), reuse_summary()   Neighbour Match carbon and results
  - choice_impacts(), impact_by_fitting()   every buyer choice, and per fitting
  - upgrade_mix()        which upgrade options buyers pick, per fitting
  - dashboard_totals()   the KPI cards on the SDP dashboard

All inputs come from the CSV files in data/ (see README.md for columns).
All figures are SIMULATED: made-up homes and owners, with realistic fitting
figures from public sources (see generate_dummy_data.py and README.md).
"""

from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).parent / "data"

# ---- Assumptions (shown on the dashboard so judges can see them) ----------
STOP_THRESHOLD = 0.50    # rip-out rate at or above this -> "Stop installing"
OFFER_THRESHOLD = 0.30   # at or above this -> "Offer as opt-out"
TRANSPORT_KGCO2E_PER_KM = 0.25   # assumption: small van, per km, one way
CHOICES = ("keep", "opt_out", "upgrade")


# ---- Loading ---------------------------------------------------------------
def load_data(data_dir=DATA_DIR):
    """Read the five CSV files into DataFrames."""
    data_dir = Path(data_dir)
    data = {
        "fittings": pd.read_csv(data_dir / "fittings.csv"),
        "upgrades": pd.read_csv(data_dir / "upgrades.csv"),
        "ripouts": pd.read_csv(data_dir / "ripouts.csv"),
        # keep_default_na: an empty upgrade_id stays "" instead of NaN
        "choices": pd.read_csv(data_dir / "choices.csv", keep_default_na=False),
        "matches": pd.read_csv(data_dir / "matches.csv"),
    }
    if "upgrade_id" not in data["choices"]:
        raise ValueError("data/choices.csv is from before upgrade options: run python generate_dummy_data.py")
    return data


def get_fitting(fittings, unit_type, fitting_id):
    """Return one fitting's row as a dict, or raise KeyError."""
    row = fittings[(fittings.unit_type == unit_type) & (fittings.fitting_id == fitting_id)]
    if row.empty:
        raise KeyError(f"No fitting {fitting_id} for unit type {unit_type}")
    return row.iloc[0].to_dict()


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
def impact_of(fittings, unit_type, fitting_id, choice, upgrade_id=None, upgrades=None):
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
                With `upgrades` (the upgrades.csv table), the margin and name
                come from the option `upgrade_id` (default: the first one).
                Without it, the margin is the fitting's upgrade_margin_rm.

    Carbon counted = embodied carbon of the standard item that is no longer
    made (weight_kg x carbon_factor). Assumes the buyer would otherwise have
    removed it - that is why only frequently removed items are offered.
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
        "upgrade_revenue_rm": 0.0,
        "upgrade_id": None,       # which upgrade option (upgrade only)
        "upgrade_name": None,
    }
    if choice == "keep":
        return result

    result["material_avoided_kg"] = float(f["weight_kg"])
    result["carbon_avoided_kg"] = float(f["weight_kg"] * f["carbon_factor"])

    if choice == "opt_out":
        result["sdp_saving_rm"] = float(f["install_cost_rm"] - f["credit_rm"])
        result["buyer_saving_rm"] = float(f["credit_rm"] + f["removal_cost_rm"])
        result["buyer_credit_rm"] = float(f["credit_rm"])
    else:  # upgrade
        result["upgrade_revenue_rm"] = float(f["upgrade_margin_rm"])
        if upgrades is not None:
            up = get_upgrade(upgrades, unit_type, fitting_id, upgrade_id)
            result["upgrade_revenue_rm"] = float(up["margin_rm"])
            result["upgrade_id"], result["upgrade_name"] = up["upgrade_id"], up["name"]
        result["buyer_saving_rm"] = float(f["removal_cost_rm"])
    return result


def save_buyer_choices(unit_type, picks, data_dir=DATA_DIR, upgrade_picks=None):
    """
    Append one new buyer's Advisor choices to choices.csv, so the SDP
    dashboard includes them. `picks` maps fitting_id -> choice; eligible
    fittings not in `picks` are saved as "keep". Fixed fittings may be sent
    as "keep" (they always are) but aren't saved. `upgrade_picks` maps
    fitting_id -> upgrade_id for upgrades (default: the first option).
    Returns the new buyer_id.
    Raises ValueError for an unknown fitting or a choice that isn't allowed,
    KeyError for an unknown upgrade option.
    """
    upgrade_picks = upgrade_picks or {}
    data = load_data(data_dir)
    fittings = data["fittings"]
    unit_fittings = fittings[fittings.unit_type == unit_type]
    if unit_fittings.empty:
        raise ValueError(f"Unknown unit type {unit_type}")
    unknown = set(picks) - set(unit_fittings.fitting_id)
    if unknown:
        raise ValueError(f"Not a fitting for {unit_type}: {', '.join(sorted(unknown))}")
    # Every option named must exist for its fitting, even one the buyer isn't upgrading.
    for fid, uid in upgrade_picks.items():
        if not isinstance(uid, str):
            raise ValueError(f"Upgrade option for {fid} must be an upgrade_id")
        get_upgrade(data["upgrades"], unit_type, fid, uid)   # KeyError if unknown

    rows = []
    for fid, eligibility in zip(unit_fittings.fitting_id, unit_fittings.eligibility):
        imp = impact_of(fittings, unit_type, fid, picks.get(fid, "keep"),
                        upgrade_picks.get(fid), data["upgrades"])  # validates the choice
        if eligibility != "fixed":   # always installed, so not a choice to save
            rows.append((fid, imp["choice"], imp["upgrade_id"] or ""))

    existing = data["choices"].buyer_id
    n = existing[existing.str.startswith(unit_type + "-B")].str[-3:].astype(int).max()
    buyer_id = f"{unit_type}-B{(0 if pd.isna(n) else n) + 1:03d}"
    new = pd.DataFrame([(buyer_id, unit_type, fid, ch, up) for fid, ch, up in rows],
                       columns=["buyer_id", "unit_type", "fitting_id", "choice", "upgrade_id"])
    new.to_csv(Path(data_dir) / "choices.csv", mode="a", header=False, index=False)
    return buyer_id


def add_ripout_report(unit_type, fitting_ids, note, data_dir=DATA_DIR):
    """
    Add one owner's renovation report to ripouts.csv: removed=1 for the tagged
    fittings, 0 for the rest of that unit type's fittings. Returns the owner_id.
    """
    data = load_data(data_dir)
    unit_fittings = list(data["fittings"][data["fittings"].unit_type == unit_type].fitting_id)
    if not unit_fittings:
        raise ValueError(f"Unknown unit type {unit_type}")
    if not all(isinstance(fid, str) for fid in fitting_ids):
        raise ValueError("fittings must be a list of fitting ids")
    unknown = set(fitting_ids) - set(unit_fittings)
    if unknown:
        raise ValueError(f"Not a fitting for {unit_type}: {', '.join(sorted(unknown))}")
    if not fitting_ids:
        raise ValueError("No fittings to record")
    existing = data["ripouts"].owner_id
    n = existing[existing.str.startswith(unit_type + "-O")].str[-3:].astype(int).max()
    owner = f"{unit_type}-O{(0 if pd.isna(n) else n) + 1:03d}"
    clean = " ".join(str(note or "").split())[:300]   # a missing note is blank, not "None"
    rows = [(owner, unit_type, fid, int(fid in fitting_ids), clean if fid in fitting_ids else "")
            for fid in unit_fittings]
    pd.DataFrame(rows, columns=["owner_id", "unit_type", "fitting_id", "removed", "note"]).to_csv(
        Path(data_dir) / "ripouts.csv", mode="a", header=False, index=False)
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


def advice_for(rate, eligibility):
    """Turn a rip-out rate into plain advice for SDP."""
    if eligibility == "fixed":
        return "Keep (required at handover)"
    if rate >= STOP_THRESHOLD:
        return "Stop installing as standard"
    if rate >= OFFER_THRESHOLD:
        # Upgrade-only items (e.g. tiles) can't be left out, only upgraded.
        return "Offer as upgrade" if eligibility == "upgrade_only" else "Offer as opt-out"
    return "Keep as standard"


def design_feedback(data, unit_type=None):
    """Rip-out index plus one line of advice per fitting."""
    idx = ripout_index(data, unit_type)
    idx["advice"] = [advice_for(r, e) for r, e in zip(idx.rate, idx.eligibility)]
    return idx


# ---- What-if simulator ----------------------------------------------------
# Fittings that can't be rehomed once removed (hacked-out tiles break;
# toilets and basins aren't offered for hygiene reasons).
NOT_REUSABLE = {"TIL-FLR", "SAN-BTH"}
AVG_TRIP_KM = 2.0          # assumption: average Neighbour Match delivery, one way
SIM_DEFAULTS = {"homes": 500, "uptake": 0.8, "upgrade_share": 0.4,
                "credit_mult": 1.0, "match_rate": 0.5, "programme_cost": 80000}


def simulate(data, unit_type, homes=SIM_DEFAULTS["homes"], uptake=SIM_DEFAULTS["uptake"],
             upgrade_share=SIM_DEFAULTS["upgrade_share"], credit_mult=SIM_DEFAULTS["credit_mult"],
             match_rate=SIM_DEFAULTS["match_rate"], programme_cost=SIM_DEFAULTS["programme_cost"]):
    """
    Project one launch of `homes` homes, using this unit type's rip-out rates.

    uptake         share of would-be rip-outs where the buyer acts before handover
    upgrade_share  of those buyers, the share who upgrade (the rest opt out)
    credit_mult    credit as a multiple of today's credit (1.0 = as in fittings.csv)
    match_rate     share of still-removed reusable fittings rehomed by Neighbour Match
    programme_cost SDP's cost to run Right-Fit for this launch (assumption, RM)
    """
    idx = ripout_index(data, unit_type)[["fitting_id", "rate"]]
    f = data["fittings"][data["fittings"].unit_type == unit_type].merge(idx, on="fitting_id")
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


def reuse_summary(data, unit_type=None):
    """How many listed items were rehomed, and the net carbon saved."""
    m = data["matches"]
    if unit_type:
        m = m[m.unit_type == unit_type]
    listed = len(m)
    collected = m[m.status == "collected"].merge(
        data["fittings"], on=["unit_type", "fitting_id"], how="left")
    carbon_saved = reuse_carbon_kg(collected.weight_kg, collected.carbon_factor,
                                   collected.distance_km.astype(float)).sum()
    return {
        "listed": listed,
        "collected": len(collected),
        "reuse_rate": (len(collected) / listed) if listed else 0.0,
        "material_reused_kg": float(collected.weight_kg.sum()),
        "carbon_saved_kg": float(carbon_saved),
    }


# ---- Dashboard ------------------------------------------------------------
def choice_impacts(data, unit_type=None):
    """impact_of() applied to every buyer choice, as one table."""
    c = data["choices"]
    if unit_type:
        c = c[c.unit_type == unit_type]
    rows = [impact_of(data["fittings"], u, f, ch, up or None, data["upgrades"])
            for u, f, ch, up in zip(c.unit_type, c.fitting_id, c.choice, c.upgrade_id)]
    return pd.DataFrame(rows)


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
    launch's specs. One row per option in upgrades.csv (in that order), with
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
    # Most-upgraded fittings first; options keep their upgrades.csv order.
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
