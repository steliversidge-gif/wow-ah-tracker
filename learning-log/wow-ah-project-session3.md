# WoW Auction House Tracker — Session 3 Plan

## The Goal

Turn your tool from "useful but requires Wowhead lookups" into a self-contained dashboard. By the end of this session, your output shows item names instead of IDs, tracks whether items sold or expired, and combines everything into one view.

---

## What You'll Learn This Session

- **Building a lookup table** — caching item names from Blizzard's API so you don't re-fetch them every time
- **Tracking auction lifecycles** — determining whether an item sold or expired using time_left data
- **Combining multiple data sources** — joining turnover, pricing, and item data into a single output
- **Rate limiting** — being respectful with API calls when fetching hundreds of item names

---

## Step 0 — Create an Item Names Table (~15 mins)

You'll store item names locally so you only need to look each one up once. Add this to your `db_setup.py` and run it:

```python
cursor.execute("""
    CREATE TABLE IF NOT EXISTS items (
        item_id INTEGER PRIMARY KEY,
        name TEXT,
        item_class TEXT,
        item_subclass TEXT,
        quality TEXT,
        level INTEGER,
        last_updated TEXT
    )
""")
```

This gives you a persistent cache of item metadata. Once you've looked up an item, you never need to fetch it again.

---

## Step 1 — Fetch Item Names from Blizzard's API (~60 mins)

Create a new file called `fetch_items.py`. This script finds all item IDs in your auctions table that don't have names yet, then looks them up via Blizzard's Item API.

```python
import requests
import sqlite3
from datetime import datetime
import time

# --- Auth (same as ah_tracker.py) ---
CLIENT_ID = "your-client-id"
CLIENT_SECRET = "your-client-secret"

token_response = requests.post(
    "https://oauth.battle.net/token",
    data={"grant_type": "client_credentials"},
    auth=(CLIENT_ID, CLIENT_SECRET)
)
access_token = token_response.json()["access_token"]

headers = {"Authorization": f"Bearer {access_token}"}
params = {"namespace": "static-eu", "locale": "en_GB"}

# --- Database ---
conn = sqlite3.connect("ah_data.db")
cursor = conn.cursor()

# Find item IDs that we don't have names for yet
cursor.execute("""
    SELECT DISTINCT a.item_id
    FROM auctions a
    LEFT JOIN items i ON a.item_id = i.item_id
    WHERE i.item_id IS NULL
    ORDER BY a.item_id
""")
missing_items = cursor.fetchall()
print(f"Items to look up: {len(missing_items)}")

# Fetch each item from Blizzard's API
count = 0
errors = 0
for row in missing_items:
    item_id = row[0]

    try:
        url = f"https://eu.api.blizzard.com/data/wow/item/{item_id}"
        response = requests.get(url, headers=headers, params=params)

        if response.status_code == 200:
            data = response.json()
            name = data.get("name", "Unknown")
            item_class = data.get("item_class", {}).get("name", "Unknown")
            item_subclass = data.get("item_subclass", {}).get("name", "Unknown")
            quality = data.get("quality", {}).get("name", "Unknown")
            level = data.get("level", 0)

            cursor.execute("""
                INSERT OR REPLACE INTO items
                (item_id, name, item_class, item_subclass, quality, level, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (item_id, name, item_class, item_subclass, quality, level,
                  datetime.now().strftime("%Y-%m-%d %H:%M:%S")))

            count += 1
            if count % 50 == 0:
                conn.commit()
                print(f"  Fetched {count} items...")
        else:
            errors += 1
            if errors % 10 == 0:
                print(f"  {errors} errors so far (last: {response.status_code} for item {item_id})")

    except Exception as e:
        errors += 1
        print(f"  Error fetching item {item_id}: {e}")

    # Rate limiting — don't hammer Blizzard's API
    time.sleep(0.05)

conn.commit()
conn.close()
print(f"\nDone. Fetched {count} items, {errors} errors.")
```

**Key things to understand:**

- **`namespace: static-eu`** — item metadata uses the `static` namespace, not `dynamic`. Dynamic is for things that change (auctions, realm status). Static is for things that don't (item definitions).
- **`time.sleep(0.05)`** — pauses 50ms between each request. You're well within rate limits but it's good practice. With thousands of items this will take a few minutes.
- **`INSERT OR REPLACE`** — if you re-run this, it updates existing entries rather than failing.
- **Committing every 50 items** — if the script crashes partway through, you don't lose everything you've already fetched.
- **Error handling** — some item IDs might not exist in Blizzard's database (removed items, internal items). The script logs errors but keeps going.

