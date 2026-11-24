# WoW Auction House Tracker — Session 4 Plan

## The Goal

Automate your tracker so it runs without you, combine your scattered scripts into a cleaner structure, and build a basic web dashboard so you can view your data in a browser instead of the terminal. Optionally, start using Git for version control.

---

## What You'll Learn This Session

- **Task scheduling** — running scripts automatically on a timer
- **Script consolidation** — combining related code into a clean workflow
- **Flask** — a lightweight Python web framework for building dashboards
- **HTML templates** — displaying data in a browser
- **Git basics** — tracking your changes (optional but recommended)

---

## Step 0 — Combine Your Scripts (~30 mins)

You currently have multiple files: `ah_tracker.py`, `fetch_items.py`, `update_tracking.py`, `query_ah.py`. The first three should run together every time you take a snapshot. Create a single `run_snapshot.py`:

```python
import requests
import sqlite3
from datetime import datetime
import time

# --- Configuration ---
CLIENT_ID = "your-client-id"
CLIENT_SECRET = "your-client-secret"
DB_PATH = "ah_data.db"

REALMS = {
    1403: "Draenor",
    1587: "Arathor"
}

# --- Auth ---
def get_access_token():
    response = requests.post(
        "https://oauth.battle.net/token",
        data={"grant_type": "client_credentials"},
        auth=(CLIENT_ID, CLIENT_SECRET)
    )
    return response.json()["access_token"]

# --- Snapshot ---
def pull_snapshot(access_token, conn):
    cursor = conn.cursor()
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {"namespace": "dynamic-eu", "locale": "en_GB"}
    snapshot_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"Snapshot time: {snapshot_time}")

    for realm_id, realm_name in REALMS.items():
        ah_url = f"https://eu.api.blizzard.com/data/wow/connected-realm/{realm_id}/auctions"
        ah_response = requests.get(ah_url, headers=headers, params=params)
        auctions = ah_response.json().get("auctions", [])
        print(f"  {realm_name}: {len(auctions)} listings")

        rows = []
        for auction in auctions:
            rows.append((
                auction["id"],
                auction["item"]["id"],
                auction.get("buyout", 0),
                auction.get("quantity", 1),
                auction.get("time_left", "UNKNOWN"),
                realm_id,
                snapshot_time
            ))

        cursor.executemany("""
            INSERT OR IGNORE INTO auctions
            (auction_id, item_id, buyout, quantity, time_left, realm_id, snapshot_time)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, rows)

    conn.commit()
    return snapshot_time

# --- Fetch New Item Names ---
def fetch_new_items(access_token, conn):
    cursor = conn.cursor()
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {"namespace": "static-eu", "locale": "en_GB"}

    cursor.execute("""
        SELECT DISTINCT a.item_id
        FROM auctions a
        LEFT JOIN items i ON a.item_id = i.item_id
        WHERE i.item_id IS NULL
    """)
    missing = cursor.fetchall()

    if not missing:
        print("  No new items to fetch.")
        return

    print(f"  Fetching {len(missing)} new item names...")
    count = 0
    for row in missing:
        item_id = row[0]
        try:
            url = f"https://eu.api.blizzard.com/data/wow/item/{item_id}"
            response = requests.get(url, headers=headers, params=params)
            if response.status_code == 200:
                data = response.json()
                cursor.execute("""
                    INSERT OR REPLACE INTO items
                    (item_id, name, item_class, item_subclass, quality, level, last_updated)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    item_id,
                    data.get("name", "Unknown"),
                    data.get("item_class", {}).get("name", "Unknown"),
                    data.get("item_subclass", {}).get("name", "Unknown"),
                    data.get("quality", {}).get("name", "Unknown"),
                    data.get("level", 0),
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                ))
                count += 1
        except Exception:
            pass
        time.sleep(0.05)

    conn.commit()
    print(f"  Fetched {count} new items.")

# --- Update Tracking ---
def update_tracking(conn, latest):
    cursor = conn.cursor()

    cursor.execute("""
        SELECT DISTINCT snapshot_time FROM auctions
        ORDER BY snapshot_time DESC LIMIT 2
    """)
    snapshots = cursor.fetchall()

    if len(snapshots) < 2:
        print("  Need at least 2 snapshots for tracking.")
        return

    previous = snapshots[1][0]
    print(f"  Tracking: {previous} → {latest}")

    # Insert new auctions
    cursor.execute("""
        INSERT OR IGNORE INTO auction_tracking
        (auction_id, realm_id, item_id, buyout, first_seen, last_seen, first_time_left, last_time_left)
        SELECT auction_id, realm_id, item_id, buyout, snapshot_time, snapshot_time, time_left, time_left
        FROM auctions
        WHERE snapshot_time = ?
    """, (latest,))

    # Update existing
    cursor.execute("""
        UPDATE auction_tracking
        SET last_seen = ?,
            last_time_left = (
                SELECT a.time_left FROM auctions a
                WHERE a.auction_id = auction_tracking.auction_id
                  AND a.realm_id = auction_tracking.realm_id
                  AND a.snapshot_time = ?
            ),
            consecutive_snapshots = consecutive_snapshots + 1
        WHERE outcome = 'ACTIVE'
          AND EXISTS (
              SELECT 1 FROM auctions a
              WHERE a.auction_id = auction_tracking.auction_id
                AND a.realm_id = auction_tracking.realm_id
                AND a.snapshot_time = ?
          )
    """, (latest, latest, latest))

    # Resolve disappeared auctions
    cursor.execute("""
        UPDATE auction_tracking
        SET outcome = CASE
            WHEN first_time_left = 'VERY_LONG'
                 AND (julianday(?) - julianday(last_seen)) * 24 < 12
                 THEN 'LIKELY_SOLD'
            WHEN first_time_left = 'LONG'
                 AND (julianday(?) - julianday(last_seen)) * 24 < 2
                 THEN 'LIKELY_SOLD'
            WHEN last_time_left = 'SHORT'
                 AND consecutive_snapshots >= 4
                 THEN 'LIKELY_EXPIRED'
            WHEN first_time_left = 'VERY_LONG'
                 AND (julianday(?) - julianday(first_seen)) * 24 >= 48
                 THEN 'LIKELY_EXPIRED'
            ELSE 'UNKNOWN'
        END
        WHERE outcome = 'ACTIVE'
          AND NOT EXISTS (
              SELECT 1 FROM auctions a
              WHERE a.auction_id = auction_tracking.auction_id
                AND a.realm_id = auction_tracking.realm_id
                AND a.snapshot_time = ?
          )
    """, (latest, latest, latest, latest))

    conn.commit()

    # Summary
    cursor.execute("SELECT outcome, COUNT(*) FROM auction_tracking GROUP BY outcome")
    for row in cursor.fetchall():
        print(f"    {row[0]}: {row[1]}")

# --- Main ---
if __name__ == "__main__":
    print("=== WoW AH Tracker ===")
    conn = sqlite3.connect(DB_PATH)

    print("\n1. Authenticating...")
    token = get_access_token()
    print("   Done.")

    print("\n2. Pulling snapshot...")
    snapshot = pull_snapshot(token, conn)

    print("\n3. Fetching new item names...")
    fetch_new_items(token, conn)

    print("\n4. Updating auction tracking...")
    update_tracking(conn, snapshot)

    conn.close()
    print("\n=== Complete ===")
```

