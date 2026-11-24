# WoW Auction House Tracker — Session 2 Plan

## The Goal

Store auction house snapshots in a database so you can track prices over time and identify flip opportunities. By the end of this session, your script will pull AH data and save it locally — every time you run it, you build more history.

---

## What You'll Learn This Session

- **SQLite** — a database that lives in a single file on your computer, built into Python (no install needed)
- **How applications talk to databases** — writing SQL from Python code
- **Database design** — structuring tables for the data you're collecting
- **Timestamps** — tagging snapshots so you know when prices were captured

---

## Why SQLite?

You already know SQL. SQLite lets you use that knowledge immediately — same SELECT, INSERT, WHERE syntax you already write. The difference is you're running it from Python code instead of a query tool. There's no server to install, no credentials to manage. It creates a single `.db` file in your project folder. Perfect for personal tools.

---

## Step 0 — Understand What You're Storing (~15 mins)

Before writing anything, look at the auction data you're already pulling. From last session, a single auction looks something like:

```json
{
    "id": 125072282,
    "item": {"id": 258033, "context": 16, "modifiers": [{"type": 28, "value": 1279}]},
    "buyout": 36000000,
    "quantity": 1,
    "time_left": "SHORT"
}
```

Think about what you actually need to store. Not everything — just what's useful for tracking prices and finding flips:

- **item_id** — what's being sold
- **buyout** — the price (in copper)
- **quantity** — how many in this listing
- **time_left** — how long until it expires
- **realm_id** — which connected realm (1403 or 1587)
- **snapshot_time** — when you captured this data

The auction `id` is useful too — it lets you avoid storing duplicates if you run the script twice during the same AH update window.

---

## Step 1 — Create Your Database and Table (~30 mins)

Create a new file called `db_setup.py`. This keeps your database code separate from your API code for now.

```python
import sqlite3

# Connect to (or create) the database file
conn = sqlite3.connect("ah_data.db")
cursor = conn.cursor()

# Create the auctions table
cursor.execute("""
    CREATE TABLE IF NOT EXISTS auctions (
        auction_id INTEGER,
        item_id INTEGER,
        buyout INTEGER,
        quantity INTEGER,
        time_left TEXT,
        realm_id INTEGER,
        snapshot_time TEXT,
        PRIMARY KEY (auction_id, realm_id, snapshot_time)
    )
""")

conn.commit()
conn.close()

print("Database created successfully.")
```

Run it: `python db_setup.py`

You should see "Database created successfully." and a new file called `ah_data.db` in your project folder.

**Pause and understand what happened:**

- `sqlite3.connect("ah_data.db")` — opens the database file, or creates it if it doesn't exist. This returns a **connection object**.
- `conn.cursor()` — creates a **cursor**, which is the thing that actually executes SQL statements. Think of it as your query window.
- `cursor.execute("""...""")` — runs a SQL statement. The triple quotes `"""` let you write multi-line strings. You'll recognise the SQL itself — it's standard CREATE TABLE.
- `IF NOT EXISTS` — means you can run this script repeatedly without errors. It only creates the table if it's not already there.
- `conn.commit()` — saves the changes. Without this, nothing is actually written.
- `conn.close()` — closes the connection. Good practice, like closing a file.

The **PRIMARY KEY** is a composite of auction_id + realm_id + snapshot_time. This prevents duplicate entries if you accidentally run the script twice in the same hour.

---

## Step 2 — Store Auction Data (~45 mins)

Now update your `ah_tracker.py` to save data into the database after pulling it from the API. Add these imports at the top of your file:

```python
import sqlite3
from datetime import datetime
```

Then replace your existing AH data section with:

```python
# Connect to database
conn = sqlite3.connect("ah_data.db")
cursor = conn.cursor()

# Timestamp for this snapshot
snapshot_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
print(f"Snapshot time: {snapshot_time}")

realms_to_track = {
    1403: "Draenor",
    1587: "Arathor"
}

for realm_id, realm_name in realms_to_track.items():
    ah_url = f"https://eu.api.blizzard.com/data/wow/connected-realm/{realm_id}/auctions"
    ah_response = requests.get(ah_url, headers=headers, params=params)
    auctions = ah_response.json().get("auctions", [])
    print(f"{realm_name}: {len(auctions)} listings")

    # Prepare data for insert
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

    # Bulk insert
    cursor.executemany("""
        INSERT OR IGNORE INTO auctions
        (auction_id, item_id, buyout, quantity, time_left, realm_id, snapshot_time)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, rows)

    print(f"  Stored {len(rows)} auctions from {realm_name}")

conn.commit()
conn.close()
print("Data saved to database.")
```

**Key things to understand:**

- `datetime.now().strftime(...)` — captures the current date and time as a formatted string. Every auction in this run gets the same timestamp so you know they came from the same snapshot.
- `auction.get("buyout", 0)` — this is a safer version of `auction["buyout"]`. If the key doesn't exist (some auctions use bids instead of buyouts), it returns `0` instead of crashing. You saw `.get()` before with `ah_response.json().get("auctions", [])`.
- `rows.append((...))` — building a list of tuples. Each tuple is one row to insert.
- `cursor.executemany(...)` — inserts all rows in one go rather than one at a time. Much faster for thousands of rows.
- The `?` placeholders — these prevent SQL injection (a security habit worth learning now, even for personal projects). Python fills in the values from each tuple.
- `INSERT OR IGNORE` — if a row with the same primary key already exists, it skips it instead of erroring. This is the deduplication.

