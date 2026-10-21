"""
dashboard.py - every page and the JSON API, as one Flask Blueprint (Member 4).

app.py plugs it into the main app with:

    from dashboard import dashboard_bp
    app.register_blueprint(dashboard_bp)

Pages (all take ?unit=T2S or ?unit=C3R):
    /advisor            buyer Fit-Out Advisor: keep / opt out / upgrade
    /dashboard          the SDP dashboard
    /match              Neighbour Match community: feed, give, ask, chat, collect, map
                        (&as=T2S-O001 picks which simulated neighbour you are)
    /simulate           What-if launch projection
    /tagger             AI tagging of messy renovation notes
API (JSON; bad input -> 400 with an "error"):
    GET  /api/impact?unit=T2S&fitting=KIT-CAB&choice=opt_out[&upgrade=QUARTZ]
    GET  /api/ripout-index?unit=T2S
    GET  /api/simulate?unit=T2S&homes=500&...       (limits: SIM_SLIDERS)
    POST /api/choices   {"unit", "choices", "upgrades"?}   saves a buyer
    POST /api/tag       {"unit", "note"}                  tags one note
    POST /api/report    {"unit", "note", "fittings"}      saves a rip-out report
    POST /api/match/list     {"unit", "owner", "fitting", "condition"?, "note"?, "request_id"?}
                                                                 offers a removed fitting
    POST /api/match/request  {"unit", "requester", "fitting", "note"?}   asks for one
    POST /api/match/claim    {"listing_id", "requester"}         takes one offer
    POST /api/match/comment  {"post_id", "author", "text"}       a message on a post
    POST /api/match/collect  {"listing_id", "by"?, "thanks"?}    marks it picked up
    POST /api/reset-demo     puts every data file back to the starting demo data
    GET  /export/<ripout-index|impact-by-fitting|upgrade-mix|choices>.csv?unit=T2S
"""

import io
import math

from flask import Blueprint, Response, abort, jsonify, make_response, render_template, request
import plotly.graph_objects as go

import generate_dummy_data
import community
import impact
import match_map
import neighbour_match
import tagger
from generate_dummy_data import UNIT_TYPES

dashboard_bp = Blueprint("dashboard", __name__)

# Shown in the 3D preview's info card. Fictional demo homes, not SDP drawings.
UNIT_INFO = {
    "T2S": {"title": "Double-storey terrace",
            "facts": ["20' × 70' lot", "2 storeys", "3 bedrooms"]},
    "C3R": {"title": "3-room condominium",
            "facts": ["Level 6 of 10", "3 bedrooms", "Balcony"]},
}

# Brand colours (see static/app.css).
INK = "#1c211d"
INK_2 = "#434c45"
MUTED = "#a39d90"
GRID = "#e4ddcf"
FONT = "Figtree, system-ui, sans-serif"
# Advice colours: set only here. The chart bars use them directly; every page's
# <body> gets them as CSS variables (--advice-stop ..., advice_css below) for the
# badges, the legend and the 3D model. Dark enough for the white icon on each.
ADVICE_COLOUR = {"stop": "#d03b3b", "offer": "#b98000", "keep": "#3f8f4a"}


@dashboard_bp.app_context_processor
def advice_css():
    """`advice_css` for every template: style="{{ advice_css }}" on <body>."""
    return {"advice_css": " ".join(f"--advice-{k}: {c};" for k, c in ADVICE_COLOUR.items())}


def advice_key(advice):
    if advice.startswith("Stop"):
        return "stop"
    if advice.startswith("Offer"):
        return "offer"
    return "keep"


def story(feedback):
    """
    The dashboard's headline, written from the data: the most-ripped-out
    fitting that buyers can choose about, e.g.
    "Kitchen cabinets are the #1 rip-out: 6 in 10 owners tear them out."
    """
    choosable = feedback[feedback.eligibility != "fixed"]
    if choosable.empty:
        return None
    top = choosable.iloc[0]
    plural = top["name"].endswith("s")
    k = max(1, round(top.rate * 10))
    return {
        "lead": f"{top['name']} {'are' if plural else 'is'} the #1 rip-out:",
        "emph": f"{k} in 10 owners",
        "tail": f"tear {'them' if plural else 'it'} out.",
        "fitting_id": top.fitting_id,
    }