**What's new here:**

- **Functions** — each task is wrapped in a `def` block. This is how real Python code is structured. Functions take inputs, do work, and optionally return results.
- **`if __name__ == "__main__"`** — this means "only run this code if the file is executed directly." It's a Python convention that lets you import functions from this file into other files without them running automatically.
- **Single database connection** — instead of each script opening and closing its own connection, one connection is shared and closed at the end.

---

## Step 1 — Automate with Task Scheduler (~30 mins)

You're on Windows, so you'll use **Task Scheduler** to run `run_snapshot.py` automatically.

### Create a batch file first

Create `run_tracker.bat` in your project folder:

```batch
@echo off
cd /d C:\Users\Steli\ClaudeCode\WoW AH Project
C:\Users\Steli\AppData\Local\Python\pythoncore-3.14-64\python.exe run_snapshot.py >> tracker_log.txt 2>&1
```

This runs your script and logs the output to `tracker_log.txt` so you can check what happened.

Test it first by double-clicking the `.bat` file. If it works, set up the schedule:

### Set up Task Scheduler

1. Open **Task Scheduler** (search for it in Start menu)
2. Click **Create Basic Task**
3. Name: "WoW AH Tracker"
4. Trigger: **Daily**
5. Start time: pick any time, then set **Repeat task every: 1 hour** for a duration of **Indefinitely**
6. Action: **Start a program**
7. Program: Browse to your `run_tracker.bat` file
8. Tick **"Run whether user is logged on or not"** in the task properties

Your tracker will now run every hour automatically. Check `tracker_log.txt` to verify it's working.

