# data/

The shared data every page reads. All simulated. `generate_dummy_data.py`
makes these files; the main README lists every column.

| File | One row per | What it holds |
| --- | --- | --- |
| `fittings.csv` | fitting per home type | Name, whether buyers can opt out or only upgrade, weight, ICE carbon factor, install and removal cost, credit, SDP's upgrade margin |
| `upgrades.csv` | upgrade option | What each fitting can be upgraded to, SDP's margin on it, and its picture |
| `ripouts.csv` | owner per fitting | What existing owners removed after handover, with their note |
| `choices.csv` | buyer per fitting | What new buyers chose in the Advisor, and which upgrade option |
| `matches.csv` | Neighbour Match listing | A removed fitting, the neighbour who took it, how far, and whether it was collected |

The app adds rows as you use it: the Advisor's **Confirm** button adds to
`choices.csv`, and **Add as a rip-out report** on the AI tagging page adds to
`ripouts.csv`. To reset everything before a demo: `python generate_dummy_data.py`.
