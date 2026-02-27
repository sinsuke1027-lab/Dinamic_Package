import sqlite3
from backend.constants import DEFAULT_COST_RATIO

conn = sqlite3.connect('backend/inventory.db')
conn.row_factory = sqlite3.Row

# is_package = 1 (パッケージ) と 0 (単品) で分けてみる
query_group = f"""
    SELECT 
        be.is_package,
        COUNT(*) as count,
        SUM(be.sold_price) as sum_dyn_sales,
        SUM(CASE 
            WHEN be.sold_price >= be.base_price_at_sale THEN be.base_price_at_sale 
            ELSE 0 
        END) as sum_fix_sales,
        SUM(CASE 
            WHEN be.sold_price < be.base_price_at_sale THEN (i.base_price * {DEFAULT_COST_RATIO}) 
            ELSE 0 
        END) as sum_fix_waste
    FROM booking_events be
    JOIN inventory i ON be.inventory_id = i.id
    GROUP BY be.is_package
"""
print("\n=== By is_package ===")
for r in conn.execute(query_group):
    print(dict(r))

conn.close()
