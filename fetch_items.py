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