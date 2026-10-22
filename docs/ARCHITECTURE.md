# Right-Fit Homes: system architecture

Right-Fit Homes is one Flask web app for three kinds of user: a **buyer moving
in**, a **homeowner** and **SDP staff**. It runs the proposal's loop of four
functions (Track, Advise, Match, Learn) plus a What-if projection, and every
function reads and writes one shared SQLite database. For the demo it runs
offline on one laptop: Python, Flask, pandas, Plotly and three.js, with no
internet and no other services.

The diagrams below are Mermaid, which GitHub draws on this page.

## 1. The big picture

```mermaid
flowchart TB
    subgraph users["Users (browser)"]
        buyer["Buyer moving in"]
        owner["Homeowner"]
        sdp["SDP staff"]
    end

    subgraph pages["Pages (templates/, static/)"]
        signin["Demo sign-in"]
        advisor["Buyer advisor"]
        tagging["AI tagging"]
        match["Neighbour Match"]
        dash["SDP dashboard"]
        whatif["What-if"]
    end

    subgraph flask["Flask app (app.py)"]
        dbp["dashboard.py<br/>pages, JSON API, sign-in,<br/>request checks"]
        bbp["buyer.py<br/>buyer API: nearest<br/>neighbour giving one"]
    end

    subgraph domain["Domain logic (pure Python + pandas)"]
        impact["impact.py<br/>cost and carbon maths,<br/>rip-out index, advice, What-if"]
        tagger["tagger.py<br/>messy note to fittings"]
        nm["neighbour_match.py<br/>offer, ask, nearest match,<br/>claim, chat, collect"]
        community["community.py<br/>names, feed, badges"]
        mapm["match_map.py<br/>homes, addresses, distances"]
    end

    subgraph data["Data"]
        dbpy["db.py<br/>tables, rules, transactions"]
        sqlite[("data/right_fit.db<br/>SQLite")]
        gen["generate_dummy_data.py<br/>builds and resets the demo data"]
    end

    buyer --> signin
    owner --> signin
    sdp --> signin
    buyer --> advisor
    owner --> tagging
    owner --> match
    sdp --> dash
    sdp --> whatif

    pages -- "HTTP: pages and JSON" --> flask
    flask --> domain
    domain --> dbpy
    dbpy --> sqlite
    gen --> dbpy

    llm["Claude (Anthropic API)<br/>when a key is set"] -. "behind tagger.tag()" .-> tagger
    sdpsys["SDP renovation applications<br/>and sales system (pilot)"] -. "imports" .-> dbpy
    login["SDP account login (pilot)"] -. "replaces signed_in()" .-> dbp
```

Each layer only talks to the one below it. Pages never touch the database;
the maths never knows it is a web app; only `db.py` knows the data is SQLite.
That is what lets a teammate swap one part (the LLM, the login, a bigger
database) without touching the others.

## 2. The loop: how the functions feed each other

```mermaid
flowchart LR
    track["Track<br/>AI tagging saves<br/>rip-out reports"]
    index["Rip-out index<br/>share of owners who<br/>removed each fitting"]
    advise["Advise<br/>buyer keeps, opts out<br/>or upgrades"]
    learn["Learn<br/>dashboard: stop installing X,<br/>carbon and RM saved"]
    matchf["Match<br/>removed fittings go to<br/>the nearest same-type home"]
    whatiff["What-if<br/>projects a whole launch"]

    track --> index
    index --> advise
    index --> learn
    index --> whatiff
    advise -- "choices" --> learn
    track -- "Offer to neighbours" --> matchf
    advise -- "opted out: a neighbour<br/>is giving one" --> matchf
    matchf -- "collected: reuse<br/>carbon and rate" --> learn
    learn -. "next launch's<br/>standard specs" .-> advise
```

| From | To | What travels | Where in the code |
| --- | --- | --- | --- |
| Track | Advise, Learn, What-if | Rip-out rates per fitting and home type | `impact.ripout_index()` over the `ripouts` table |
| Advise | Learn | Every buyer's choices | `impact.save_buyer_choices()` → `choices`, read by `impact.dashboard_totals()` |
| Track | Match | "Offer the … to neighbours" after a report | `templates/tagger.html` → `POST /api/match/list` |
| Advise | Match | The nearest neighbour giving away a fitting the buyer opted out of | `buyer.py` `GET /api/buyer/nearby` |
| Match | Learn | Collected fittings: reuse rate and carbon saved | `impact.reuse_summary()` over `matches` |
| Sign-in | every page | Who is using the app (buyer, homeowner or SDP staff) | `dashboard.signed_in()` |

## 3. Layers and files

