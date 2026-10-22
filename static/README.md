# static/

Files the browser loads directly. Everything is bundled here, so the demo runs
with no internet.

| File or folder | What it is |
| --- | --- |
| `app.css` | Shared styles and brand colours (forest green and terracotta) for every page |
| `house3d.js` | The 3D home (three.js): Exterior and Fittings views, floor by floor, zoom on select, advice colours (from each fitting's `advice_key`), and each upgrade's finish (`LOOKS`) |
| `esc.js` | `esc()`: escapes text before it goes into HTML. Imported by `house3d.js` and the Advisor and AI tagging pages |
| `upgrades/` | A picture of each upgrade option, shown on the Advisor. Drawn illustrations, not product photos; the name matches the `image` column of the `upgrades` table |
| `fonts/` | Fraunces (headings) and Figtree (text), with their open font licences |
| `vendor/` | three.js r169 and its OrbitControls (drag and zoom) and RoomEnvironment (lighting) add-ons, with the three.js licence |
| `plotly.min.js` | Not in git: `app.py` writes it on first run, from the installed plotly package |
