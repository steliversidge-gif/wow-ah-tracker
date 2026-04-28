import requests
import sqlite3
from datetime import datetime
import time
import os
from dotenv import load_dotenv

load_dotenv()

# --- Configuration ---
CLIENT_ID = os.getenv("BLIZZARD_CLIENT_ID")
CLIENT_SECRET = os.getenv("BLIZZARD_CLIENT_SECRET")
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
    print(f"  Tracking: {previous} -> {latest}")

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

    print("\n5. Cleaning old data...")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM auctions WHERE snapshot_time < datetime('now', '-30 days')")
    deleted = cursor.rowcount
    if deleted > 0:
        print(f"   Removed {deleted} old auction records.")
    conn.commit()

    conn.close()
    print("\n=== Complete ===")