| Layer | Files | What it does |
| --- | --- | --- |
| Pages | `templates/*.html`, `static/app.css`, `static/house3d.js`, `static/vendor/` | What users see. Jinja templates filled by the routes; three.js for the 3D home; Plotly for charts. All libraries and fonts are bundled, so it runs offline. |
| Web (Flask) | `app.py`, `dashboard.py`, `buyer.py` | Routes for every page and JSON API, the demo sign-in, and the request checks (other websites refused, 64 KB limit, debug off by default). |
| Domain logic | `impact.py`, `tagger.py`, `neighbour_match.py`, `community.py`, `match_map.py` | The rules and the maths. Works on pandas DataFrames from `impact.load_data()`; saves through `db.py`. |
| Data | `db.py`, `data/right_fit.db`, `generate_dummy_data.py` | One SQLite file. `db.py` defines the tables and their rules, runs every save in a transaction and exports CSV copies. The generator builds the demo data and the Reset button rebuilds it. |
| Checks | `test_impact.py`, `test_buyer.py` | Over 500 checks: maths, database rules, every page and API, sign-in, security fixes, the buyer flow. Saves are tested on temporary copies, so the real data never changes. |

### Routes

| Route | Page or API |
| --- | --- |
| `/`, `/signin`, `POST /signin`, `POST /signout` | Demo sign-in; `/` goes to the SDP dashboard once signed in |
| `/dashboard`, `/advisor`, `/match`, `/simulate`, `/tagger` | The five pages |
| `GET /api/impact`, `POST /api/choices` | Advisor: one choice's numbers and working; save a buyer's choices |
| `GET /api/buyer/nearby` | Advisor: the nearest neighbour giving away each opted-out fitting |
| `POST /api/tag`, `POST /api/report` | AI tagging: tag a note; save it as a rip-out report |
| `POST /api/match/list`, `request`, `claim`, `comment`, `collect` | Neighbour Match actions |
| `GET /api/ripout-index`, `GET /api/simulate`, `GET /export/<table>.csv` | Data for charts, the What-if, CSV downloads |
| `POST /api/reset-demo` | Rebuild the demo database (dashboard button) |

## 4. Database design

One SQLite file, `data/right_fit.db`, nine tables. Column names are the ones
the team agreed for the original CSV files; `people` is new, so every owner
and buyer is one row that reports, choices and posts point at (and that a real
login can attach to).

```mermaid
erDiagram
    UNIT_TYPES ||--o{ FITTINGS : "has"
    UNIT_TYPES ||--o{ PEOPLE : "home type of"
    FITTINGS ||--o{ UPGRADES : "can be upgraded to"
    PEOPLE ||--o{ RIPOUTS : "reports"
    FITTINGS ||--o{ RIPOUTS : "is in"
    PEOPLE ||--o{ CHOICES : "makes"
    FITTINGS ||--o{ CHOICES : "is in"
    UPGRADES |o--o{ CHOICES : "picked as"
    PEOPLE ||--o{ MATCHES : "offers"
    PEOPLE |o--o{ MATCHES : "takes"
    FITTINGS ||--o{ MATCHES : "is offered in"
    PEOPLE ||--o{ REQUESTS : "asks"
    MATCHES |o--o{ REQUESTS : "answers"
    PEOPLE ||--o{ MESSAGES : "writes"

    UNIT_TYPES {
        string unit_type PK "T2S, C3R"
        string name
    }
    FITTINGS {
        string unit_type PK
        string fitting_id PK "KIT-CAB"
        string eligibility "opt_out, upgrade_only, fixed"
        number weight_kg
        number carbon_factor "ICE, kg CO2e per kg"
        number install_cost_rm
        number removal_cost_rm
        number credit_rm
        number upgrade_margin_rm
    }
    UPGRADES {
        string unit_type PK
        string fitting_id PK
        string upgrade_id PK "QUARTZ"
        number margin_rm
        string image
    }
    PEOPLE {
        string person_id PK "T2S-O001 owner, T2S-B001 buyer"
        string unit_type FK
        string role "owner, buyer"
    }
    RIPOUTS {
        string owner_id PK
        string fitting_id PK
        int removed "0 or 1"
        string note "the owner's own words"
    }
    CHOICES {
        string buyer_id PK
        string fitting_id PK
        string choice "keep, opt_out, upgrade"
        string upgrade_id "upgrades only"
    }
    MATCHES {
        string listing_id PK "L001"
        string from_owner FK
        string to_owner FK "once matched"
        number distance_km
        string status "unmatched, matched, collected"
        string condition "Like new, Good, Fair"
        string posted_at
        string matched_at
        string collected_at
    }
    REQUESTS {
        string request_id PK "R001"
        string requester FK
        string status "open, matched"
        string listing_id FK
    }
    MESSAGES {
        string message_id PK "M001"
        string post_id "a listing or request id"
        string author FK
        string kind "comment, thanks"
        string text
    }
```

