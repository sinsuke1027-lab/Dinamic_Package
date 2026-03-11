import pandas as pd
import sqlite3
from model_evaluator import backtest_strategy

conn = sqlite3.connect('inventory.db')
inv_df = pd.read_sql("SELECT * FROM inventory LIMIT 1", conn)
events_df = pd.read_sql("SELECT * FROM booking_events WHERE inventory_id = ?", conn, params=(inv_df.iloc[0]['id'],))
conn.close()

if not events_df.empty:
    res = backtest_strategy("rule_based", inv_df.iloc[0], events_df, {})
    print("Success! MAPE:", res["mape"])
else:
    print("No events found.")
