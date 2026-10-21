# data/

The shared data every page reads. All simulated. `generate_dummy_data.py`
makes these seven files; the main README lists every column.

| File | One row per | What it holds |
| --- | --- | --- |
| `fittings.csv` | fitting per home type | Name, whether buyers can opt out or only upgrade, weight, ICE carbon factor, install and removal cost, credit, SDP's upgrade margin |
| `upgrades.csv` | upgrade option | What each fitting can be upgraded to, SDP's margin on it, and its picture |
| `ripouts.csv` | owner per fitting | What existing owners removed after handover, with their note |
| `choices.csv` | buyer per fitting | What new buyers chose in the Advisor, and which upgrade option |
| `matches.csv` | Neighbour Match offer | A removed fitting an owner offered (condition, note), the neighbour matched to it, how far, its status (unmatched / matched / collected) and when each step happened |
| `requests.csv` | Neighbour Match request | A neighbour asking for a fitting (with a note), open or matched, and the listing it was matched to |
| `messages.csv` | message | The chat under each offer or request, and the thank-you notes left on pick-up |

The app adds rows as you use it: the Advisor's **Confirm** button adds to
`choices.csv`, **Add as a rip-out report** on the AI tagging page adds to
`ripouts.csv`, and giving, asking, messaging and collecting on Neighbour
Match change `matches.csv`, `requests.csv` and `messages.csv`. To reset
everything before a demo, press **Reset demo data** at the bottom of the
dashboard, or run
`python generate_dummy_data.py`. Both give exactly the same data every time,
except the Neighbour Match dates, which count back from the hour you reset.
