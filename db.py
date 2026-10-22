"""
db.py - the Right-Fit Homes database: SQLite, one file, data/right_fit.db (Member 4).

  exists(data_dir)            is the database there yet?
  create(data_dir)            every table, empty (the generator and Reset demo data start here)
  read_tables(data_dir)       every table as a pandas DataFrame (impact.load_data uses this)
  transaction(data_dir)       `with transaction() as con:` saves everything, or nothing if any step fails
  insert(con, table, row)     one row from a dict; empty text is stored as NULL
  ensure_person(con, ...)     add an owner or buyer the first time they save something
  export_csv(data_dir, out)   every table as a CSV, for reading in Excel: python db.py export

The tables (SCHEMA below) keep the column names of the old CSV files, so the
maths and pages read the same columns as before. The database checks the rules
a CSV couldn't: keys (one choice per buyer per fitting), links between tables
(a report for a fitting that exists, by an owner who exists), allowed values
(keep / opt_out / upgrade), and consistency (a matched listing has a taker).
Every save runs in one transaction, so a save is complete or not there at all.
"""

import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).parent / "data"
DB_FILE = "right_fit.db"

# Parents before children: create in this order, drop in reverse.
TABLES = ["unit_types", "fittings", "upgrades", "people", "ripouts", "choices", "matches", "requests", "messages"]

SCHEMA = """
CREATE TABLE unit_types (                -- one row per house design
  unit_type   TEXT PRIMARY KEY,          -- T2S, C3R
  name        TEXT NOT NULL
);

CREATE TABLE fittings (                  -- one row per fitting per house design
  unit_type          TEXT NOT NULL REFERENCES unit_types,
  fitting_id         TEXT NOT NULL,      -- KIT-CAB
  name               TEXT NOT NULL,
  eligibility        TEXT NOT NULL CHECK (eligibility IN ('opt_out', 'upgrade_only', 'fixed')),
  material           TEXT NOT NULL,
  weight_kg          NUMERIC NOT NULL CHECK (weight_kg > 0),
  carbon_factor      REAL NOT NULL CHECK (carbon_factor >= 0),
  install_cost_rm    NUMERIC NOT NULL CHECK (install_cost_rm >= 0),
  removal_cost_rm    NUMERIC NOT NULL CHECK (removal_cost_rm >= 0),
  credit_rm          NUMERIC NOT NULL CHECK (credit_rm >= 0),
  upgrade_margin_rm  NUMERIC NOT NULL CHECK (upgrade_margin_rm >= 0),
  PRIMARY KEY (unit_type, fitting_id)
);

CREATE TABLE upgrades (                  -- what each fitting can be upgraded to
  unit_type    TEXT NOT NULL,
  fitting_id   TEXT NOT NULL,
  upgrade_id   TEXT NOT NULL,            -- QUARTZ
  name         TEXT NOT NULL,
  description  TEXT NOT NULL,
  margin_rm    NUMERIC NOT NULL CHECK (margin_rm >= 0),
  image        TEXT,
  PRIMARY KEY (unit_type, fitting_id, upgrade_id),
  FOREIGN KEY (unit_type, fitting_id) REFERENCES fittings
);

CREATE TABLE people (                    -- every homeowner and new buyer (the real login attaches here)
  person_id   TEXT PRIMARY KEY,          -- T2S-O001 homeowner, T2S-B001 buyer
  unit_type   TEXT NOT NULL REFERENCES unit_types,
  role        TEXT NOT NULL CHECK (role IN ('owner', 'buyer'))
);

CREATE TABLE ripouts (                   -- Track: what each owner removed after handover
  owner_id    TEXT NOT NULL REFERENCES people,
  unit_type   TEXT NOT NULL,
  fitting_id  TEXT NOT NULL,
  removed     INTEGER NOT NULL CHECK (removed IN (0, 1)),
  note        TEXT,                      -- the owner's own words, e.g. "kabinet dapur tukar baru"
  PRIMARY KEY (owner_id, fitting_id),
  FOREIGN KEY (unit_type, fitting_id) REFERENCES fittings
);

CREATE TABLE choices (                   -- Advise: what each new buyer chose
  buyer_id    TEXT NOT NULL REFERENCES people,
  unit_type   TEXT NOT NULL,
  fitting_id  TEXT NOT NULL,
  choice      TEXT NOT NULL CHECK (choice IN ('keep', 'opt_out', 'upgrade')),
  upgrade_id  TEXT,                      -- the option picked, for upgrades only
  PRIMARY KEY (buyer_id, fitting_id),
  FOREIGN KEY (unit_type, fitting_id) REFERENCES fittings,
  FOREIGN KEY (unit_type, fitting_id, upgrade_id) REFERENCES upgrades,
  CHECK (upgrade_id IS NULL OR choice = 'upgrade')
);

CREATE TABLE matches (                   -- Match: fittings owners offer to neighbours ("listings")
  listing_id    TEXT PRIMARY KEY,        -- L001
  from_owner    TEXT NOT NULL REFERENCES people,
  unit_type     TEXT NOT NULL,
  fitting_id    TEXT NOT NULL,
  to_owner      TEXT REFERENCES people,  -- the neighbour taking it, once matched
  distance_km   REAL CHECK (distance_km >= 0),
  status        TEXT NOT NULL CHECK (status IN ('unmatched', 'matched', 'collected')),
  condition     TEXT NOT NULL CHECK (condition IN ('Like new', 'Good', 'Fair')),
  note          TEXT,
  posted_at     TEXT NOT NULL,           -- YYYY-MM-DD HH:MM
  matched_at    TEXT,
  collected_at  TEXT,
  FOREIGN KEY (unit_type, fitting_id) REFERENCES fittings,
  UNIQUE (from_owner, fitting_id),       -- an owner offers a fitting once
  CHECK ((status = 'unmatched') = (to_owner IS NULL)),
  CHECK ((status = 'collected') = (collected_at IS NOT NULL))
);

CREATE TABLE requests (                  -- Match: neighbours asking for a fitting
  request_id  TEXT PRIMARY KEY,          -- R001
  requester   TEXT NOT NULL REFERENCES people,
  unit_type   TEXT NOT NULL,
  fitting_id  TEXT NOT NULL,
  status      TEXT NOT NULL CHECK (status IN ('open', 'matched')),
  listing_id  TEXT REFERENCES matches,   -- the offer it was matched to
  note        TEXT,
  posted_at   TEXT NOT NULL,
  FOREIGN KEY (unit_type, fitting_id) REFERENCES fittings,
  CHECK ((status = 'open') = (listing_id IS NULL))
);

CREATE TABLE messages (                  -- Match: the chat under each post, and thank-you notes
  message_id  TEXT PRIMARY KEY,          -- M001
  post_id     TEXT NOT NULL CHECK (post_id LIKE 'L%' OR post_id LIKE 'R%'),   -- a listing or a request
  author      TEXT NOT NULL REFERENCES people,
  kind        TEXT NOT NULL CHECK (kind IN ('comment', 'thanks')),
  text        TEXT NOT NULL,
  posted_at   TEXT NOT NULL
);

CREATE INDEX ripouts_by_fitting ON ripouts (unit_type, fitting_id);
CREATE INDEX choices_by_unit ON choices (unit_type, fitting_id);
CREATE INDEX matches_by_status ON matches (unit_type, status);
CREATE INDEX requests_by_status ON requests (unit_type, status);
CREATE INDEX messages_by_post ON messages (post_id);
"""