### Data cleanup

Remember the 30-day TTL from Blizzard's ToS. Add this to the end of `run_snapshot.py`, before `conn.close()`:

```python
    print("\n5. Cleaning old data...")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM auctions WHERE snapshot_time < datetime('now', '-30 days')")
    deleted = cursor.rowcount
    if deleted > 0:
        print(f"   Removed {deleted} old auction records.")
    conn.commit()
```

---

## Step 2 — Build a Web Dashboard with Flask (~90 mins)

### Install Flask

```
pip install flask
```

### Create the app

Create a file called `dashboard.py`:

```python
from flask import Flask, render_template
import sqlite3

app = Flask(__name__)
DB_PATH = "ah_data.db"

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # Access columns by name instead of index
    return conn

@app.route("/")
def home():
    conn = get_db()
    cursor = conn.cursor()

    # Snapshot info
    cursor.execute("SELECT COUNT(*) as total FROM auctions")
    total_auctions = cursor.fetchone()["total"]

    cursor.execute("SELECT COUNT(DISTINCT snapshot_time) as count FROM auctions")
    snapshot_count = cursor.fetchone()["count"]

    cursor.execute("SELECT MAX(snapshot_time) as latest FROM auctions")
    latest_snapshot = cursor.fetchone()["latest"]

    conn.close()
    return render_template("home.html",
        total_auctions=total_auctions,
        snapshot_count=snapshot_count,
        latest_snapshot=latest_snapshot
    )

@app.route("/flips")
def flips():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        WITH buyout_listings_draenor AS (
            SELECT item_id, MIN(buyout) / 10000 as min_gold, COUNT(*) as listings
            FROM auctions
            WHERE realm_id = 1403
            AND snapshot_time = (SELECT MAX(snapshot_time) FROM auctions WHERE realm_id = 1403)
            GROUP BY item_id
        ),
        buyout_listings_arathor AS (
            SELECT item_id, MIN(buyout) / 10000 as min_gold, COUNT(*) as listings
            FROM auctions
            WHERE realm_id = 1587
            AND snapshot_time = (SELECT MAX(snapshot_time) FROM auctions WHERE realm_id = 1587)
            GROUP BY item_id
        )
        SELECT
            dr.item_id,
            COALESCE(i.name, 'Unknown') as item_name,
            COALESCE(i.item_subclass, '') as subclass,
            dr.min_gold as draenor_gold,
            ar.min_gold as arathor_gold,
            dr.min_gold - ar.min_gold as delta,
            dr.listings as dr_listings,
            ar.listings as ar_listings
        FROM buyout_listings_draenor dr
        JOIN buyout_listings_arathor ar ON dr.item_id = ar.item_id
        LEFT JOIN items i ON dr.item_id = i.item_id
        WHERE dr.min_gold > 100
          AND ar.min_gold > 100
          AND dr.min_gold < 2000000
          AND ar.min_gold < 2000000
          AND dr.listings >= 3
          AND ar.listings >= 3
        ORDER BY ABS(dr.min_gold - ar.min_gold) DESC
        LIMIT 30
    """)
    flips = cursor.fetchall()
    conn.close()
    return render_template("flips.html", flips=flips)

@app.route("/turnover")
def turnover():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT DISTINCT snapshot_time FROM auctions
        ORDER BY snapshot_time DESC LIMIT 2
    """)
    snapshots = cursor.fetchall()

    if len(snapshots) < 2:
        conn.close()
        return render_template("turnover.html", items=[], message="Need at least 2 snapshots.")

    latest = snapshots[0]["snapshot_time"]
    previous = snapshots[1]["snapshot_time"]

    cursor.execute("""
        WITH prev AS (
            SELECT realm_id, item_id, auction_id, buyout
            FROM auctions WHERE snapshot_time = ?
        ),
        curr AS (
            SELECT realm_id, item_id, auction_id, buyout
            FROM auctions WHERE snapshot_time = ?
        ),
        disappeared AS (
            SELECT p.realm_id, p.item_id, COUNT(*) as gone
            FROM prev p
            LEFT JOIN curr c ON p.auction_id = c.auction_id AND p.realm_id = c.realm_id
            WHERE c.auction_id IS NULL
            GROUP BY p.realm_id, p.item_id
        ),
        appeared AS (
            SELECT c.realm_id, c.item_id, COUNT(*) as new_count
            FROM curr c
            LEFT JOIN prev p ON c.auction_id = p.auction_id AND c.realm_id = p.realm_id
            WHERE p.auction_id IS NULL
            GROUP BY c.realm_id, c.item_id
        ),
        held AS (
            SELECT c.realm_id, c.item_id, COUNT(*) as held_count
            FROM curr c
            INNER JOIN prev p ON c.auction_id = p.auction_id AND c.realm_id = p.realm_id
            GROUP BY c.realm_id, c.item_id
        ),
        current_prices AS (
            SELECT realm_id, item_id, MIN(buyout) / 10000 as min_gold, COUNT(*) as listings
            FROM auctions WHERE snapshot_time = ?
            GROUP BY realm_id, item_id
        )
        SELECT
            cp.item_id,
            COALESCE(i.name, 'Unknown') as item_name,
            cp.realm_id,
            cp.min_gold,
            COALESCE(d.gone, 0) as gone,
            COALESCE(a.new_count, 0) as new_listings,
            COALESCE(h.held_count, 0) as held,
            COALESCE(d.gone, 0) - COALESCE(a.new_count, 0) as net_demand
        FROM current_prices cp
        LEFT JOIN disappeared d ON cp.item_id = d.item_id AND cp.realm_id = d.realm_id
        LEFT JOIN appeared a ON cp.item_id = a.item_id AND cp.realm_id = a.realm_id
        LEFT JOIN held h ON cp.item_id = h.item_id AND cp.realm_id = h.realm_id
        LEFT JOIN items i ON cp.item_id = i.item_id
        WHERE cp.min_gold > 100
          AND cp.min_gold < 9999999
          AND (COALESCE(d.gone, 0) > 0 OR COALESCE(a.new_count, 0) > 0)
        ORDER BY (COALESCE(d.gone, 0) - COALESCE(a.new_count, 0)) DESC
        LIMIT 30
    """, (previous, latest, latest))

    items = cursor.fetchall()
    conn.close()
    return render_template("turnover.html",
        items=items,
        latest=latest,
        previous=previous,
        message=None
    )

@app.route("/sales")
def sales():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            t.item_id,
            COALESCE(i.name, 'Unknown') as item_name,
            COUNT(CASE WHEN t.outcome = 'LIKELY_SOLD' THEN 1 END) as sold,
            COUNT(CASE WHEN t.outcome = 'LIKELY_EXPIRED' THEN 1 END) as expired,
            COUNT(CASE WHEN t.outcome = 'ACTIVE' THEN 1 END) as active,
            ROUND(
                COUNT(CASE WHEN t.outcome = 'LIKELY_SOLD' THEN 1 END) * 100.0 /
                NULLIF(COUNT(CASE WHEN t.outcome IN ('LIKELY_SOLD', 'LIKELY_EXPIRED') THEN 1 END), 0),
                1
            ) as sale_pct,
            AVG(CASE WHEN t.outcome = 'LIKELY_SOLD' THEN t.buyout / 10000 END) as avg_sold_gold
        FROM auction_tracking t
        LEFT JOIN items i ON t.item_id = i.item_id
        GROUP BY t.item_id
        HAVING sold + expired >= 5
        ORDER BY sale_pct DESC
        LIMIT 30
    """)
    items = cursor.fetchall()
    conn.close()
    return render_template("sales.html", items=items)

if __name__ == "__main__":
    app.run(debug=True, port=5000)
```

