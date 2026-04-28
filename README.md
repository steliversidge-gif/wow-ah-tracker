# WoW Auction House Tracker

A self-built, end-to-end data tool for tracking the World of Warcraft auction house, identifying cross-realm flip opportunities, and analysing item demand over time.

Built as a learning project to extend my data analytics background toward full-stack engineering — covering API integration, database design, automated data pipelines, and a Flask-based web dashboard.

## What It Does

The tool pulls live auction data from Blizzard's Game Data API on an hourly schedule, stores snapshots in SQLite, tracks the lifecycle of individual auctions (sold vs expired), resolves item names from a separate API, and surfaces actionable insights via a web dashboard.

### Dashboard Pages

- **Home** — overview of stored data, snapshot count, latest pull
- **Flip Finder** — items with the largest price differences between connected realms (Draenor EU and Arathor EU), filtered for credible listings
- **Turnover** — listing movement between snapshots: how many auctions disappeared (likely sold), how many appeared, how many are still sitting
- **Sale Rates** — calculated probability of an item selling vs expiring, based on tracked auction outcomes
- **Opportunities** — combined view with user-driven filters for price floor, listing depth, item type, and sort order

## Technical Stack

**Backend & Data**

- Python 3.14 — orchestration, API integration, data transformation
- SQLite — local persistent storage with composite primary keys for snapshot deduplication
- SQL — CTEs, self-joins, window functions, conditional aggregation for analytical queries
- Blizzard Game Data API — OAuth2 client credentials authentication, dynamic and static namespaces

**Web Layer**

- Flask — Python web framework serving the dashboard
- Jinja2 — template inheritance with a shared base layout
- HTML / CSS — custom dark theme, responsive table layouts
- JavaScript — client-side filter controls firing URL parameter requests

**Automation & Operations**

- Windows Task Scheduler — hourly snapshot runs
- Batch scripting — wrapper for scheduled execution and logging
- Git — version control, with .gitignore protecting credentials and large data files

## Architecture

```
┌─────────────────────┐
│ Windows Task        │
│ Scheduler (hourly)  │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐         ┌──────────────────┐
│ run_snapshot.py     │────────▶│ Blizzard API     │
│                     │         │ (OAuth2 + Data)  │
│ • Authenticate      │◀────────│                  │
│ • Pull AH snapshots │         └──────────────────┘
│ • Resolve new items │
│ • Update tracking   │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ SQLite Database     │
│                     │
│ • auctions          │
│ • items             │
│ • auction_tracking  │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐         ┌──────────────────┐
│ Flask Dashboard     │────────▶│ Browser UI       │
│ (dashboard.py)      │         │ (Jinja2 + HTML)  │
└─────────────────────┘         └──────────────────┘
```

## Key Design Decisions

**Composite primary keys** on the auctions table (`auction_id + realm_id + snapshot_time`) prevent duplicate inserts if a snapshot runs twice in the same hour.

**Static vs dynamic namespaces** — Blizzard separates data that changes (auctions, realm status) from data that doesn't (item definitions). Item names are fetched once and cached locally, dramatically reducing API calls.

**Auction lifecycle tracking** — individual auction IDs are tracked across snapshots. When one disappears, its `time_left` value is used to classify the outcome:

- An auction first seen with VERY_LONG time remaining (12-48 hours) that vanishes within 12 hours is classified `LIKELY_SOLD`
- An auction whose `time_left` degrades to SHORT over multiple snapshots is classified `LIKELY_EXPIRED`
- Insufficient data is classified `UNKNOWN` rather than guessed

This is the closest possible approximation of sale data without access to the in-game addon ecosystem that licensed tools like TSM rely on.

**Cross-realm flip filtering** — naïve cross-realm comparisons are dominated by troll listings (gold cap, scam pricing). The flip finder filters for credible markets: minimum 3 listings on each realm, prices within sensible bounds, exclusion of items with single-listing manipulation.