def mix_by_fitting(mix):
    """impact.upgrade_mix() rows grouped into one entry per fitting, for the template."""
    cols = ["upgrade_id", "upgrade_name", "picks", "share", "margin_earned_rm"]
    return [{"fitting_id": fid, "name": name, "upgrades": int(rows.fitting_upgrades.iloc[0]),
             "options": rows[cols].to_dict("records")}
            for (fid, name), rows in mix.groupby(["fitting_id", "name"], sort=False)]


def _data():
    # Re-read every request so edited CSVs show up without a restart.
    return impact.load_data()


def _unit():
    unit = request.args.get("unit", "T2S")
    if unit not in UNIT_TYPES:
        if request.path.startswith("/api/"):
            # API callers get a JSON 400 they can show, like every other API error.
            abort(make_response(jsonify({"error": f"Unknown unit type {unit}"}), 400))
        abort(404, f"Unknown unit type {unit}")
    return unit


def _json_body():
    """The request's JSON object, or {} for anything else (a list, a string, bad JSON),
    so the POST routes answer 400 instead of crashing."""
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


def ripout_chart(feedback):
    """Horizontal bar chart of the rip-out index, with the advice thresholds."""
    df = feedback.sort_values("rate")  # biggest at the top
    pct = df.rate * 100
    fig = go.Figure(go.Bar(
        x=pct,
        y=df.name,
        orientation="h",
        marker=dict(color=[ADVICE_COLOUR[advice_key(a)] for a in df.advice], cornerradius=4),
        text=[f"{p:.0f}%" for p in pct],
        textposition="outside",
        textfont=dict(color=INK_2, size=12),
        customdata=list(zip(df.removed, df.owners, df.advice, df.fitting_id)),
        hovertemplate=("<b>%{y}</b><br>%{x:.0f}% of owners removed it"
                       "<br>%{customdata[0]} of %{customdata[1]} owners"
                       "<br>%{customdata[2]}<extra></extra>"),
        width=0.6,
    ))
    # Labels sit on opposite sides of their lines so they never overlap.
    for threshold, label, side in ((impact.OFFER_THRESHOLD, "Offer opt-out ", "right"),
                                   (impact.STOP_THRESHOLD, " Stop installing", "left")):
        x = threshold * 100
        fig.add_vline(x=x, line=dict(color=MUTED, width=1, dash="dot"))
        fig.add_annotation(x=x, y=1.0, yref="paper", yanchor="bottom", text=label,
                           showarrow=False, xanchor=side, font=dict(size=11, color=INK_2))
    fig.update_layout(
        height=60 + 44 * len(df),
        margin=dict(l=8, r=40, t=32, b=36),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=FONT, color=INK, size=14),
        xaxis=dict(range=[0, 100], ticksuffix="%", gridcolor=GRID, zeroline=False,
                   tickfont=dict(color=INK_2, size=12), title=None),
        # ticklabelstandoff: breathing room between the names and the bars
        yaxis=dict(tickfont=dict(color=INK, size=13), title=None, automargin=True,
                   ticklabelstandoff=12),
        showlegend=False,
        dragmode=False,   # a click shows the bar's fitting in 3D, so no drag-to-zoom
        hoverlabel=dict(bgcolor="#fffdf8", bordercolor=GRID, font=dict(color=INK, family=FONT)),
    )
    return fig.to_html(full_html=False, include_plotlyjs=False,
                       config={"displayModeBar": False, "responsive": True})


