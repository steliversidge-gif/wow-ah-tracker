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