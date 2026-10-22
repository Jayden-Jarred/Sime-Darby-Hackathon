# data/

The demo data, in one SQLite database: `right_fit.db`. All simulated.

The database file is built on each computer and not stored in git, because
every practice run changes it. Starting the app builds it the first time;
`python generate_dummy_data.py` (or **Reset demo data** at the bottom of the
dashboard) rebuilds it from scratch. Both give exactly the same data every
time, except the Neighbour Match dates, which count back from the hour you
reset. The tables and their rules are in `db.py`, and the main README lists
every column.

| Table | One row per | What it holds |
| --- | --- | --- |
| `unit_types` | house design | T2S terrace, C3R condo |
| `fittings` | fitting per home type | Name, whether buyers can opt out or only upgrade, weight, ICE carbon factor, install and removal cost, credit, SDP's upgrade margin |
| `upgrades` | upgrade option | What each fitting can be upgraded to, SDP's margin on it, and its picture |
| `people` | homeowner or buyer | Who they are (id, home type, owner or buyer) |
| `ripouts` | owner per fitting | What existing owners removed after handover, with their note |
| `choices` | buyer per fitting | What new buyers chose in the Advisor, and which upgrade option |
| `matches` | Neighbour Match offer | A removed fitting an owner offered (condition, note), the neighbour matched to it, how far, its status (unmatched / matched / collected) and when each step happened |
| `requests` | Neighbour Match request | A neighbour asking for a fitting (with a note), open or matched, and the listing it was matched to |
| `messages` | message | The chat under each offer or request, and the thank-you notes left on pick-up |

The app adds rows as you use it: the Advisor's **Confirm** button saves to
`choices`, **Add as a rip-out report** on the AI tagging page to `ripouts`,
and giving, asking, messaging and collecting on Neighbour Match to `matches`,
`requests` and `messages`. New owners and buyers are added to `people`.

To look at the data in Excel: `python db.py export` writes every table as a
CSV file into `data/export/` (not stored in git either).