**Key concepts:**

- **`@app.route("/")`** — a **decorator** that tells Flask "when someone visits this URL, run this function." Each route is a different page.
- **`render_template`** — loads an HTML file and injects your data into it. This is how the backend sends data to the frontend.
- **`conn.row_factory = sqlite3.Row`** — lets you access columns by name (`row["item_name"]`) instead of index (`row[1]`). Much cleaner and fixes the index-shifting problem you hit earlier.
- **`debug=True`** — auto-reloads when you change code. Only use this locally, never in production.

---

## Step 3 — Create HTML Templates (~60 mins)

Flask looks for templates in a `templates` folder. Create `templates/` in your project directory.

### templates/base.html

This is the shared layout every page uses:

```html
<!DOCTYPE html>
<html>
<head>
    <title>WoW AH Tracker</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            background: #1a1a2e;
            color: #e0e0e0;
            margin: 0;
            padding: 20px;
        }
        nav {
            background: #16213e;
            padding: 15px 20px;
            margin: -20px -20px 20px -20px;
            display: flex;
            gap: 20px;
        }
        nav a {
            color: #00d4ff;
            text-decoration: none;
            font-weight: bold;
        }
        nav a:hover { color: #ffffff; }
        h1 { color: #00d4ff; }
        h2 { color: #a0a0c0; }
        table {
            border-collapse: collapse;
            width: 100%;
            margin-top: 10px;
        }
        th {
            background: #16213e;
            color: #00d4ff;
            padding: 10px 12px;
            text-align: left;
            border-bottom: 2px solid #00d4ff;
        }
        td {
            padding: 8px 12px;
            border-bottom: 1px solid #2a2a4a;
        }
        tr:hover { background: #1f1f3a; }
        .positive { color: #00ff88; }
        .negative { color: #ff4444; }
        .neutral { color: #888; }
        .buy { color: #00ff88; font-weight: bold; }
        .watch { color: #ffaa00; }
        .avoid { color: #ff4444; }
        .stat-cards {
            display: flex;
            gap: 20px;
            margin-bottom: 20px;
        }
        .stat-card {
            background: #16213e;
            padding: 20px;
            border-radius: 8px;
            flex: 1;
        }
        .stat-card h3 { margin: 0; color: #a0a0c0; font-size: 14px; }
        .stat-card .value { font-size: 28px; color: #00d4ff; margin-top: 5px; }
    </style>
</head>
<body>
    <nav>
        <a href="/">Dashboard</a>
        <a href="/flips">Flip Finder</a>
        <a href="/turnover">Turnover</a>
        <a href="/sales">Sale Rates</a>
    </nav>
    {% block content %}{% endblock %}
</body>
</html>
```