**First run will be slow** — you probably have 10,000+ unique item IDs in your auctions table. At 50ms per request, that's about 8-10 minutes. Subsequent runs only fetch new items, so they'll be much faster.

---

## Step 2 — Add Names to Your Queries (~30 mins)

Now update your `query_ah.py` to join against the items table. Replace your flip query's SELECT and print section:

```python
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
    LIMIT 20
""")

print(f"\n{'ID':<10} {'Name':<30} {'Type':<15} {'Draenor':<10} {'Arathor':<10} {'Delta':<10} {'D':<4} {'A':<4}")
print("-" * 93)
for row in cursor.fetchall():
    print(f"{row[0]:<10} {row[1][:28]:<30} {row[2][:13]:<15} {row[3]:<10.0f} {row[4]:<10.0f} {row[5]:<10.0f} {row[6]:<4} {row[7]:<4}")
```

**Note:** `row[1][:28]` truncates the item name to 28 characters so it doesn't break the table formatting. `COALESCE(i.name, 'Unknown')` handles items you haven't looked up yet.

Also update the flip query to only use the **latest snapshot** — notice the subquery `snapshot_time = (SELECT MAX(snapshot_time) FROM auctions WHERE realm_id = ...)`. This ensures you're always looking at current prices, not mixing in old data.

---

## Step 3 — Add Names to Turnover Analysis (~15 mins)

Same principle — join the items table into your turnover query. Update the SELECT to include:

```sql
COALESCE(i.name, 'Unknown') as item_name
```

And add:

```sql
LEFT JOIN items i ON cp.item_id = i.item_id
```

Then update the print formatting to include the name column.

I'm leaving this one for you to implement — you've seen the pattern now. If you get stuck, the flip query above shows exactly how to do it.

---

## Step 4 — Create the Auction Tracking Table (~30 mins)

This is the sold/expired tracking you designed. Add to `db_setup.py`:

```python
cursor.execute("""
    CREATE TABLE IF NOT EXISTS auction_tracking (
        auction_id INTEGER,
        realm_id INTEGER,
        item_id INTEGER,
        buyout INTEGER,
        first_seen TEXT,
        last_seen TEXT,
        first_time_left TEXT,
        last_time_left TEXT,
        consecutive_snapshots INTEGER DEFAULT 1,
        outcome TEXT DEFAULT 'ACTIVE',
        PRIMARY KEY (auction_id, realm_id)
    )
""")
```

Then create `update_tracking.py` — run this after each `ah_tracker.py` run:

```python
import sqlite3

conn = sqlite3.connect("ah_data.db")
cursor = conn.cursor()

# Get the two most recent snapshots
cursor.execute("""
    SELECT DISTINCT snapshot_time FROM auctions
    ORDER BY snapshot_time DESC LIMIT 2
""")
snapshots = cursor.fetchall()

if len(snapshots) < 2:
    print("Need at least 2 snapshots.")
    conn.close()
    exit()

latest = snapshots[0][0]
previous = snapshots[1][0]
print(f"Updating tracking: {previous} → {latest}")

# Step 1: Insert new auctions (seen for the first time)
cursor.execute("""
    INSERT OR IGNORE INTO auction_tracking
    (auction_id, realm_id, item_id, buyout, first_seen, last_seen, first_time_left, last_time_left)
    SELECT auction_id, realm_id, item_id, buyout, snapshot_time, snapshot_time, time_left, time_left
    FROM auctions
    WHERE snapshot_time = ?
""", (latest,))
new_count = cursor.rowcount
print(f"  New auctions tracked: {new_count}")

# Step 2: Update existing auctions still present
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
updated_count = cursor.rowcount
print(f"  Auctions updated: {updated_count}")

# Step 3: Determine outcome for disappeared auctions
# Calculate hours between first_seen and last_seen
cursor.execute("""
    UPDATE auction_tracking
    SET outcome = CASE
        -- First seen as VERY_LONG and disappeared quickly = likely sold
        WHEN first_time_left = 'VERY_LONG'
             AND (julianday(?) - julianday(last_seen)) * 24 < 12
             THEN 'LIKELY_SOLD'
        -- First seen as LONG and disappeared quickly
        WHEN first_time_left = 'LONG'
             AND (julianday(?) - julianday(last_seen)) * 24 < 2
             THEN 'LIKELY_SOLD'
        -- Was tracked for many snapshots and time_left degraded = likely expired
        WHEN last_time_left = 'SHORT'
             AND consecutive_snapshots >= 4
             THEN 'LIKELY_EXPIRED'
        -- Was VERY_LONG and enough time passed for it to expire
        WHEN first_time_left = 'VERY_LONG'
             AND (julianday(?) - julianday(first_seen)) * 24 >= 48
             THEN 'LIKELY_EXPIRED'
        -- Not enough info
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
resolved_count = cursor.rowcount
print(f"  Auctions resolved: {resolved_count}")

# Summary
cursor.execute("""
    SELECT outcome, COUNT(*) FROM auction_tracking
    GROUP BY outcome
""")
print("\nTracking summary:")
for row in cursor.fetchall():
    print(f"  {row[0]}: {row[1]}")

conn.commit()
conn.close()
```

