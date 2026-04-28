from flask import Flask, render_template, request
import sqlite3

app = Flask(__name__)
DB_PATH = "ah_data.db"

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # Access columns by name instead of index
    return conn

@app.route("/")
def home():
    conn = get_db()
    cursor = conn.cursor()

    # Snapshot info
    cursor.execute("SELECT COUNT(*) as total FROM auctions")
    total_auctions = cursor.fetchone()["total"]

    cursor.execute("SELECT COUNT(DISTINCT snapshot_time) as count FROM auctions")
    snapshot_count = cursor.fetchone()["count"]

    cursor.execute("SELECT MAX(snapshot_time) as latest FROM auctions")
    latest_snapshot = cursor.fetchone()["latest"]

    conn.close()
    return render_template("home.html",
        total_auctions=total_auctions,
        snapshot_count=snapshot_count,
        latest_snapshot=latest_snapshot
    )

@app.route("/flips")
def flips():
    conn = get_db()
    cursor = conn.cursor()

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
        LIMIT 30
    """)
    flips = cursor.fetchall()
    conn.close()
    return render_template("flips.html", flips=flips)

@app.route("/turnover")
def turnover():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT DISTINCT snapshot_time FROM auctions
        ORDER BY snapshot_time DESC LIMIT 2
    """)
    snapshots = cursor.fetchall()

    if len(snapshots) < 2:
        conn.close()
        return render_template("turnover.html", items=[], message="Need at least 2 snapshots.")

    latest = snapshots[0]["snapshot_time"]
    previous = snapshots[1]["snapshot_time"]

    

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
        ORDER BY (COALESCE(d.gone, 0) - COALESCE(a.new_count, 0)) DESC
        LIMIT 30
    """, (previous, latest, latest))

    items = cursor.fetchall()
    conn.close()
    return render_template("turnover.html",
        items=items,
        latest=latest,
        previous=previous,
        message=None
    )

@app.route("/sales")
def sales():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            t.item_id,
            COALESCE(i.name, 'Unknown') as item_name,
            COUNT(CASE WHEN t.outcome = 'LIKELY_SOLD' THEN 1 END) as sold,
            COUNT(CASE WHEN t.outcome = 'LIKELY_EXPIRED' THEN 1 END) as expired,
            COUNT(CASE WHEN t.outcome = 'ACTIVE' THEN 1 END) as active,
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
    items = cursor.fetchall()
    conn.close()
    return render_template("sales.html", items=items)

@app.route("/opportunities")

def opportunities():
    # Get filter values from URL parameters
    min_profit = request.args.get("min_profit", 100, type=int)
    min_listings = request.args.get("min_listings", 3, type=int)
    item_type = request.args.get("item_type", "", type=str)
    sort_by = request.args.get("sort", "gone")

    valid_sorts = {
        "gone": "COALESCE(dg.gone, 0) DESC",
        "delta": "ABS(dp.min_gold - COALESCE(ap.min_gold, 0)) DESC",
        "sale_pct": "COALESCE(sr.sale_pct, 0) DESC",
        "price": "dp.min_gold DESC"
    }
    order_clause = valid_sorts.get(sort_by, valid_sorts["gone"])


    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT DISTINCT snapshot_time FROM auctions
        ORDER BY snapshot_time DESC LIMIT 2
    """)
    snapshots = cursor.fetchall()

    if len(snapshots) < 2:
        conn.close()
        return render_template("opportunities.html", items=[], message="Need at least 2 snapshots.")

    latest = snapshots[0]["snapshot_time"]
    previous = snapshots[1]["snapshot_time"]

    type_filter = ""
    params = [latest, latest, previous, latest, latest, min_profit, min_listings]

    if item_type:
        type_filter = "AND i.item_subclass = ?"
        params.append(item_type)

    query = f"""
        WITH draenor_prices AS (
            SELECT item_id, MIN(buyout) / 10000 as min_gold, COUNT(*) as listings
            FROM auctions
            WHERE realm_id = 1403 AND snapshot_time = ?
            GROUP BY item_id
        ),
        arathor_prices AS (
            SELECT item_id, MIN(buyout) / 10000 as min_gold, COUNT(*) as listings
            FROM auctions
            WHERE realm_id = 1587 AND snapshot_time = ?
            GROUP BY item_id
        ),
        prev_draenor AS (
            SELECT item_id, auction_id FROM auctions
            WHERE realm_id = 1403 AND snapshot_time = ?
        ),
        curr_draenor AS (
            SELECT item_id, auction_id FROM auctions
            WHERE realm_id = 1403 AND snapshot_time = ?
        ),
        draenor_gone AS (
            SELECT p.item_id, COUNT(*) as gone
            FROM prev_draenor p
            LEFT JOIN curr_draenor c ON p.auction_id = c.auction_id
            WHERE c.auction_id IS NULL
            GROUP BY p.item_id
        ),
        sale_rates AS (
            SELECT item_id,
                ROUND(
                    COUNT(CASE WHEN outcome = 'LIKELY_SOLD' THEN 1 END) * 100.0 /
                    NULLIF(COUNT(CASE WHEN outcome IN ('LIKELY_SOLD', 'LIKELY_EXPIRED') THEN 1 END), 0),
                    1
                ) as sale_pct
            FROM auction_tracking
            GROUP BY item_id
        )
        SELECT
            dp.item_id,
            COALESCE(i.name, 'Unknown') as item_name,
            COALESCE(i.item_subclass, '') as subclass,
            dp.min_gold as draenor_gold,
            COALESCE(ap.min_gold, 0) as arathor_gold,
            dp.min_gold - COALESCE(ap.min_gold, 0) as delta,
            dp.listings as dr_listings,
            COALESCE(ap.listings, 0) as ar_listings,
            COALESCE(dg.gone, 0) as gone,
            COALESCE(sr.sale_pct, 0) as sale_pct,
            (SELECT MIN(a2.buyout) / 10000 FROM auctions a2
             WHERE a2.item_id = dp.item_id AND a2.realm_id = 1403
               AND a2.snapshot_time >= datetime(?, '-48 hours')) as floor_48h
        FROM draenor_prices dp
        LEFT JOIN arathor_prices ap ON dp.item_id = ap.item_id
        LEFT JOIN items i ON dp.item_id = i.item_id
        LEFT JOIN draenor_gone dg ON dp.item_id = dg.item_id
        LEFT JOIN sale_rates sr ON dp.item_id = sr.item_id
        WHERE dp.min_gold > ?
            AND dp.min_gold < 2000000
            AND dp.listings >= ?
            {type_filter}
        ORDER BY {order_clause}
        LIMIT 40
    """

    cursor.execute(query, params)

    items = cursor.fetchall()
    conn.close()
    return render_template("opportunities.html",
        items=items,
        latest=latest,
        previous=previous,
        message=None
    )

if __name__ == "__main__":
    app.run(debug=True, port=5000)