### templates/home.html

```html
{% extends "base.html" %}
{% block content %}
<h1>WoW AH Tracker</h1>
<div class="stat-cards">
    <div class="stat-card">
        <h3>Total Auctions Stored</h3>
        <div class="value">{{ "{:,}".format(total_auctions) }}</div>
    </div>
    <div class="stat-card">
        <h3>Snapshots Taken</h3>
        <div class="value">{{ snapshot_count }}</div>
    </div>
    <div class="stat-card">
        <h3>Latest Snapshot</h3>
        <div class="value" style="font-size: 18px;">{{ latest_snapshot }}</div>
    </div>
</div>
{% endblock %}
```

### templates/flips.html

```html
{% extends "base.html" %}
{% block content %}
<h1>Flip Finder</h1>
<p>Items with the largest price difference between Draenor and Arathor.</p>
<table>
    <tr>
        <th>ID</th>
        <th>Name</th>
        <th>Type</th>
        <th>Draenor</th>
        <th>Arathor</th>
        <th>Delta</th>
        <th>D.List</th>
        <th>A.List</th>
    </tr>
    {% for flip in flips %}
    <tr>
        <td>{{ flip["item_id"] }}</td>
        <td>{{ flip["item_name"] }}</td>
        <td>{{ flip["subclass"] }}</td>
        <td>{{ "{:,.0f}".format(flip["draenor_gold"]) }}g</td>
        <td>{{ "{:,.0f}".format(flip["arathor_gold"]) }}g</td>
        <td class="{{ 'positive' if flip['delta'] > 0 else 'negative' }}">
            {{ "{:,.0f}".format(flip["delta"]) }}g
        </td>
        <td>{{ flip["dr_listings"] }}</td>
        <td>{{ flip["ar_listings"] }}</td>
    </tr>
    {% endfor %}
</table>
{% endblock %}
```

### templates/turnover.html

```html
{% extends "base.html" %}
{% block content %}
<h1>Turnover Analysis</h1>
{% if message %}
<p>{{ message }}</p>
{% else %}
<p>{{ previous }} → {{ latest }}</p>
<table>
    <tr>
        <th>ID</th>
        <th>Name</th>
        <th>Realm</th>
        <th>Price</th>
        <th>Gone</th>
        <th>New</th>
        <th>Held</th>
        <th>Net</th>
        <th>Signal</th>
    </tr>
    {% for item in items %}
    {% set net = item["net_demand"] %}
    {% set price = item["min_gold"] %}
    <tr>
        <td>{{ item["item_id"] }}</td>
        <td>{{ item["item_name"] }}</td>
        <td>{{ "Draenor" if item["realm_id"] == 1403 else "Arathor" }}</td>
        <td>{{ "{:,.0f}".format(price) }}g</td>
        <td>{{ item["gone"] }}</td>
        <td>{{ item["new_listings"] }}</td>
        <td>{{ item["held"] }}</td>
        <td class="{{ 'positive' if net > 0 else ('negative' if net < 0 else 'neutral') }}">
            {{ net }}
        </td>
        <td class="{{ 'buy' if net > 2 and price > 500 else ('watch' if net > 0 else ('avoid' if net < -3 else 'neutral')) }}">
            {{ "BUY" if net > 2 and price > 500 else ("WATCH" if net > 0 and price > 100 else ("AVOID" if net < -3 else "—")) }}
        </td>
    </tr>
    {% endfor %}
</table>
{% endif %}
{% endblock %}
```

