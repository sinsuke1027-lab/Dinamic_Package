import sqlite3
import pandas as pd

conn = sqlite3.connect("inventory.db")
query = """
SELECT 
    i.id,
    i.name,
    i.item_type,
    i.departure_date,
    i.total_stock,
    SUM(b.quantity) as total_sold
FROM inventory i
LEFT JOIN booking_events b ON i.id = b.inventory_id
GROUP BY i.id
"""
df = pd.read_sql(query, conn)
conn.close()

df["departure_date"] = pd.to_datetime(df["departure_date"])
df["month"] = df["departure_date"].dt.month

def get_season(m):
    if m in [5, 7, 8]: return "Peak (繁忙期)"
    elif m in [2, 6, 11]: return "Off-Peak (閑散期)"
    else: return "Normal (中間期)"

df["season"] = df["month"].apply(get_season)
df["sales_rate"] = df["total_sold"] / df["total_stock"] * 100

summary = df.groupby(["season", "name"])["sales_rate"].mean().reset_index()
print(summary)

summary_overall = df.groupby("season")["sales_rate"].mean().reset_index()
print("\nOverall:")
print(summary_overall)
