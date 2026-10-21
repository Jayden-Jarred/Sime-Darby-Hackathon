# templates/

One HTML page each, filled in by the routes in `dashboard.py`. Each file
starts with a comment saying what it shows.

| File | Page | What it does |
| --- | --- | --- |
| `signin.html` | `/signin` | Demo sign-in: SDP staff, a homeowner or a buyer moving in, with suggested people. No password |
| `advisor.html` | `/advisor` | Buyer Fit-Out Advisor: keep, opt out or upgrade each fitting, with live savings, the working behind each number, and the 3D home |
| `dashboard.html` | `/dashboard` | SDP dashboard: KPIs, rip-out chart, "what to change next launch", upgrade mix, 3D home, Reset demo data button |
| `match.html` | `/match` | Neighbour Match community: give or ask (matched at once to the nearest home), a feed of posts with chat, claim, collect and thank-you, your profile and badges, top neighbours, the township map |
| `simulate.html` | `/simulate` | What-if: sliders that project a whole launch |
| `tagger.html` | `/tagger` | AI tagging: sort a messy renovation note into fittings, save it as a report, and offer the removed fittings to neighbours |
| `_topbar.html` | (every page) | The shared logo, page menu (SDP dashboard first) and who is signed in, included at the top of each page |