### templates/sales.html

```html
{% extends "base.html" %}
{% block content %}
<h1>Sale Rates</h1>
<p>Items with enough resolved auctions to calculate a sale rate.</p>
<table>
    <tr>
        <th>ID</th>
        <th>Name</th>
        <th>Sold</th>
        <th>Expired</th>
        <th>Active</th>
        <th>Sale %</th>
        <th>Avg Gold</th>
    </tr>
    {% for item in items %}
    <tr>
        <td>{{ item["item_id"] }}</td>
        <td>{{ item["item_name"] }}</td>
        <td>{{ item["sold"] }}</td>
        <td>{{ item["expired"] }}</td>
        <td>{{ item["active"] }}</td>
        <td class="{{ 'positive' if item['sale_pct'] and item['sale_pct'] > 70 else ('watch' if item['sale_pct'] and item['sale_pct'] > 40 else 'negative') }}">
            {{ "{:.1f}%".format(item["sale_pct"]) if item["sale_pct"] else "N/A" }}
        </td>
        <td>{{ "{:,.0f}g".format(item["avg_sold_gold"]) if item["avg_sold_gold"] else "N/A" }}</td>
    </tr>
    {% endfor %}
</table>
{% endblock %}
```

---

## Step 4 — Run the Dashboard

```
python dashboard.py
```

Then open your browser and go to `http://localhost:5000`. You should see your dashboard with navigation between pages.

**What just happened:** Flask starts a local web server on your computer. When your browser visits `localhost:5000`, Flask receives the request, runs the matching route function, queries the database, injects the data into the HTML template, and sends the rendered page back to your browser. That's the full stack loop.

---

## Step 5 — Git Version Control (Optional but Recommended) (~20 mins)

### Install Git

Download from [git-scm.com](https://git-scm.com/). Default options are fine.

### Initialise your project

In your project folder terminal:

```bash
git init
```

Create a `.gitignore` file to exclude things that shouldn't be tracked:

```
ah_data.db
tracker_log.txt
__pycache__/
*.pyc
```

Note: you're excluding `ah_data.db` because it's large and changes constantly. Your code is what matters.

### First commit

```bash
git add .
git commit -m "Initial commit: AH tracker with flip finder, turnover analysis, sale tracking, and Flask dashboard"
```

### Going forward

After making changes:

```bash
git add .
git commit -m "Description of what you changed"
```

This gives you a history of every change you've made. If you break something, you can always go back. It's also essential if you ever want to put this on GitHub as part of a portfolio.

---

## Your Project Structure

After this session, your folder should look like:

```
WoW AH Project/
├── ah_data.db              (your database — not in git)
├── run_snapshot.py          (combined tracker script)
├── query_ah.py              (terminal queries — keep for quick checks)
├── dashboard.py             (Flask web app)
├── run_tracker.bat          (Windows scheduler batch file)
├── tracker_log.txt          (log output — not in git)
├── db_setup.py              (database setup — run once)
├── .gitignore
└── templates/
    ├── base.html
    ├── home.html
    ├── flips.html
    ├── turnover.html
    └── sales.html
```

---

## What You Learned This Session

- **Functions** — organising code into reusable blocks with `def`
- **`if __name__ == "__main__"`** — Python's entry point convention
- **Flask routing** — mapping URLs to Python functions
- **HTML templates** — Jinja2 template syntax with `{{ }}` and `{% %}`
- **Template inheritance** — `{% extends "base.html" %}` for shared layouts
- **CSS basics** — styling a web page
- **Task scheduling** — automating scripts on Windows
- **Git basics** — tracking changes to your code

---

## What's Coming in Session 5+

- **Price history charts** — visualising trends over time with Chart.js or matplotlib
- **Search and filter** — find specific items in your dashboard
- **Item category pages** — browse by type (transmog, recipes, mounts, decor)
- **Wowhead links** — clickable item names that open on Wowhead
- **Mobile-friendly layout** — check your AH data from your phone
- **GitHub portfolio** — publish your project for potential employers to see