**48-hour price floor flag** on the opportunities view — motivated by a real loss on Sun-Blessed Blacksmith's Toolboxes where the price crashed same-day from 4k to 890g. The floor warning prevents repeat mistakes.

## Indexing

With ~160k rows per snapshot and hourly collection, the database grows by several million rows per week. At 26m rows, full-table scans on every query made the dashboard noticeably slow — query times dropped from milliseconds to seconds.

Indexes added to `db_setup.py`:

```sql
CREATE INDEX idx_auctions_snapshot ON auctions(snapshot_time);
CREATE INDEX idx_auctions_realm_snapshot ON auctions(realm_id, snapshot_time);
CREATE INDEX idx_auctions_item_realm ON auctions(item_id, realm_id);
CREATE INDEX idx_auctions_realm_snapshot_item ON auctions(realm_id, snapshot_time, item_id);
CREATE INDEX idx_tracking_item ON auction_tracking(item_id);
CREATE INDEX idx_tracking_outcome ON auction_tracking(outcome);
```

Each index targets a specific access pattern: snapshot lookups, realm-filtered queries, cross-realm joins, the GROUP BY clauses inside the CTEs, and the outcome-based aggregations on the tracking table. SQLite uses compound indexes left-to-right, so the column order matters — an index on `(realm_id, snapshot_time)` helps queries filtering on `realm_id` alone or both columns, but not queries filtering on `snapshot_time` alone.

Trade-off: indexes consume disk space (typically 10-30% of the indexed data) and slow down writes slightly. Both are acceptable for a read-heavy analytical workload.

## Known Limitations

- **Item-level variation** is not yet tracked. Items like profession equipment exist at multiple item levels but share the same item_id, leading to misleading price comparisons. Storing the `bonus_lists` and `modifiers` fields from auction data would resolve this.
- **Cancel scans** inflate turnover numbers. When a player cancels and relists, the old auction_id disappears and a new one appears — this looks like a sale and a new listing, but is neither. Net demand (gone minus new) partially mitigates this.
- **30-day TTL** is enforced via cleanup query in line with Blizzard's API terms of service.

## Project Files

- `run_snapshot.py` — combined orchestration script (auth, snapshot, item resolution, tracking)
- `dashboard.py` — Flask web application
- `query_ah.py` — terminal-based queries (kept for quick checks during development)
- `db_setup.py` — schema creation and indexes, run once
- `templates/` — Jinja2 templates for the dashboard
- `run_tracker.bat` — Windows Task Scheduler entry point
- `wow-ah-project-session*.md` — session-by-session learning notes

## Future Development

The current tool surfaces opportunities. The end goal is a recommendation engine that produces a single confidence score per item, combining sale rate, cross-realm price delta, turnover velocity, and proximity to recent price floors. The signal output should be a clear, actionable line:

> Buy [item] on [realm] for [price]. Expected sell price: [X]. Confidence: HIGH.

Specific features planned:

- **Item-level differentiation** via `bonus_lists` and `modifiers` storage, unlocking accurate analysis of profession equipment and other variable-ilvl items
- **Sniper alerts** for high-value items listed significantly below historical average, with notifications via Discord webhook or similar
- **Wowhead links** on item names for quick reference
- **Price history charts** to visualise trends over time
- **Improved cancel scan handling** by comparing total listing counts per item between snapshots, rather than relying solely on individual auction IDs
- **Variable comparison windows** for the turnover analysis (1 hour, 3 hours, 6 hours back)

## Background

This is a personal project. I'm a data analytics professional with a strong SQL background, currently building toward full-stack engineering capability. The auction house tracker was chosen because it has genuine personal stakes — I play the game and use the tool — which makes the learning curve sustainable in a way that tutorial projects haven't been for me historically.

The session markdown files in this repository document the project's development as a learning journey, intentionally kept in the repo as a record of progression rather than a polished retrospective.