@dashboard_bp.route("/dashboard")
def dashboard():
    unit = _unit()
    data = _data()
    feedback = impact.design_feedback(data, unit)
    house_fittings = feedback[["fitting_id", "name", "eligibility", "owners",
                               "removed", "rate", "advice"]].to_dict("records")
    for row in house_fittings:  # numpy ints -> plain ints for JSON
        row["owners"], row["removed"] = int(row["owners"]), int(row["removed"])
    return render_template(
        "dashboard.html",
        unit=unit,
        unit_types=UNIT_TYPES,
        unit_info=UNIT_INFO[unit],
        house_fittings=house_fittings,
        story=story(feedback),
        totals=impact.dashboard_totals(data, unit),
        feedback=feedback.to_dict("records"),
        by_fitting=impact.impact_by_fitting(data, unit).to_dict("records"),
        upgrade_mix=mix_by_fitting(impact.upgrade_mix(data, unit)),
        chart=ripout_chart(feedback),
        stop=impact.STOP_THRESHOLD,
        offer=impact.OFFER_THRESHOLD,
        transport=impact.TRANSPORT_KGCO2E_PER_KM,
    )


@dashboard_bp.route("/api/impact")
def api_impact():
    """For Member 2's Advisor screen: the savings as the buyer clicks."""
    unit = _unit()
    fitting = request.args.get("fitting", "")
    choice = request.args.get("choice", "keep")
    upgrade = request.args.get("upgrade") or None
    data = _data()
    rate = impact.ripout_rates(data, unit).get((unit, fitting))
    try:
        return jsonify(impact.impact_of(data["fittings"], unit, fitting, choice, upgrade, data["upgrades"], rate))
    except (KeyError, ValueError) as e:
        # str() of a KeyError wraps the message in quotes, so read it from args.
        return jsonify({"error": e.args[0] if e.args else str(e)}), 400


@dashboard_bp.route("/advisor")
def advisor():
    """Buyer-facing Fit-Out Advisor: keep / opt out / upgrade per fitting."""
    unit = _unit()
    data = _data()
    idx = impact.ripout_index(data, unit)[["fitting_id", "owners", "removed", "rate"]]
    f = data["fittings"]
    rows = (f[f.unit_type == unit]
            .merge(idx, on="fitting_id", how="left")
            .sort_values("rate", ascending=False))
    rows["advice"] = [impact.advice_for(r, e) for r, e in zip(rows.rate, rows.eligibility)]
    records = rows.to_dict("records")
    ups = data["upgrades"][data["upgrades"].unit_type == unit]
    for r in records:
        r["owners"], r["removed"] = int(r["owners"]), int(r["removed"])
        r["upgrades"] = ups[ups.fitting_id == r["fitting_id"]][
            ["upgrade_id", "name", "description", "image"]].to_dict("records")
    house = [{k: r[k] for k in ("fitting_id", "name", "eligibility", "owners", "removed", "rate", "advice")}
             for r in records]
    return render_template(
        "advisor.html",
        unit=unit,
        unit_types=UNIT_TYPES,
        unit_info=UNIT_INFO[unit],
        choosable=[r for r in records if r["eligibility"] != "fixed"],
        included=[r for r in records if r["eligibility"] == "fixed"],
        house_fittings=house,
    )


@dashboard_bp.route("/api/choices", methods=["POST"])
def api_choices():
    """
    Save one buyer's choices. Body:
    {"unit": "T2S", "choices": {"KIT-CAB": "opt_out", "KIT-TOP": "upgrade"}, "upgrades": {"KIT-TOP": "QUARTZ"}}
    """
    body = _json_body()
    unit = body.get("unit", "")
    picks = body.get("choices", {})
    upgrade_picks = body.get("upgrades", {})
    if unit not in UNIT_TYPES or not isinstance(picks, dict) or not isinstance(upgrade_picks, dict):
        return jsonify({"error": "Send a known unit, a choices object and an optional upgrades object"}), 400
    try:
        buyer_id = impact.save_buyer_choices(unit, picks, upgrade_picks=upgrade_picks)
    except (KeyError, ValueError) as e:
        return jsonify({"error": e.args[0] if e.args else str(e)}), 400
    return jsonify({"buyer_id": buyer_id,
                    "totals": impact.dashboard_totals(_data(), unit)})


