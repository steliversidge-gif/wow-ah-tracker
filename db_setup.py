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

conn.commit()
conn.close()

print("Database created successfully.")