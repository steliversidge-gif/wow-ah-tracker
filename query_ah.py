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

# Top deltas across realms
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

# --- Turnover Analysis ---

# Get the two most recent snapshot times
cursor.execute("""
    SELECT DISTINCT snapshot_time FROM auctions
    ORDER BY snapshot_time DESC LIMIT 2
""")
snapshots = cursor.fetchall()

if len(snapshots) < 2:
    print("Need at least 2 snapshots for turnover analysis.")
else:
    latest = snapshots[0][0]
    previous = snapshots[1][0]
    print(f"\nTurnover Analysis: {previous} → {latest}")
    print(f"{'ID':<10} {'Name':<30} {'Realm':<10} {'Price':<10} {'Gone':<6} {'New':<6} {'Held':<6} {'Trend':<8} {'Signal':<10}")
    print("-" * 70)

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
        ORDER BY net_demand DESC
        LIMIT 30
    """, (previous, latest, latest))

    for row in cursor.fetchall():
        item_id = row[0]
        item_name = row[1]
        realm = "Draenor" if row[2] == 1403 else "Arathor"
        price = row[3]
        gone = row[4]
        new = row[5]
        held = row[6]
        net = row[7]

        if net > 0:
            trend = "▲ DEMAND"
        elif net < 0:
            trend = "▼ SUPPLY"
        else:
            trend = "— FLAT"

        # Simple signal logic
        if net > 2 and price > 500:
            signal = "BUY ✓"
        elif net > 0 and price > 100:
            signal = "WATCH"
        elif net < -3:
            signal = "AVOID"
        else:
            signal = "—"

        print(f"{item_id:<10} {item_name[:28]:<30} {realm:<10} {price:<10.0f} {gone:<6} {new:<6} {held:<6} {trend:<8} {signal:<10}")

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


conn.close()