def _unit_fitting_ids(data, unit):
    return set(data["fittings"][data["fittings"].unit_type == unit].fitting_id)


EXAMPLE_NOTES = [
    "hak semua kabinet dapur, tukar quartz top",
    "master bedroom wardrobe removed, built in new one",
    "almari bilik kecil tukar baru",
    "changed all lights to LED downlight",
    "hack floor tiles downstairs, put vinyl",
    "hack the wardrobe, put open rack",   # room not stated: two lower-confidence tags
]
# Never use a tagger.HELD_OUT note here: it could be saved into the demo data.


@dashboard_bp.route("/tagger")
def tagger_page():
    """AI tagging: type a messy renovation note, see it sorted into fittings."""
    unit = _unit()
    data = _data()
    ev = tagger.evaluate(data["ripouts"])
    r = data["ripouts"]
    recent = r[(r.unit_type == unit) & r.note.notna() & (r.note != "")].tail(8)
    samples = []
    for note, truth in zip(recent.note, recent.fitting_id):
        t = tagger.tag(note, fitting_ids=_unit_fitting_ids(data, unit))["tags"]
        samples.append({"note": note, "truth": truth, "got": t[0]["fitting_id"] if t else None,
                        "truth_name": tagger.NAMES.get(truth, truth)})
    return render_template("tagger.html", unit=unit, unit_types=UNIT_TYPES, ev=ev,
                           samples=list(reversed(samples)), examples=EXAMPLE_NOTES,
                           names=tagger.NAMES,
                           reusable=sorted(_unit_fitting_ids(data, unit) - impact.NOT_REUSABLE))


@dashboard_bp.route("/api/tag", methods=["POST"])
def api_tag():
    """Body: {"note": "...", "unit": "T2S"} -> tags, highlight spans."""
    body = _json_body()
    unit = body.get("unit", "T2S")
    if unit not in UNIT_TYPES:
        return jsonify({"error": "Unknown unit"}), 400
    note = str(body.get("note") or "")[:500]
    return jsonify(tagger.tag(note, unit, _unit_fitting_ids(_data(), unit)))


@dashboard_bp.route("/api/report", methods=["POST"])
def api_report():
    """Save a tagged note as a new rip-out report. Body: {"unit", "note", "fittings": [...]}"""
    body = _json_body()
    unit, fids = body.get("unit", ""), body.get("fittings", [])
    if unit not in UNIT_TYPES or not isinstance(fids, list):
        return jsonify({"error": "Send a known unit and a list of fittings"}), 400
    try:
        owner = impact.add_ripout_report(unit, fids, body.get("note", ""))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    idx = impact.ripout_index(_data(), unit)
    return jsonify({"owner_id": owner,
                    "rates": {fid: round(rate * 100, 1) for fid, rate in zip(idx.fitting_id, idx.rate)}})