def path(data_dir=DATA_DIR):
    return Path(data_dir) / DB_FILE


def exists(data_dir=DATA_DIR):
    return path(data_dir).exists()


def connect(data_dir=DATA_DIR):
    """A connection with foreign keys enforced. Waits up to 10 s if another process is saving."""
    con = sqlite3.connect(path(data_dir), timeout=10, isolation_level=None)   # we open transactions ourselves
    con.execute("PRAGMA foreign_keys = ON")
    return con


@contextmanager
def transaction(data_dir=DATA_DIR):
    """`with transaction() as con:` commits when the block ends, rolls everything back if it raises."""
    con = connect(data_dir)
    try:
        con.execute("BEGIN IMMEDIATE")   # take the write lock now, so nobody saves in between
        yield con
        con.execute("COMMIT")
    except BaseException:
        con.execute("ROLLBACK")
        raise
    finally:
        con.close()


def create(data_dir=DATA_DIR):
    """Every table, empty. Keeps the file (the running app may have it open) and replaces its tables."""
    Path(data_dir).mkdir(parents=True, exist_ok=True)
    with transaction(data_dir) as con:
        for table in reversed(TABLES):
            con.execute(f"DROP TABLE IF EXISTS {table}")
        for statement in SCHEMA.split(";"):
            if statement.strip():
                con.execute(statement)


def read_tables(data_dir=DATA_DIR):
    """Every table as a DataFrame, in the order rows were saved."""
    con = connect(data_dir)
    try:
        return {t: pd.read_sql_query(f"SELECT * FROM {t} ORDER BY rowid", con) for t in TABLES}
    finally:
        con.close()


def _value(v):
    """What goes in a cell: empty text becomes NULL, NaN becomes NULL, everything else as it is."""
    if v is None or (isinstance(v, str) and v == "") or (isinstance(v, float) and v != v):
        return None
    return v


def insert(con, table, row):
    """INSERT one row from a dict of column -> value."""
    cols = list(row)
    con.execute(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                [_value(row[c]) for c in cols])


def insert_many(con, table, columns, rows):
    """INSERT many rows given as tuples in the order of `columns`."""
    con.executemany(f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join('?' * len(columns))})",
                    [[_value(v) for v in r] for r in rows])


def ensure_person(con, person_id, unit_type, role):
    """Add an owner or buyer the first time they save something (no-op if they exist)."""
    con.execute("INSERT OR IGNORE INTO people (person_id, unit_type, role) VALUES (?, ?, ?)",
                (person_id, unit_type, role))


def export_csv(data_dir=DATA_DIR, out_dir=None):
    """Write every table to <out_dir>/<table>.csv (default data/export/). Returns the folder."""
    out = Path(out_dir) if out_dir else Path(data_dir) / "export"
    out.mkdir(parents=True, exist_ok=True)
    for table, df in read_tables(data_dir).items():
        df.to_csv(out / f"{table}.csv", index=False)
    return out


if __name__ == "__main__":
    if sys.argv[1:] == ["export"]:
        print(f"Wrote every table as CSV to {export_csv()}/")
    else:
        print("Usage: python db.py export      (CSV copies of every table, for Excel)")