**Rules the database enforces** (in `db.SCHEMA`): primary keys (one choice per
buyer per fitting, one rip-out row per owner per fitting, one offer per owner
per fitting), foreign keys (nothing can point at a fitting, upgrade or person
that doesn't exist), allowed values (choices, statuses, conditions, a removed
flag of 0 or 1) and consistency checks (a matched listing has a taker, a
collected one has a collection time, an open request has no listing, only an
upgrade has an upgrade option).

**How saving works.** A save reads the data, decides (the next id, the nearest
neighbour), then writes all its rows in one transaction (`db.transaction()`):
complete, or not there at all. An in-process lock (`impact.DATA_LOCK`) makes
saves take turns, so two at the same moment can't pick the same id. The test
suite checks that 20 saves at once all land.

## 5. Two requests, step by step

A buyer confirms their choices on the Advisor:

```mermaid
sequenceDiagram
    actor B as Buyer (signed in)
    participant P as Advisor page
    participant D as dashboard.py
    participant I as impact.py
    participant DB as db.py / SQLite
    participant BY as buyer.py
    B->>P: Confirm my choices
    P->>D: POST /api/choices {unit, choices, upgrades}
    D->>D: signed_in(): this buyer (never from the request)
    D->>I: save_buyer_choices(..., buyer_id)
    I->>I: check every choice is allowed (impact_of)
    I->>DB: one transaction: replace this buyer's choices
    D->>I: dashboard_totals()
    D-->>P: {buyer_id, name, totals}
    P->>BY: GET /api/buyer/nearby (opted-out fittings)
    BY-->>P: nearest neighbour giving each one away
    P-->>B: "Saved for Arjun R." + "Ask for one"
```

A homeowner offers a fitting they removed:

```mermaid
sequenceDiagram
    actor O as Homeowner
    participant P as Neighbour Match page
    participant D as dashboard.py
    participant N as neighbour_match.py
    participant M as match_map.py
    participant DB as db.py / SQLite
    O->>P: Post offer (fitting, condition, note)
    P->>D: POST /api/match/list
    D->>N: list_item(unit, owner, fitting, ...)
    N->>N: owner reported removing it? not listed before? reusable?
    N->>M: distance to each neighbour asking for it
    N->>DB: one transaction: insert the offer, match the nearest request
    D-->>P: the listing (matched, or waiting)
    P-->>O: "Matched at once: Wei Ming, 0.4 km away"
```

## 6. Across the whole app

| Concern | How it is handled now |
| --- | --- |
| Who is using it | Demo sign-in in Flask's signed session cookie. `dashboard.signed_in()` is the one place that asks; saves use the signed-in person, never an id sent by the browser. |
| Security | POSTs from other websites refused; Reset needs JSON; request bodies over 64 KB refused; debug mode off unless `FLASK_DEBUG=1`; every user's text escaped on the pages. |
| Data quality | Database keys, links and checks (section 4); every save in one transaction. |
| Speed | The dashboard works out each distinct choice once (about 0.2 s per load); pages read the database fresh on each request, so edits show at once. |
| Honest numbers | Carbon counted only for fittings at least 30% of owners remove; reuse carbon net of delivery trips; every number on the Advisor shows its working; simulated data labelled on every page. |
| Offline demo | three.js, Plotly and fonts bundled in `static/`. The only network call is AI tagging asking Claude, and only when an API key is set; without one, or offline, the keyword rules tag every note. |
| Reset before a demo | Dashboard button, or `python generate_dummy_data.py`: the same data every time (only Neighbour Match dates move). |

## 7. From the demo to a real pilot

What would change, layer by layer. Everything above the data layer stays the
same, because pages and maths only use `impact.load_data()` and the save
functions.

| Layer | Demo (now) | Pilot (suggested) |
| --- | --- | --- |
| Database | SQLite file on one laptop | A server database (e.g. PostgreSQL) with the same tables. Only `db.py` changes. |
| Saving at the same time | One app process + lock + transactions | Several processes: drop the in-process lock, rely on database transactions and row locks. |
| Login | Demo sign-in, no password | SDP's own account system replaces `signed_in()` and the `/signin` routes; accounts attach to `people`. |
| AI tagging | Claude behind `tagger.tag()` when an API key is set, keyword rules otherwise and as the backup | The same, on SDP's own API key. Test Claude on real owners' notes (`python tagger.py --ai` with new held-out notes) before trusting it. |
| Where data comes from | Simulated owners, buyers and reports | SDP's renovation applications feed `ripouts`; the sales system feeds `people` and `choices`. |
| Hosting | `python app.py` on localhost | A WSGI server (e.g. gunicorn or waitress) behind HTTPS on SDP's network. |
| Privacy | Fictional names and addresses | Show neighbours only the distance until both agree to a pickup; keep personal data in SDP's systems. |