@dashboard_bp.route("/match")
def match():
    """Neighbour Match: the community feed for one home type, as one (simulated) neighbour."""
    unit = _unit()
    data = _data()
    hints = neighbour_match.suggestions(data, unit)
    members = neighbour_match.people(data, unit)
    you = request.args.get("as", "")
    if you not in members:   # default: an owner with something a neighbour is asking for
        you = hints["can_list"][0][0] if hints["can_list"] else min(members)
    items = match_map.listings(data, unit)
    asks = match_map.asks(data, unit)
    reuse = impact.reuse_summary(data, unit)   # the same figures as the dashboard
    trips = [i["km"] for i in items if i["km"] is not None]
    summary = {
        "listed": reuse["listed"],
        "collected": reuse["collected"],
        "matched": sum(i["status"] == "matched" for i in items),
        "waiting": sum(i["status"] == "unmatched" for i in items),
        "asking": len(asks),
        "reused_kg": reuse["material_reused_kg"],
        "carbon_kg": reuse["carbon_saved_kg"],
        "avg_km": (sum(trips) / len(trips)) if trips else 0,
        "neighbours": community.stats(data, unit)["neighbours"],
    }
    f = data["fittings"]
    reusable = [{"id": i, "name": n} for i, n in zip(f.fitting_id[f.unit_type == unit], f.name[f.unit_type == unit])
                if i not in impact.NOT_REUSABLE]
    neighbours = community.everyone(data, unit)
    req = data["requests"]
    return render_template(
        "match.html", unit=unit, unit_types=UNIT_TYPES, items=items, asks=asks, summary=summary,
        layout=match_map.map_layout(unit), reusable=reusable, hints=hints,
        you=community.you_card(data, unit, you), you_at=match_map.position(you, unit),
        posts=community.feed(data, unit, you), board=community.leaderboard(data, unit),
        activity=community.activity(data, unit), neighbours=neighbours,
        names={n["id"]: n["name"] for n in neighbours},
        wanted_fittings=dict(zip(req.request_id[req.unit_type == unit], req.fitting_id[req.unit_type == unit])),
        conditions=neighbour_match.CONDITIONS, max_text=neighbour_match.MAX_TEXT,
        trip_factor=impact.TRANSPORT_KGCO2E_PER_KM)


def _match_call(step):
    """Run a Neighbour Match step: its result as JSON, or a 400 with the reason."""
    try:
        return jsonify(step())
    except (KeyError, ValueError) as e:
        return jsonify({"error": e.args[0] if e.args else str(e)}), 400


def _optional_id(body, key):
    """An optional id from a request body: None if left out, else a string."""
    return None if body.get(key) is None else str(body[key])


@dashboard_bp.route("/api/match/list", methods=["POST"])
def api_match_list():
    """
    Body: {"unit", "owner", "fitting", "condition"?, "note"?, "request_id"?} -> {"listing": ...}.
    Matched at once to the nearest neighbour asking, or to request_id when answering that post.
    """
    body = _json_body()
    return _match_call(lambda: {"listing": neighbour_match.list_item(
        body.get("unit", ""), str(body.get("owner", "")), str(body.get("fitting", "")),
        condition=str(body.get("condition") or "Good"), note=body.get("note", ""),
        request_id=_optional_id(body, "request_id"))})


@dashboard_bp.route("/api/match/request", methods=["POST"])
def api_match_request():
    """Body: {"unit", "requester", "fitting"} -> {"request": ..., "listing": ... or null}."""
    body = _json_body()

    def ask():
        req, listing = neighbour_match.request_item(
            body.get("unit", ""), str(body.get("requester", "")), str(body.get("fitting", "")),
            note=body.get("note", ""))
        return {"request": req, "listing": listing}
    return _match_call(ask)


@dashboard_bp.route("/api/match/claim", methods=["POST"])
def api_match_claim():
    """Body: {"listing_id", "requester"} -> {"request": ..., "listing": ...}: "I'd like this"."""
    body = _json_body()

    def take():
        req, listing = neighbour_match.claim(str(body.get("listing_id", "")), str(body.get("requester", "")))
        return {"request": req, "listing": listing}
    return _match_call(take)


@dashboard_bp.route("/api/match/comment", methods=["POST"])
def api_match_comment():
    """Body: {"post_id", "author", "text"} -> {"message": ...}."""
    body = _json_body()
    return _match_call(lambda: {"message": neighbour_match.comment(
        str(body.get("post_id", "")), str(body.get("author", "")), body.get("text", ""))})


@dashboard_bp.route("/api/match/collect", methods=["POST"])
def api_match_collect():
    """
    Body: {"listing_id", "by"?, "thanks"?} -> {"listing": ...} with its carbon saved.
    `by` is the giver or the neighbour taking it; that neighbour can add a thank-you note.
    """
    body = _json_body()
    return _match_call(lambda: {"listing": neighbour_match.collect(
        str(body.get("listing_id", "")), by=_optional_id(body, "by"), thanks=body.get("thanks", ""))})