**How the outcome logic works:**

- **LIKELY_SOLD** — disappeared before its time window could have expired. An auction first seen as VERY_LONG (12-48 hours remaining) that vanishes within 12 hours almost certainly sold.
- **LIKELY_EXPIRED** — time_left degraded to SHORT over multiple snapshots, or enough time has passed since first_seen for the auction duration to have elapsed.
- **UNKNOWN** — not enough data to determine. This is the honest answer when your snapshots are too far apart to tell.

The classification gets more accurate with more frequent snapshots. Hourly snapshots would give you high confidence. Your current 3-4 hour gaps are decent but will produce more UNKNOWNs.

---

## Step 5 — Sale Rate Query (~30 mins)

Once you've run `update_tracking.py` a few times, you can query actual sale rates:

```python
# Add this to query_ah.py or create a new file

cursor.execute("""
    SELECT
        t.item_id,
        COALESCE(i.name, 'Unknown') as item_name,
        COUNT(CASE WHEN t.outcome = 'LIKELY_SOLD' THEN 1 END) as sold,
        COUNT(CASE WHEN t.outcome = 'LIKELY_EXPIRED' THEN 1 END) as expired,
        COUNT(CASE WHEN t.outcome = 'ACTIVE' THEN 1 END) as active,
        COUNT(CASE WHEN t.outcome = 'UNKNOWN' THEN 1 END) as unknown,
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

print(f"\n{'ID':<10} {'Name':<25} {'Sold':<6} {'Exp':<6} {'Act':<6} {'Sale%':<8} {'AvgGold':<10}")
print("-" * 71)
for row in cursor.fetchall():
    sale_pct = f"{row[6]:.1f}%" if row[6] else "N/A"
    avg_gold = f"{row[7]:.0f}" if row[7] else "N/A"
    print(f"{row[0]:<10} {row[1][:23]:<25} {row[2]:<6} {row[3]:<6} {row[4]:<6} {sale_pct:<8} {avg_gold:<10}")
```

This gives you the holy grail: **what percentage of listings for each item actually sell, and at what average price.** Items with a high sale percentage and strong price are your best bets.

---

## Step 6 — Combined Dashboard (Optional Stretch Goal)

Once everything above works, the end goal is a single output:

```
ID     Name                   Draenor  Arathor  Delta   Gone  New  Sale%  Signal
233450 Mechforged Mantle       325555   13800    311755  5     2    78.2%  BUY ✓
```

This combines flip margins + turnover + sale rate into one line. Build this when you're comfortable with all the individual pieces.

---

## Running Order

1. Run `db_setup.py` (adds new tables)
2. Run `fetch_items.py` (populates item names — slow first time)
3. Run `ah_tracker.py` (pull fresh snapshot)
4. Run `update_tracking.py` (update auction lifecycle tracking)
5. Run `query_ah.py` (see your dashboard)

Steps 3-5 are your regular loop. Eventually you'll combine them into a single script.

---

## What You Learned This Session

- **API caching patterns** — fetch once, store locally, reuse forever
- **Rate limiting** — being a good API citizen
- **Static vs Dynamic namespaces** — Blizzard separates data that changes from data that doesn't
- **Lifecycle tracking** — determining outcomes from incomplete data
- **CASE statements in SQL** — conditional logic inside queries
- **NULLIF** — avoiding division by zero in percentage calculations

---

## What's Coming in Session 4

- **Automated scheduling** — running your tracker hourly without manual effort
- **Visualisation** — price trend charts using matplotlib or a web dashboard
- **Combining scripts** — one command to pull, track, and report
- **Filtering by item category** — focusing on markets you care about (gear, transmog, decor)
