"""
app.py - starts the Right-Fit Homes web app.

Run:   python app.py      then open http://127.0.0.1:5000
While coding, FLASK_DEBUG=1 python app.py adds error pages with the code and
auto-reload. Never use debug mode when other people can reach the app (for
example with flask run --host 0.0.0.0): its error pages show the code.

Every page and API route lives in dashboard.py (a Flask Blueprint plugged in
here), except the buyer screens' own API in buyer.py (a second Blueprint).
"/" opens the demo sign-in screen, then the SDP dashboard (the main page)
once someone has signed in.
"""

import os
from pathlib import Path

from flask import Flask, redirect, url_for
from plotly.offline import get_plotlyjs

from buyer import buyer_bp
import generate_dummy_data
from dashboard import dashboard_bp, signed_in

generate_dummy_data.ensure_database()   # a fresh clone has no data/right_fit.db yet: build it
app = Flask(__name__)
app.register_blueprint(dashboard_bp)
app.register_blueprint(buyer_bp)

# Save Plotly's JavaScript locally once, so the demo works with no internet.
STATIC = Path(__file__).parent / "static"
STATIC.mkdir(exist_ok=True)
plotly_js = STATIC / "plotly.min.js"
if not plotly_js.exists():
    plotly_js.write_text(get_plotlyjs(), encoding="utf-8")


@app.route("/")
def home():
    return redirect(url_for("dashboard.dashboard" if signed_in() else "dashboard.signin"))


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1")   # off unless asked: see the top of this file
