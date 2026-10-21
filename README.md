# Right-Fit Homes

**Stop building what buyers tear out.** Many new home owners rip out
brand-new kitchens, wardrobes and tiles soon after handover. Right-Fit Homes
lets buyers keep, opt out of, or upgrade each fitting *before* it is built,
and shows Sime Darby Property (SDP) the waste, carbon and money saved.
A demo for the Sime Darby Property hackathon (Planet track: circular economy
and waste).

| Page | What it does |
| --- | --- |
| Buyer advisor | Keep, opt out for a credit, or pick an upgrade option, with live savings and a 3D model of the home that shows the chosen finish |
| SDP dashboard | Rip-out index, "stop installing" advice for the next launch, carbon and RM saved, which upgrades buyers pick |
| Neighbour Match | Fittings that still get removed, rehomed to the same house design nearby |
| What-if | Projects a whole launch: waste avoided, carbon, SDP's gain and payback |
| AI tagging | Sorts messy renovation notes (English and Malay) into fittings, with an honest accuracy score |

Built with Flask, pandas, Plotly and three.js, and runs offline.

**All data is simulated.** The homes, owners, rip-out rates, buyer choices and
Neighbour Match listings are made up. The fittings' weights, carbon factors and
prices are realistic estimates from public sources: see
[Where the numbers come from](#where-the-numbers-come-from). There is no survey
data.

## Run it

```bash
pip install flask pandas plotly
python generate_dummy_data.py     # makes the CSV files in data/
python test_impact.py             # checks the maths
python app.py                     # open http://127.0.0.1:5000
```

- `/advisor` — the buyer screen: keep / opt out / upgrade each fitting
- `/dashboard` — the SDP dashboard
- `/match` — Neighbour Match: animated map of removed fittings going to same-type homes nearby
- `/simulate` — What-if: sliders to project a whole launch (carbon, RM, payback)
- `/tagger` — AI tagging: type a messy note, see it sorted into fittings; add it as a report

**Demo tip:** confirming choices on the Advisor saves them to
`data/choices.csv`, so the dashboard's buyer count and totals go up. Run
`python generate_dummy_data.py` before the real demo to reset the data.

## Files

`data/`, `templates/` and `static/` each have their own README listing every
file inside. On GitHub, the message next to each file says what it is.

| File | What it is | Owner |
| --- | --- | --- |
| `generate_dummy_data.py` | Makes the simulated CSV data | Member 1 |
| `data/*.csv` | The shared data everyone reads | Member 1 |
| `impact.py` | All cost and carbon calculations | Member 4 |
| `dashboard.py` | SDP dashboard page + JSON API | Member 4 |
| `templates/dashboard.html` | Dashboard layout | Member 4 |
| `static/house3d.js` | 3D preview of the selected home (three.js) | Member 4 |
| `static/vendor/` | three.js r169 + its OrbitControls and RoomEnvironment helpers, bundled so the demo runs offline | — |
| `app.py` | The Flask app | Member 2 |
| `templates/advisor.html` | Buyer Fit-Out Advisor screen | Member 2 |
| `tagger.py` | Sorts messy notes into fittings (keyword version + honest accuracy test). Swap in an AI model by replacing `tag()` | Member 3 |
| `templates/tagger.html` | AI tagging page | Member 3 |
| `templates/simulate.html` | What-if simulator page (maths in `impact.simulate()`) | Member 4 |
| `match_map.py`, `templates/match.html` | Neighbour Match map | Member 4 |
| `static/app.css` | Shared styles and brand (forest green + terracotta) | — |
| `templates/_topbar.html` | Logo and page switcher shared by every page | — |
| `static/fonts/` | Fraunces (headlines) + Figtree (text), bundled for offline use, OFL licence | — |
| `static/upgrades/` | A picture of each upgrade option (drawn illustrations, not product photos) | Member 1 |
| `test_impact.py` | Checks for the calculations | Member 4 |

## The data format (agree on this, don't rename columns)

### `data/fittings.csv` — one row per fitting per unit type

| Column | Meaning |
| --- | --- |
| `unit_type` | `T2S` = double-storey terrace 20' x 70', `C3R` = 3-room condo |
| `fitting_id` | Short code, e.g. `KIT-CAB` |
| `name` | Display name |
| `eligibility` | `opt_out` (keep / opt out / upgrade), `upgrade_only` (keep / upgrade), `fixed` (always installed) |
| `material` | Main material |
| `weight_kg` | Weight of the standard item — our estimate |
| `carbon_factor` | kg CO₂e per kg of material, from the ICE database |
| `install_cost_rm` | What SDP pays to supply and install it — low end of Malaysian retail prices |
| `removal_cost_rm` | What an owner pays to rip it out and dispose of it — our estimate |
| `credit_rm` | Credit the buyer gets for opting out — **assumption**: 70% of `install_cost_rm` |
| `upgrade_margin_rm` | SDP's margin when a buyer upgrades — **assumption**: 20% of `install_cost_rm` |

### `data/upgrades.csv` — what a buyer can upgrade each fitting to

`unit_type, fitting_id, upgrade_id, name, description, margin_rm, image`

One row per option, e.g. `KIT-TOP` → `QUARTZ` "Quartz top", `GRANITE`, `SINTERED`.
`margin_rm` is SDP's margin on that option — an **assumption** (a multiple of
the fitting's `upgrade_margin_rm`; pricier options earn more). The first option
for a fitting is the default, and matches `upgrade_margin_rm` in `fittings.csv`
(the What-if simulator still uses that one number). Fixed fittings have none.

`image` is the option's picture on the Advisor, a path under `static/` (e.g.
`upgrades/quartz.svg`). They're drawn illustrations. To use a real supplier
photo instead, put it in `static/upgrades/` and point `image` at it (in
`generate_dummy_data.py`'s `write_upgrades()`), with permission to use the
photo. `python -c "import generate_dummy_data as g; g.write_upgrades()"`
rewrites just this file, without resetting the rest of the data.

### `data/ripouts.csv` — what existing owners removed (one row per owner per fitting)

`owner_id, unit_type, fitting_id, removed (1/0), note`

`note` is messy free text like "kabinet dapur tukar baru". **Member 3:** your
AI tagging should turn each note back into its `fitting_id`, so you can
measure how accurate the tagger is against this column.

### `data/choices.csv` — what new buyers picked in the Fit-Out Advisor

`buyer_id, unit_type, fitting_id, choice (keep / opt_out / upgrade), upgrade_id`

`upgrade_id` is the option from `upgrades.csv` for upgrades, empty otherwise.
Data made before this column existed won't load: run `python generate_dummy_data.py`.

### `data/matches.csv` — Neighbour Match listings

`listing_id, from_owner, unit_type, fitting_id, to_owner, distance_km, status (collected / matched / unmatched)`

## For Member 2: getting live savings in the Advisor screen

Plug the dashboard into the app (already done in `app.py`):

```python
from dashboard import dashboard_bp
app.register_blueprint(dashboard_bp)
```

When the buyer clicks a choice, call:

```
GET /api/impact?unit=T2S&fitting=KIT-CAB&choice=opt_out
```

It returns JSON:

```json
{"unit_type": "T2S", "fitting_id": "KIT-CAB", "name": "Kitchen cabinets", "choice": "opt_out",
 "carbon_avoided_kg": 219.12, "material_avoided_kg": 330.0,
 "sdp_saving_rm": 2470.0, "buyer_saving_rm": 6270.0, "buyer_credit_rm": 5770.0,
 "upgrade_revenue_rm": 0.0, "upgrade_id": null, "upgrade_name": null}
```

For an upgrade, add which option: `&choice=upgrade&upgrade=QUARTZ` (left out =
the fitting's first option). `upgrade_revenue_rm` is that option's margin, and
`upgrade_id` / `upgrade_name` say which one it was.

An invalid choice (e.g. opting out of tiles), an unknown fitting or an
unknown `unit` returns HTTP 400 with an `error` message, so the screen can
show why.

For the rip-out index screen: `GET /api/ripout-index?unit=T2S`.

To save a buyer's choices (the Advisor's "Confirm" button does this):

```
POST /api/choices
{"unit": "T2S", "choices": {"KIT-CAB": "opt_out", "WRD-MST": "upgrade"},
 "upgrades": {"WRD-MST": "WALK-IN"}}
```

Fittings left out count as `keep`. `upgrades` says which option each upgrade
is (left out = the first option); an unknown option returns HTTP 400. Fixed fittings may be sent as `keep`
(they aren't saved, since they're always installed). Returns the new
`buyer_id` and the updated dashboard totals. Invalid choices return HTTP 400.

Or call the Python directly: `impact.impact_of(fittings, "T2S", "KIT-CAB", "opt_out")`.

## 3D preview

The top of the dashboard shows the selected home in 3D (drag to rotate,
scroll to zoom):

- **Exterior:** the terrace row, or the condo tower with the selected unit in terracotta (the brand accent).
- **Fittings:** walls turn see-through, upper floors lift away, and each
  fitting is coloured by its advice (red = stop installing, amber = offer as
  opt-out or upgrade, green = keep). Hover or tap a fitting for its rip-out rate.
- **Floors:** on the terrace, the Floor buttons (All / Ground / First) show
  one floor at a time and zoom in on it. The condo unit is on one level, so it
  has no floor buttons.
- **Zoom on select:** clicking a fitting in 3D (or its row in the
  design-feedback table, or its choice on the Advisor) switches to the floor
  it's on and flies the camera in close. Pick "All" to zoom back out.
- Clicking a bar in the chart shows that fitting in 3D the same way, from
  either view. Hovering a bar highlights it once the Fittings view is open.
- **Upgrades (Advisor):** picking an upgrade option shows it in the model in
  that finish, outlined in terracotta: plywood or brushed aluminium cabinets;
  quartz, granite or sintered stone tops; large tiles or vinyl planks; and
  mirrored sliding doors. Some options change the shape too: the walk-in
  system shows open shelves with clothes, the study option a half wardrobe with
  a desk, and the LED options recessed downlights that glow (smart lights drift
  between warm and cool white). The finishes are `LOOKS` in `house3d.js`, keyed
  by `upgrade_id`; a new option without one shows as plain terracotta.

The models are simple boxes, not SDP drawings. Colours come straight from
the rip-out index, so they update when the data changes. The advice colours
are set once, in `ADVICE_COLOUR` in `dashboard.py`: the chart uses them, and
every page's `<body style="{{ advice_css }}">` gets them as CSS variables
(`--advice-stop`, `--advice-offer`, `--advice-keep`) for the badges and the 3D
model. A new page needs that same `style` on its `<body>`. **Member 2** can reuse
the 3D view on the buyer screens. It needs the bundled three.js mapped in an
importmap first (copy both script tags from `templates/dashboard.html`):

```html
<script type="importmap">
  {"imports": {"three": "/static/vendor/three.module.min.js",
               "three/addons/": "/static/vendor/"}}
</script>
<script type="module">
  import { mountHouse } from "/static/house3d.js";
  const view = mountHouse(el, { unit: "T2S", fittings: rowsFromApiRipoutIndex });
  if (view) {               // null when the browser has WebGL turned off
    view.focus("KIT-CAB");  // switch to Fittings view, pin that item and zoom in
    view.setFloor("ff");    // "all", or an id from view.floors (T2S: "gf", "ff")
  }
</script>
```

`el` is the house section: give it a `.house-canvas` child for the picture (the
advice colours come from the page's `<body>`, as above). Add an element
with `data-floor-picker` holding an empty `.seg` inside it and the Floor buttons
fill it (see `templates/dashboard.html`).

## How the numbers are calculated

- **Carbon per item** = `weight_kg × carbon_factor`.
- **Opt out:** the item is never made. SDP saves `install_cost − credit`;
  the buyer gets the credit and skips the rip-out cost.
- **Upgrade:** SDP installs the buyer's preferred version instead. The
  standard item is never made, SDP earns `upgrade_margin`, and the buyer
  skips the rip-out cost.
- **Carbon is only counted** for items the buyer would otherwise have removed.
- **Reuse carbon** = item carbon − delivery trip (0.25 kg CO₂e per km for a small van, both ways — an assumption). One function, `impact.reuse_carbon_kg()`, used by the dashboard, the What-if and the Neighbour Match page.
- **Upgrade mix** (`impact.upgrade_mix()`, the "Which upgrades buyers pick"
  panel on the dashboard): for each fitting, how many buyers picked each
  upgrade option, its share of that fitting's upgrades, and the margin it
  earned. Options nobody picked show as 0%, and an upgrade saved without an
  option counts as the first one. Bar colours follow the option's order in
  `upgrades.csv` (up to four options have a colour).
- **Design advice:** removed by 50%+ → stop installing as standard;
  30–50% → offer as opt-out (offer as upgrade for `upgrade_only` items like
  tiles); below 30% → keep. Thresholds are in `impact.py`.

## Where the numbers come from

Every fitting's figures, with the working, are in `FITTINGS` at the top of
`generate_dummy_data.py`. In short:

| What | Source |
| --- | --- |
| Carbon factors (kg CO₂e/kg): particleboard 0.664, ceramic tile 0.796, sanitary ceramic 1.93, glass 1.437, aluminium 13.06 | [ICE Database v4](https://circularecology.com), Circular Ecology 2024, cradle to gate, as listed on Climatiq (e.g. [tile](https://www.climatiq.io/data/emission-factor/ca3be708-df0d-47a2-9e51-43cf139ebfd8), [sanitary](https://www.climatiq.io/data/emission-factor/218eace7-6add-4bcf-b571-b464ac924dfd)) |
| Solid-surface kitchen top: 0.70 kg CO₂e/kg | No open factor for acrylic solid surface, so a stand-in: [DuPont quartz worktop EPD](https://materials.oneclicklca.com/en/material/quartz-countertop/66475d82e18244544f8d7be7) (42.4 kg CO₂e/m² at 61 kg/m²). Likely an undercount. |
| Kitchen cabinets: RM280/ft base, RM220/ft wall | [recommend.my](https://recommend.my/blog/?p=9822), 29 Sep 2024 |
| Solid-surface top: RM135/ft | [recommend.my](https://recommend.my/blog/?p=8605), 29 Sep 2024 |
| Wardrobe: RM3,840 for 2.4 m | [recommend.my](https://recommend.my/blog/?p=18334), 29 Sep 2024 |
| Tiles RM15/sqft installed, hacking RM3–6/sqft, pendant RM80, toilet RM250, sink and tap RM150 | [Qanvast](https://qanvast.com/my/articles/how-much-does-it-cost-to-renovate-in-malaysia-928), 8 Dec 2025 |

SDP's prices are the low end of each range, since it buys in bulk. Tile hacking
is paid by the owner with no bulk discount, so it uses RM4/sqft, inside RM3–6. Weights,
removal costs, the 70% credit and 20% upgrade margin are our own estimates or
assumptions, stated as such in the generator. Rip-out rates are simulated.

To change a number, edit `FITTINGS` (or `CREDIT_SHARE` / `MARGIN_SHARE`) and
refresh just the fittings and upgrade options, keeping any rip-out reports and
buyer choices added through the app:

```bash
python -c "import generate_dummy_data as g; g.write_fittings(); g.write_upgrades()"
```


## More API routes

| Route | What it does |
| --- | --- |
| `POST /api/tag` `{"note", "unit"}` | Tags one note: fittings found, confidence, words to highlight |
| `POST /api/report` `{"unit", "note", "fittings": [...]}` | Saves a tagged note as a new rip-out report (updates the rip-out index) |
| `GET /api/simulate?unit=T2S&homes=500&uptake=0.8&upgrade_share=0.4&credit_mult=1&match_rate=0.5&programme_cost=80000` | One launch projection |
| `GET /export/<ripout-index or impact-by-fitting or upgrade-mix or choices>.csv?unit=T2S` | CSV downloads |

Check the tagger's accuracy any time with `python tagger.py`. The honest number is the
**held-out** one: `HELD_OUT` notes the word lists were never tuned to. Notes the
rules were adjusted to pass live in `TUNING_NOTES` and don't count. If you change
the rules to fix a held-out miss, move that note to `TUNING_NOTES`.

**Demo tip:** adding reports on the AI tagging page and confirming choices on the Advisor
both change the data. Run `python generate_dummy_data.py` before the real demo.