@dashboard_bp.route("/api/reset-demo", methods=["POST"])
def api_reset_demo():
    """Every data file back to the starting demo data (same seed, same data every time)."""
    generate_dummy_data.main()
    return jsonify({"ok": True})


# The What-if sliders: name -> (min, max, step). The page draws its sliders from
# this and the API clamps to it, so the two can't drift apart. Defaults are
# impact.SIM_DEFAULTS.
SIM_SLIDERS = {
    "homes": (10, 2000, 10), "uptake": (0, 1, 0.05), "upgrade_share": (0, 1, 0.05),
    "credit_mult": (0, 2, 0.05), "match_rate": (0, 1, 0.05), "programme_cost": (0, 500_000, 5000),
}


def _sim_params():
    """The What-if inputs from the query string: defaults for anything missing or
    not a finite number ("nan" and "inf" parse as floats), clamped to SIM_SLIDERS."""
    p = {}
    for k, (lo, hi, step) in SIM_SLIDERS.items():
        try:
            v = float(request.args.get(k, impact.SIM_DEFAULTS[k]))
        except (TypeError, ValueError):
            v = impact.SIM_DEFAULTS[k]
        if not math.isfinite(v):
            v = impact.SIM_DEFAULTS[k]
        whole_numbers = isinstance(step, int)   # homes and RM stay int
        p[k] = (int if whole_numbers else float)(min(max(v, lo), hi))
    return p


@dashboard_bp.route("/simulate")
def simulate():
    """What-if: project a whole launch with sliders."""
    unit = _unit()
    params = _sim_params()
    return render_template("simulate.html", unit=unit, unit_types=UNIT_TYPES, params=params,
                           sliders=SIM_SLIDERS, defaults=impact.SIM_DEFAULTS,
                           result=impact.simulate(_data(), unit, **params),
                           transport=impact.TRANSPORT_KGCO2E_PER_KM, trip=impact.AVG_TRIP_KM)


@dashboard_bp.route("/api/simulate")
def api_simulate():
    return jsonify(impact.simulate(_data(), _unit(), **_sim_params()))


EXPORTS = {
    "ripout-index": "Rip-out index and advice",
    "impact-by-fitting": "What buyers chose, by fitting",
    "choices": "Every buyer choice",
    "upgrade-mix": "Which upgrade options buyers pick",
}


@dashboard_bp.route("/export/<name>.csv")
def export_csv(name):
    """Download a table as CSV: /export/ripout-index.csv?unit=T2S"""
    unit = _unit()
    data = _data()
    if name == "ripout-index":
        df = impact.design_feedback(data, unit)[["fitting_id", "name", "eligibility",
                                                 "owners", "removed", "rate", "advice"]]
        df = df.assign(rate=(df.rate * 100).round(1)).rename(columns={"rate": "removed_pct"})
    elif name == "impact-by-fitting":
        df = impact.impact_by_fitting(data, unit).round(1)
    elif name == "choices":
        df = data["choices"][data["choices"].unit_type == unit]
    elif name == "upgrade-mix":
        df = impact.upgrade_mix(data, unit)[["fitting_id", "name", "upgrade_id", "upgrade_name", "picks",
                                             "share", "margin_rm", "margin_earned_rm"]]
        df = df.assign(share=(df.share * 100).round(1)).rename(columns={"share": "share_pct"})
    else:
        abort(404)
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    # The header row comes first so the file opens cleanly; "simulated" goes in the
    # filename instead, so the warning travels with the file.
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="right-fit-{name}-{unit}-simulated.csv"'})


@dashboard_bp.route("/api/ripout-index")
def api_ripout_index():
    unit = _unit()
    fb = impact.design_feedback(_data(), unit)
    return jsonify(fb[["fitting_id", "name", "eligibility", "owners",
                       "removed", "rate", "advice"]].to_dict("records"))
