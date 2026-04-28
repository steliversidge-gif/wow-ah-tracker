import requests
import sqlite3
from datetime import datetime
import os
from dotenv import load_dotenv

load_dotenv()

# --- Configuration ---
CLIENT_ID = os.getenv("BLIZZARD_CLIENT_ID")
CLIENT_SECRET = os.getenv("BLIZZARD_CLIENT_SECRET")

# Step 1: Access token
token_url="https://oauth.battle.net/token"
token_response = requests.post(
        token_url,
        data={"grant_type":"client_credentials"},
        auth=(CLIENT_ID,CLIENT_SECRET)
)

print("status:", token_response.status_code)

token_data = token_response.json()
access_token = token_data["access_token"]

print("Token:", access_token)

# Intermediary Step
# realm_url = "https://eu.api.blizzard.com/data/wow/connected-realm/index"
headers = {"Authorization": f"Bearer {access_token}"}
params = {"namespace": "dynamic-eu", "locale": "en_GB"}

# realm_response = requests.get(realm_url, headers=headers, params=params)

# import json
# realms = realm_response.json()["connected_realms"]

# for realm in realms:
#     url = realm["href"]
#     detail = requests.get(url, headers=headers, params=params)
#     data = detail.json()
#     realm_names = [r["name"] for r in data["realms"]]
#     if "Draenor" in realm_names or "Arathor" in realm_names:
#         print(f"ID: {data['id']} - Realms: {realm_names}")

# Step 2: Get AH data
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