---

## Step 3 — Query Your Data (~30 mins)

Create a new file called `query_ah.py`. This is where your SQL skills come back into play.

```python
import sqlite3

conn = sqlite3.connect("ah_data.db")
cursor = conn.cursor()

# How many auctions have we stored?
cursor.execute("SELECT COUNT(*) FROM auctions")
print(f"Total auctions stored: {cursor.fetchone()[0]}")

# How many snapshots do we have?
cursor.execute("SELECT DISTINCT snapshot_time FROM auctions ORDER BY snapshot_time")
snapshots = cursor.fetchall()
print(f"Snapshots taken: {len(snapshots)}")
for s in snapshots:
    print(f"  {s[0]}")

# Cheapest Silvermoon Curtains per realm
cursor.execute("""
    SELECT realm_id, MIN(buyout) / 10000 as min_gold, COUNT(*) as listings
    FROM auctions
    WHERE item_id = 262599
    GROUP BY realm_id
""")
print("\nSilvermoon Curtains:")
for row in cursor.fetchall():
    realm_name = "Draenor" if row[0] == 1403 else "Arathor"
    print(f"  {realm_name}: {row[1]}g ({row[2]} listings)")

conn.close()
```

This should feel familiar — it's just SQL. The only new bit is how results come back:
- `cursor.fetchone()` — returns a single row as a tuple
- `cursor.fetchall()` — returns all rows as a list of tuples

You can write any SQL you'd normally write. Try adding your own queries — top 10 most listed items, average prices, whatever interests you.

---

## Step 4 — Find Flip Margins (~45 mins)

This is what you actually want. Create `find_flips.py`:

```python
import sqlite3

conn = sqlite3.connect("ah_data.db")
cursor = conn.cursor()

# Find items that exist on both realms with different prices
# This looks at the most recent snapshot only
cursor.execute("""
    SELECT snapshot_time FROM auctions ORDER BY snapshot_time DESC LIMIT 1
""")
latest = cursor.fetchone()[0]

cursor.execute("""
    SELECT
        d.item_id,
        MIN(d.buyout) / 10000 as draenor_min_gold,
        MIN(a.buyout) / 10000 as arathor_min_gold,
        ROUND((MIN(d.buyout) - MIN(a.buyout)) * 100.0 / MIN(a.buyout), 1) as margin_pct,
        COUNT(DISTINCT d.auction_id) as draenor_listings,
        COUNT(DISTINCT a.auction_id) as arathor_listings
    FROM auctions d
    JOIN auctions a ON d.item_id = a.item_id
    WHERE d.realm_id = 1403
      AND a.realm_id = 1587
      AND d.snapshot_time = ?
      AND a.snapshot_time = ?
      AND d.buyout > 0
      AND a.buyout > 0
    GROUP BY d.item_id
    HAVING MIN(a.buyout) < MIN(d.buyout)
    ORDER BY (MIN(d.buyout) - MIN(a.buyout)) DESC
    LIMIT 20
""", (latest, latest))

results = cursor.fetchall()

print(f"Top 20 flip opportunities (buy Arathor, sell Draenor) — Snapshot: {latest}\n")
print(f"{'Item ID':<12} {'Draenor':<14} {'Arathor':<14} {'Margin %':<10} {'D.List':<8} {'A.List':<8}")
print("-" * 66)

for row in results:
    print(f"{row[0]:<12} {row[1]:<14.0f} {row[2]:<14.0f} {row[3]:<10.1f} {row[4]:<8} {row[5]:<8}")

conn.close()
```

This query joins the same table to itself — Draenor auctions on one side, Arathor on the other — and finds items where Arathor is cheaper. You'll get item IDs, not names (we'll fix that later). For now, look up interesting ones on Wowhead.

**You could also reverse the direction** — find items cheaper on Draenor to sell on Arathor. Just swap the realm IDs in the HAVING clause.

---

## Step 5 — Run It Multiple Times (~5 mins)

The real power comes from running `ah_tracker.py` at different times of day. Each run adds a new snapshot. After a few runs, your queries can start comparing prices over time:

```sql
-- Price history for an item
SELECT snapshot_time, realm_id, MIN(buyout) / 10000 as min_gold
FROM auctions
WHERE item_id = 262599
GROUP BY snapshot_time, realm_id
ORDER BY snapshot_time
```

Run your tracker a few times over the next couple of days. Even 3-4 snapshots will start showing patterns.

---

## What You Learned This Session

- **SQLite** — a zero-setup database perfect for personal tools
- **Connection and cursor pattern** — how Python talks to any SQL database
- **Parameterised queries** — using `?` placeholders instead of string formatting
- **Data pipeline basics** — pull from API → transform → store in database → query for insights
- **Self-join queries** — comparing the same table to itself (the flip finder)

---

## What's Coming in Session 3

- **Item name resolution** — turning item IDs into actual names using Blizzard's Item API
- **Automated scheduling** — running your tracker automatically every hour
- **Better analysis** — pandas DataFrames for more complex price analysis and visualisation

---

## Remember

- Run `db_setup.py` once to create the database
- Run `ah_tracker.py` each time you want a new snapshot
- Run `query_ah.py` or `find_flips.py` whenever you want to analyse
- Your database file `ah_data.db` persists between runs — that's the whole point
- You can open `ah_data.db` in any SQLite viewer if you want to browse the data manually (DB Browser for SQLite is a free, good option)
