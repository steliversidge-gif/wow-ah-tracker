# WoW AH Tracker — Claude Code Brief

## Project Overview

A World of Warcraft Auction House price tracking and flip-finding tool. Built as a learning project to develop full-stack engineering skills. The tool pulls live auction data from Blizzard's Game Data API, stores it in SQLite, tracks auction lifecycles (sold vs expired), and surfaces opportunities via a Flask web dashboard.

## Location

`C:\Users\Steli\ClaudeCode\WoW AH Project\`

## Current File Structure

```
WoW AH Project/
├── ah_tracker.py              (original standalone tracker — superseded by run_snapshot.py)
├── run_snapshot.py             (combined script: auth, pull snapshots, fetch item names, update tracking)
├── query_ah.py                 (terminal-based queries — turnover, flips, sale rates)
├── db_setup.py                 (database table creation)
├── fetch_items.py              (standalone item name fetcher — now integrated into run_snapshot.py)
├── update_tracking.py          (standalone tracking updater — now integrated into run_snapshot.py)
├── dashboard.py                (Flask web app)
├── run_tracker.bat             (Windows Task Scheduler batch file, runs hourly)
├── tracker_log.txt             (log output from scheduled runs)
├── ah_data.db                  (SQLite database)
├── .gitignore                  (excludes ah_data.db, tracker_log.txt, __pycache__/)
└── templates/
    ├── base.html               (shared layout with nav and CSS)
    ├── home.html               (dashboard overview — snapshot count, total auctions)
    ├── flips.html              (cross-realm price comparison)
    ├── turnover.html           (listing movement analysis)
    ├── sales.html              (sale rate tracking)
    └── opportunities.html      (combined view with filters)
```

## Database Schema

### auctions
```sql
auction_id INTEGER,
item_id INTEGER,
buyout INTEGER,          -- in copper (divide by 10000 for gold)
quantity INTEGER,
time_left TEXT,          -- SHORT, MEDIUM, LONG, VERY_LONG
realm_id INTEGER,        -- 1403 = Draenor EU, 1587 = Arathor EU (connected with Hellfire, Runetotem, Kilrogg, Nagrand)
snapshot_time TEXT,
PRIMARY KEY (auction_id, realm_id, snapshot_time)
```

### items
```sql
item_id INTEGER PRIMARY KEY,
name TEXT,
item_class TEXT,
item_subclass TEXT,
quality TEXT,
level INTEGER,
last_updated TEXT
```

### auction_tracking
```sql
auction_id INTEGER,
realm_id INTEGER,
item_id INTEGER,
buyout INTEGER,
first_seen TEXT,
last_seen TEXT,
first_time_left TEXT,
last_time_left TEXT,
consecutive_snapshots INTEGER DEFAULT 1,
outcome TEXT DEFAULT 'ACTIVE',   -- ACTIVE, LIKELY_SOLD, LIKELY_EXPIRED, UNKNOWN
PRIMARY KEY (auction_id, realm_id)
```

## API Details

- **Auth:** OAuth2 client credentials flow against `https://oauth.battle.net/token`
- **Auction data:** `https://eu.api.blizzard.com/data/wow/connected-realm/{realm_id}/auctions` with `namespace=dynamic-eu`
- **Item data:** `https://eu.api.blizzard.com/data/wow/item/{item_id}` with `namespace=static-eu`
- **Rate limits:** 36,000 calls/hour, AH data updates roughly once per hour
- **Credentials** are hardcoded in run_snapshot.py (CLIENT_ID and CLIENT_SECRET)

## Known Issues and Pending Improvements

### 1. Cancel scans inflate turnover numbers
When a player cancels and relists an auction, the old auction_id disappears and a new one appears. The tool counts this as one "gone" and one "new", inflating both numbers. The tracking table may classify cancelled auctions as LIKELY_SOLD if they had VERY_LONG time remaining.

**Mitigation:** Net demand (gone - new) partially handles this. A more robust approach would compare total listing counts per item between snapshots rather than relying solely on individual auction IDs.

### 2. Profession equipment (bonus_lists/modifiers not stored)
Items like Sun-Blessed Blacksmith's Toolbox exist at multiple item levels (206, 212, 218, 225, 232) but share the same item_id. The tool treats them as one item, causing misleading price comparisons. Lower ilvl versions are byproducts of profession levelling and get dumped cheaply.

**Fix needed:** Store `bonus_lists` and `modifiers` from auction data to differentiate by item level. Until then, profession equipment should be excluded from flip analysis.

**Current workaround:** The subclass filter on the opportunities page can exclude profession-related categories.

### 3. 48-hour price floor flag
Added to the opportunities query to warn when current price is significantly above the recent floor — motivated by a real loss on Sun-Blessed Blacksmith's Toolboxes where the price crashed same-day from 4k to 890g.

### 4. Turnover page shows blank when snapshots are too close together
If two consecutive snapshots hit during the same Blizzard AH update window, the data is identical and no movement is detected. The page currently only compares the two most recent snapshots.

**Improvement needed:** Allow user to select comparison window (e.g. 1 hour, 3 hours, 6 hours back) similar to the filter controls on the opportunities page.

### 5. Troll listing filtering
Listings at or near gold cap (9,999,999g) are filtered out, and a minimum of 3 listings per realm is required. Max price filter is set to 2,000,000g to accommodate legitimate rare items early in the expansion. Arathor-side max filter was missing and has been partially addressed.

### 6. Data cleanup / TTL compliance
Blizzard ToS requires 30-day TTL on API data. A cleanup step exists in run_snapshot.py:
```sql
DELETE FROM auctions WHERE snapshot_time < datetime('now', '-30 days')
```
Aggregated summaries (daily averages, min/max) could be kept indefinitely as they're not raw player data.

## Features Discussed But Not Yet Built

### Sniper alerts
Flag when high-value items are listed significantly below historical average. Could notify via Discord webhook or similar. Requires sufficient price history to establish baselines.

### Scoring/recommendation engine
The end goal: a single confidence score per item combining sale rate, delta stability, turnover velocity, and floor proximity. Output should be a clear recommendation: "Buy [item] on [realm] for [price]. Expected sell price: [X]. Confidence: HIGH."

### Item category browsing
Filter opportunities by item type — transmog, mounts, pets, recipes, decor. The type filter exists on the opportunities page but could be expanded to dedicated category views.

### Wowhead links
Make item names clickable, linking to `https://www.wowhead.com/item={item_id}`.

### Price history charts
Visualise price trends over time for specific items using Chart.js or similar.

## User Context

- Steve has strong SQL skills and data analytics experience (previously at Shell)
- Python is relatively new — comfortable reading and adapting code but still building fluency with syntax
- This is a learning project — he wants to understand what the code does, not just have working code
- Primary characters on Draenor EU (connected realm 1403) and Arathor EU (connected realm 1587)
- The longer-term vision is a data-backed recommendation engine: "buy this item to flip, it will result in a profit"
- Data visualisation principle from Shell: reach the largest audience with maximum clarity for minimum effort
